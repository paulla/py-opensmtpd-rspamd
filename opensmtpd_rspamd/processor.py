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

        self.stream.on_report('link-connect', link_connect)
        self.stream.on_report('link-disconnect', link_disconnect)
        self.stream.on_report('link-identify', link_identify)

        self.stream.on_report('tx-begin', tx_begin)
        self.stream.on_report('tx-mail', tx_mail)
        self.stream.on_report('tx-rcpt', tx_rcpt)
        self.stream.on_report('tx-commit', tx_cleanup)
        self.stream.on_report('tx-rollback', tx_cleanup)

        self.stream.on_filter('data', filter_data)
        self.stream.on_filter('commit', filter_commit)

        self.stream.on_filter('data-line', filter_data_line)
        
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
            return False
        else:
            self.message = email.message_from_string('\n'.join(self.payload))
            return True


def link_connect(timestamp, session_id, args):
    rdns, _, laddr, _ = args

    session = sessions[session_id] = Session(session_id)
    session.control['Pass'] = 'all'
    src, port = laddr.split(':')
    if src != 'local':
        session.control['Ip'] = src
    if rdns:
        session.control['Hostname'] = rdns


def link_disconnect(timestamp, session_id, args):
    sessions.pop(session_id)


def link_identify(timestamp, session_id, args):
    helo = args[0]

    session = sessions[session_id]
    session.control['Helo'] = helo


def tx_begin(timestamp, session_id, args):
    tx_id = args[0]

    session = sessions[session_id]
    session.control['Queue-Id'] = tx_id


def tx_mail(timestamp, session_id, args):
    _, mail_from, status = args
    if status == 'ok':
        session = sessions[session_id]
        session.control['From'] = mail_from

def tx_rcpt(timestamp, session_id, args):
    _, rcpt_to, status = args
    if status == 'ok':
        session = sessions[session_id]
        session.control['Rcpt'] = rcpt_to


def tx_cleanup(timestamp, session_id, args):
    session = sessions[session_id]
    session.control = {}


def filter_data(timestamp, session_id, args):
    # this should probably be a tx event
    session = sessions[session_id]
    session.payload = []
    proceed(session_id)


def filter_commit(timestamp, session_id, args):
    session = sessions[session_id]
    if session.reject_reason:
        reject(session_id, session.reject_reason)
    else:
        proceed(session_id)


def filter_data_line(timestamp, session_id, args):
    line = args[0]

    session = sessions[session_id]
    if session.push(line):
        return

    try:
        res = requests.post('http://localhost:11333/checkv2',
                            headers=session.control,
                            data=str(self.message))
        jret = res.json()
    except:
        jret = {}

    data_output(session, jret)


def data_output(session, jret):
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

    for line in str(ml).split('\n'):
        dataline(session.session_id, line)
    dataline(session.session_id, ".")
