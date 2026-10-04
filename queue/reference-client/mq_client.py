#!/usr/bin/env python3
"""
Medic queue reference client (stdlib only).
Implements canonical-json/v1, send/poll/ack/ack_read, bounded retries,
cursor persistence, and receiver-side dedup on (sender, idempotency_key).

Usage:
  mq_client.py send --to rivet --type note --payload '{"a":1}' --key my-key-1
  mq_client.py poll [--wait 20] [--limit 50]
  mq_client.py ack --id <message-id> --stage received
  mq_client.py ack_read --id <message-id>

Config via env: MQ_URL, MQ_TOKEN, MQ_CURSOR_FILE, MQ_SEEN_FILE.
"""
import json, os, sys, time, random, hashlib, urllib.request, urllib.error

MQ_URL = os.environ.get('MQ_URL', 'https://madmorrigan.com/prymortal-api/api.php?action=mq')
MQ_TOKEN = os.environ.get('MQ_TOKEN', '')
CURSOR_FILE = os.environ.get('MQ_CURSOR_FILE', os.path.expanduser('~/.mq-cursor'))
SEEN_FILE = os.environ.get('MQ_SEEN_FILE', os.path.expanduser('~/.mq-seen'))
IDENTITY = os.environ.get('MQ_IDENTITY', 'medic')

INT_MIN, INT_MAX = -9007199254740991, 9007199254740991

# ---------- canonical-json/v1 ----------
def canon(v):
    if v is None: return b'null'
    if isinstance(v, bool): return b'true' if v else b'false'
    if isinstance(v, int):
        if not (INT_MIN <= v <= INT_MAX): raise ValueError(f'int out of range: {v}')
        return str(v).encode()
    if isinstance(v, float): raise ValueError(f'floats rejected in v1: {v!r}')
    if isinstance(v, str):
        v.encode('utf-8')
        out = ['"']
        for ch in v:
            o = ord(ch)
            if o > 0x10FFFF or 0xD800 <= o <= 0xDFFF:
                raise ValueError(f'bad code point U+{o:04X}')
            if ch == '"': out.append('\\"')
            elif ch == '\\': out.append('\\\\')
            elif o < 0x20: out.append('\\u%04x' % o)
            else: out.append(ch)
        out.append('"')
        return ''.join(out).encode('utf-8')
    if isinstance(v, list):
        return b'[' + b','.join(canon(x) for x in v) + b']'
    if isinstance(v, dict):
        items = sorted(v.items(), key=lambda kv: kv[0].encode('utf-8'))
        return b'{' + b','.join(canon(k) + b':' + canon(val) for k, val in items) + b'}'
    raise ValueError(f'bad type: {type(v)}')

def sha256_canon(payload):
    return hashlib.sha256(canon(payload)).hexdigest()

# ---------- transport with bounded retries ----------
# 1 initial attempt + up to 5 retries. Backoff 1s,2s,4s,8s,16s ±25% jitter.
# 30s per-attempt timeout. 5-minute total deadline. Then report blocked.
def api(op_body, timeout=30):
    body = json.dumps(op_body).encode()
    headers = {'Content-Type': 'application/json',
               'User-Agent': 'medic-queue-client/1.0',
               'Authorization': 'Bearer ' + MQ_TOKEN}
    req = urllib.request.Request(MQ_URL, data=body, headers=headers, method='POST')
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors='replace')
        try: return e.code, json.loads(raw)
        except Exception: return e.code, {'ok': False, 'code': 'http_error', '_raw': raw[:200]}

def call(op_body):
    deadline = time.time() + 300
    delay = 1.0
    for attempt in range(6):  # 1 initial + 5 retries
        try:
            st, r = api(op_body)
        except Exception as e:
            st, r = None, {'ok': False, 'code': 'transport_error', 'error': str(e)[:200]}
        # retry on transport errors and 5xx; not on 4xx (client error, retrying won't help)
        if r.get('ok') or (st is not None and 400 <= st < 500):
            return st, r
        if attempt == 5 or time.time() + delay > deadline:
            break
        time.sleep(delay * random.uniform(0.75, 1.25))
        delay *= 2
    r['_blocked'] = True
    return st, r

