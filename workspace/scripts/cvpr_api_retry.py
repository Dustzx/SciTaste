"""Bounded paid-request retry with durable per-attempt reservations and receipts.

Use only under explicit retry authorization. Successful/truncated outputs are
never regenerated. Failed attempts retain their full pessimistic reservation.
"""
import email.utils
import json
import os
import re
import threading
import time
from datetime import datetime, timezone

import requests

from cvpr_chart_api import ENDPOINT, now
from cvpr_chart_run import parse_json


def error_metadata(exc, secret=''):
    response = getattr(exc, 'response', None)
    status = response.status_code if response is not None else None
    info = {'exception_type': type(exc).__name__, 'http_status': status}
    if response is not None:
        try:
            payload = response.json()
            error = payload.get('error', payload) if isinstance(payload, dict) else {}
            code = str(error.get('code', ''))
            if re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,79}', code):
                info['provider_error_code'] = code.replace(secret, '[redacted]') if secret else code
            message = str(error.get('message', ''))
            if secret:
                message = message.replace(secret, '[redacted]')
            message = re.sub(r'(?i)Bearer\s+\S+|sk-[A-Za-z0-9_-]+|data:image/[^\s]+', '[redacted]', message)
            info['provider_message_sanitized'] = message[:512]
        except (ValueError, TypeError, AttributeError):
            pass
        info['retry_after'] = response.headers.get('Retry-After', '')[:100]
    return info


def retryable(exc):
    if isinstance(exc, requests.HTTPError):
        response = exc.response
        if response is None:
            return False
        if response.status_code in {408, 429} or 500 <= response.status_code < 600:
            return True
        if response.status_code == 400:
            # DashScope can label a server-side JSON-generation abort as a
            # parameter error while explicitly asking to retry the request.
            # Recognize this exact failure; ordinary invalid inputs stay held.
            info = error_metadata(exc)
            message = info.get('provider_message_sanitized', '').lower()
            return (info.get('provider_error_code') == 'invalid_parameter_error'
                    and 'model output became abnormal while generating a json response' in message
                    and 'generation was aborted' in message)
        return False
    return isinstance(exc, (requests.Timeout, requests.ConnectionError))


def retry_delay(index, value='', wall_time=None):
    delay = 30 * (3 ** (index - 1))
    if value:
        try:
            server = float(value)
        except ValueError:
            try:
                stamp = email.utils.parsedate_to_datetime(value)
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=timezone.utc)
                server = stamp.timestamp() - (wall_time if wall_time is not None else datetime.now(timezone.utc).timestamp())
            except (ValueError, TypeError, OverflowError):
                server = 0
        delay = max(delay, server)
    return max(0, delay)


