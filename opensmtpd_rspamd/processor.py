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
import sys

import requests

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

sessions = {}
payloads = {}
failures = {}

def link_connect(timestamp, session_id, args):
    rdns, _, laddr, _ = args
    sessions[session_id] = {}

    src, port = laddr.split(':')
    if src != 'local':
        sessions[session_id]['Ip'] = src
    if rdns:
        sessions[session_id]['Hostname'] = rdns
    sessions[session_id]['Pass'] = 'all'

def link_disconnect(timestamp, session_id, args):
    if session_id in failures:
        failures.pop(session_id)
    if session_id in payloads:
        payloads.pop(session_id)
    sessions.pop(session_id)

def link_identify(timestamp, session_id, args):
    helo = args[0]
    sessions[session_id]['Helo'] = args[0]

def tx_begin(timestamp, session_id, args):
    tx_id = args[0]
    sessions[session_id]['Queue-Id'] = tx_id

def tx_mail(timestamp, session_id, args):
    _, mail_from, status = args
    if status == 'ok':
        sessions[session_id]['From'] = mail_from

def tx_rcpt(timestamp, session_id, args):
    _, rcpt_to, status = args
    if status == 'ok':
        sessions[session_id]['Rcpt'] = rcpt_to

def tx_cleanup(timestamp, session_id, args):
    sessions[session_id] = {}

def filter_data(timestamp, session_id, args):
    payloads[session_id] = []
    proceed(session_id)

def filter_commit(timestamp, session_id, args):
    if session_id in failures:
        action = failures.pop(session_id)
        if action == 'reject':
            reject(session_id, '550 message rejected')
        if action == 'soft reject':
            reject(session_id, '451 try again later')
        if action == 'greylist':
            reject(session_id, '421 greylisted')
    else:
        proceed(session_id)

def filter_data_line(timestamp, session_id, args):
    line = args[0]
    if line != '.':
        payloads[session_id].append(line)
        return

    ml = email.message_from_string('\n'.join(payloads[session_id]))
    try:
        ret = requests.post('http://localhost:11333/checkv2',
                            headers=sessions[session_id],
                            data=str(ml))
    except:
        ret = {}

    if ret:
        data_output(session_id, ml, ret.json())
    else:
        for line in str(ml).split('\n'):
            dataline(session_id, line)
        dataline(session_id, ".")

def data_output(session_id, ml, jret):
    if jret['action'] == 'rewrite subject':
        del ml['Subject']
        ml['Subject'] = jret['subject']
    ml['X-Spam-Action'] = jret['action']
    if jret['action'] == 'add header':
        ml['X-Spam'] = 'yes'
    if jret['action'] in ('reject', 'greylist', 'soft reject'):
        failures[session_id] = jret['action']
    ml['X-Spam-Sore'] = "%s / %s" % (jret['score'], jret['required_score'])
    ml['X-Spam-Symbols'] = ', '.join(jret['symbols'])

    for line in str(ml).split('\n'):
        dataline(session_id, line)
    dataline(session_id, ".")