# ---------- cursor + seen-set ----------
def load_cursor():
    try: return int(open(CURSOR_FILE).read().strip())
    except Exception: return 0

def save_cursor(seq):
    # persist only after durable admission (caller writes state first)
    open(CURSOR_FILE, 'w').write(str(seq))

def load_seen():
    try: return set(open(SEEN_FILE).read().split())
    except Exception: return set()

def save_seen(seen):
    open(SEEN_FILE, 'w').write('\n'.join(sorted(seen)))

# ---------- ops ----------
def op_send(to, ptype, payload, key, ttl=604800):
    h = sha256_canon(payload)
    return call({'op': 'send', 'recipient': to, 'type': ptype, 'payload': payload,
                 'sha256': h, 'idempotency_key': key, 'ttl_seconds': ttl})

def op_poll(since_seq=None, limit=50, include_dead=False, wait=0):
    return call({'op': 'poll',
                 'since_seq': load_cursor() if since_seq is None else since_seq,
                 'limit': limit, 'include_dead': include_dead, 'wait_seconds': wait})

def op_ack(mid, stage, note=None):
    body = {'op': 'ack', 'message_id': mid, 'stage': stage}
    if note: body['note'] = note
    return call(body)

def op_ack_read(mid):
    return call({'op': 'ack_read', 'message_id': mid})

def verify(msg):
    """Re-canonicalize the polled payload and check the server's hash."""
    return sha256_canon(msg['payload']) == msg['sha256']

def main(argv):
    if not MQ_TOKEN:
        print('MQ_TOKEN not set', file=sys.stderr); return 2
    cmd = argv[1] if len(argv) > 1 else ''
    args = dict(zip(argv[2::2], argv[3::2])) if len(argv) > 2 else {}
    # (simple --flag value parsing; flags look like --to X)
    kv = {}
    i = 2
    while i < len(argv):
        if argv[i].startswith('--') and i + 1 < len(argv):
            kv[argv[i][2:]] = argv[i + 1]; i += 2
        else: i += 1

    if cmd == 'send':
        payload = json.loads(kv.get('payload', '{}'))
        st, r = op_send(kv['to'], kv.get('type', 'note'), payload,
                       kv.get('key', hashlib.sha256(str(time.time()).encode()).hexdigest()[:16]),
                       int(kv.get('ttl', '604800')))
        print(json.dumps({'http': st, **r}, indent=1))
    elif cmd == 'poll':
        st, r = op_poll(limit=int(kv.get('limit', '50')),
                        wait=int(kv.get('wait', '0')),
                        include_dead=kv.get('include_dead') == '1')
        if r.get('ok'):
            seen = load_seen()
            fresh = []
            for m in r['messages']:
                # receiver-side dedup on (sender, idempotency_key) — survives
                # the server's 30-day pruning horizon; transport UUID is not
                # an execution identity.
                dkey = m['sender'] + ':' + m['idempotency_key']
                if dkey in seen:
                    continue
                if not verify(m):
                    print(f"hash mismatch on {m['id']}, skipping", file=sys.stderr)
                    continue
                fresh.append(m)
                seen.add(dkey)
            save_seen(seen)
            if r['messages']:
                # persist cursor only after durable admission (above)
                save_cursor(r['next_seq'])
            print(json.dumps({'http': st, 'fresh': len(fresh),
                              'next_seq': r['next_seq'],
                              'truncated': r.get('truncated'),
                              'messages': fresh}, indent=1, ensure_ascii=False))
        else:
            print(json.dumps({'http': st, **r}, indent=1))
    elif cmd == 'ack':
        st, r = op_ack(kv['id'], kv['stage'], kv.get('note'))
        print(json.dumps({'http': st, **r}, indent=1))
    elif cmd == 'ack_read':
        st, r = op_ack_read(kv['id'])
        print(json.dumps({'http': st, **r}, indent=1))
    else:
        print(__doc__); return 2
    return 0

if __name__ == '__main__':
    sys.exit(main(sys.argv))