class PaidRequester:
    def __init__(self, *, budget, run, run_id, secret, halt, prior_attempts=None,
                 post=requests.post, monotonic=time.monotonic, sleeper=time.sleep,
                 prices=(.8, 2.7), phase_cap=20, wall_limit_seconds=1800,
                 allow_reasoning=False, cost_function=None, request_timeout=(15, 180)):
        self.budget, self.run, self.run_id, self.secret = budget, run, run_id, secret
        self.halt, self.prior_attempts = halt, prior_attempts or {}
        self.post, self.monotonic, self.sleep = post, monotonic, sleeper
        self.input_price, self.output_price = prices
        self.phase_cap = phase_cap
        self.allow_reasoning, self.cost_function = allow_reasoning, cost_function
        self.request_timeout = request_timeout
        if len(request_timeout) != 2 or any(not 0 < v <= 600 for v in request_timeout):
            raise ValueError('Invalid bounded HTTP timeout')
        if min(prices) <= 0 or not 0 < phase_cap <= 300 or wall_limit_seconds <= 0:
            raise ValueError('Invalid bounded request resource contract')
        self.rate, self.log_lock = threading.Lock(), threading.Lock()
        self.next_allowed = 0
        self.deadline = monotonic() + wall_limit_seconds

    def event(self, item):
        with self.log_lock, (self.run/'ATTEMPTS.jsonl').open('a') as handle:
            handle.write(json.dumps(item, ensure_ascii=False) + '\n')
            handle.flush()
            os.fsync(handle.fileno())

    def call(self, *, key, cap, body, digest, save):
        prior = self.prior_attempts.get(key, 0)
        for attempt in range(prior + 1, 4):
            ledger_key = self.run_id + '|' + key + '|attempt-' + str(attempt)
            with self.rate:
                self.sleep(max(0, self.next_allowed - self.monotonic()))
                if self.halt.is_set() or self.monotonic() >= self.deadline:
                    raise RuntimeError('Retry window ended or sibling stopped')
                self.budget.change(ledger_key, record={'run_id': self.run_id, 'key': key, 'logical_key': key,
                    'attempt_index': attempt, 'pid': os.getpid(), 'model': body['model'],
                    'reserved_cny': self.input_price + cap*self.output_price/1e6,
                    'status': 'pending', 'started_at': now()},
                    phase_cap=self.phase_cap, run_id=self.run_id)
                self.next_allowed = self.monotonic() + 2.5
            tick = self.monotonic()
            settled = False
            try:
                response = self.post(ENDPOINT, headers={'Authorization': 'Bearer ' + self.secret},
                                     json=body, timeout=self.request_timeout)
                response.raise_for_status()
                obj = response.json()
                usage, choice = obj['usage'], obj['choices'][0]
                inp, out = int(usage['prompt_tokens']), int(usage['completion_tokens'])
                assert 0 <= inp <= 1000000 and 0 <= out <= cap
                content = choice['message']['content']
                reasoning = choice['message'].get('reasoning_content')
                assert isinstance(content, str) and (self.allow_reasoning or not reasoning)
                cost = (self.cost_function(inp, out) if self.cost_function else
                        (inp*self.input_price + out*self.output_price)/1e6)
                assert 0 <= cost <= self.input_price + cap*self.output_price/1e6
                sample, stage = key.split('|')
                item = {'key': key, 'sample_id': sample, 'stage': stage, 'status': 'ok', 'created_at': now(),
                    'prompt_sha256': digest, 'ledger_key': ledger_key, 'attempt_index': attempt,
                    'requested_model': body['model'], 'returned_model': obj.get('model'), 'response_id': obj['id'],
                    'usage': usage, 'input_tokens': inp, 'output_tokens': out, 'token_cap': cap, 'api_cost_cny': cost,
                    'elapsed_seconds': self.monotonic()-tick, 'finish_reason': choice.get('finish_reason'),
                    'truncated': choice.get('finish_reason') == 'length', 'text': content, 'parsed': parse_json(content)}
                if self.allow_reasoning:
                    item['reasoning_returned'] = bool(reasoning)
                    item['reasoning_characters'] = len(reasoning or '')
                save(item)  # Durable successful response before releasing its reservation.
                self.budget.change(ledger_key, settle={'status': 'settled', 'cost_cny': cost,
                    'settled_at': now(), 'response_id': obj['id'], 'usage': usage})
                settled = True
                self.event({'ledger_key': ledger_key, 'key': key, 'attempt_index': attempt,
                            'status': 'settled', 'created_at': now(), 'response_id': obj['id']})
                return item
            except Exception as exc:
                if settled:
                    self.halt.set()
                    raise RuntimeError('Receipt logging failed after settlement; do not regenerate output') from None
                info = error_metadata(exc, self.secret)
                delay = retry_delay(attempt, info.get('retry_after', ''))
                can_retry = retryable(exc) and attempt < 3 and self.monotonic() + delay < self.deadline
                event = {'status': 'unknown', 'failed_at': now(), **info, 'automatic_retry_eligible': can_retry,
                         'retry_delay_seconds': delay if can_retry else None}
                self.budget.change(ledger_key, settle=event)
                self.event({'ledger_key': ledger_key, 'key': key, 'attempt_index': attempt, **event})
                if not can_retry:
                    self.halt.set()
                    raise RuntimeError('Paid request stopped after bounded handling; see structured attempt receipt') from None
                with self.rate:
                    self.next_allowed = max(self.next_allowed, self.monotonic() + delay)
                print(json.dumps({'key': key, 'attempt': attempt, 'http_status': info.get('http_status'),
                                  'automatic_retry_in_seconds': delay}), flush=True)
        raise RuntimeError('Attempt limit exhausted')
