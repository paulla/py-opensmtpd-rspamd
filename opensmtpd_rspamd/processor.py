#! /usr/bin/env python3
#
# Copyright (c) 2018 Gilles Chehade <gilles@poolp.org>
#
# Permission to use, copy, modify, and/or distribute this software for any
# purpose with or without fee is hereby granted, provided that the above
# copyright notice and this permission notice appear in all copies.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
# WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
# ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
# WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
# ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
# OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
#

from opensmtpd.filters import smtp_in, proceed, reject, dataline

import email

import requests

sessions = {}

class Rspamd():
    def __init__(self):
        self.stream = smtp_in()

        self.stream.on_report('link-connect', link_connect, None)
        self.stream.on_report('link-disconnect', link_disconnect, None)
        self.stream.on_report('link-identify', link_identify, None)

        self.stream.on_report('tx-begin', tx_begin, None)
        self.stream.on_report('tx-mail', tx_mail, None)
        self.stream.on_report('tx-rcpt', tx_rcpt, None)
        self.stream.on_report('tx-data', tx_data, None)
        self.stream.on_report('tx-commit', tx_cleanup, None)
        self.stream.on_report('tx-rollback', tx_cleanup, None)

        self.stream.on_filter('commit', filter_commit, None)

        self.stream.on_filter('data-line', filter_data_line, None)
        
    def run(self):
        self.stream.run()



class Session():
    def __init__(self, session_id):
        self.session_id = session_id
        self.control = {}
        self.payload = []
        self.reject_reason = None
        self.message = None

    def push(self, line):
        if line != '.':
            self.payload.append(line)
            return True
        else:
            self.message = email.message_from_string('\n'.join(self.payload))
            return False


def link_connect(ctx, timestamp, session_id, args):
    rdns, _, laddr, _ = args

    session = sessions[session_id] = Session(session_id)
    session.control['Pass'] = 'all'
    src, port = laddr.split(':')
    if src != 'local':
        session.control['Ip'] = src
    if rdns:
        session.control['Hostname'] = rdns


def link_disconnect(ctx, timestamp, session_id, args):
    sessions.pop(session_id)


def link_identify(ctx, timestamp, session_id, args):
    helo = args[0]

    session = sessions[session_id]
    session.control['Helo'] = helo


def tx_begin(ctx, timestamp, session_id, args):
    tx_id = args[0]

    session = sessions[session_id]
    session.control['Queue-Id'] = tx_id


def tx_mail(ctx, timestamp, session_id, args):
    _, mail_from, status = args
    if status == 'ok':
        session = sessions[session_id]
        session.control['From'] = mail_from

def tx_rcpt(ctx, timestamp, session_id, args):
    _, rcpt_to, status = args
    if status == 'ok':
        session = sessions[session_id]
        session.control['Rcpt'] = rcpt_to

def tx_data(ctx, timestamp, session_id, args):
    _, status = args
    if status == 'ok':
        session = sessions[session_id]
        session.payload = []

def tx_cleanup(ctx, timestamp, session_id, args):
    session = sessions[session_id]
    session.control = {}

def filter_commit(ctx, timestamp, token, session_id, args):
    session = sessions[session_id]
    if session.reject_reason:
        reject(token, session_id, session.reject_reason)
    else:
        proceed(token, session_id)


def filter_data_line(ctx, timestamp, token, session_id, args):
    line = args[0]

    session = sessions[session_id]
    if session.push(line):
        return

    try:
        res = requests.post('http://localhost:11333/checkv2',
                            headers=session.control,
                            data=str(session.message))
        jret = res.json()
    except:
        jret = {}

    data_output(token, session, jret)


def data_output(token, session, jret):
    ml = session.message

    if jret:
        if jret['action'] == 'rewrite subject':
            del ml['Subject']
            ml['Subject'] = jret['subject']
        ml['X-Spam-Action'] = jret['action']
        if jret['action'] == 'add header':
            ml['X-Spam'] = 'yes'
        if jret['action'] == 'reject':
            session.reject_reason = '550 message rejected'
        if jret['action'] == 'greylist':
            session.reject_reason = '421 greylisted'
        if jret['action'] == 'soft reject':
            session.reject_reason = '451 try again later'
        ml['X-Spam-Sore'] = '%s / %s' % (jret['score'], jret['required_score'])
        ml['X-Spam-Symbols'] = ', '.join(jret['symbols'])
        if 'dkim-signature' in jret:
            ml['dkim-signature'] = jret['dkim-signature']

    for line in str(ml).split('\n'):
        dataline(token, session.session_id, line)
    dataline(token, session.session_id, ".")
