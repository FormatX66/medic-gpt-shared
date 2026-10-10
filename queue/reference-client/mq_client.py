#!/usr/bin/env python3
"""
Medic queue reference client (stdlib only).
Implements canonical-json/v1, send/poll/ack/ack_read, bounded retries,
and durable receiver-side admission.

Durability model (SQLite, stdlib):
  One transaction admits a polled batch: valid payloads go to `inbox`,
  hash failures go to `quarantine` (with evidence), conflicting content
  under an existing (sender, key) goes to `quarantine` with both sides'
  identities (never silently dropped), and the cursor advances —
  atomically. Output happens after commit; `delivered` records what was
  emitted, so a crash between commit and output re-emits on restart instead
  of losing payloads. Dedup is on (sender, key) as separate columns —
  no string-concatenated keys. Exact duplicates (same id and sha256) are
  safe idempotent no-ops.

Usage:
  mq_client.py send --to rivet --type note --payload '{"a":1}' --key my-key-1
  mq_client.py poll [--wait 20] [--limit 50]
  mq_client.py ack --id <message-id> --stage received
  mq_client.py ack_read --id <message-id>

Config via env: MQ_URL, MQ_TOKEN, MQ_DB (default ~/.mq-client.db).
"""
import json, os, sys, time, random, hashlib, sqlite3
import urllib.request, urllib.error

MQ_URL = os.environ.get('MQ_URL', 'https://madmorrigan.com/prymortal-api/api.php?action=mq')
MQ_TOKEN = os.environ.get('MQ_TOKEN', '')
MQ_DB = os.environ.get('MQ_DB', os.path.expanduser('~/.mq-client.db'))
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
#
# Response bodies are NEVER read unbounded. read_bounded() streams the body
# in chunks and aborts the moment the running total exceeds RESPONSE_CAP
# (the documented 1,000,000-byte response cap). Content-Length is never
# trusted: the cap is enforced on actual bytes received, so a misleading
# or missing Content-Length header cannot bypass it.
RESPONSE_CAP = 1_000_000
_READ_CHUNK = 65536

class ResponseTooLarge(Exception):
    """Raised when a response body exceeds RESPONSE_CAP during streaming read."""

def read_bounded(resp, cap=RESPONSE_CAP):
    """Read a response body with the cap enforced DURING the stream.

    Accumulates in fixed-size chunks; raises ResponseTooLarge as soon as
    the running byte total exceeds cap — the oversized tail is never
    buffered and never parsed. Returns the full body bytes when within cap.
    """
    chunks = []
    total = 0
    while True:
        chunk = resp.read(_READ_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > cap:
            raise ResponseTooLarge(
                f"response body exceeded {cap} bytes (aborted mid-stream)")
        chunks.append(chunk)
    return b''.join(chunks)

def api(op_body, timeout=30):
    body = json.dumps(op_body).encode()
    headers = {'Content-Type': 'application/json',
               'User-Agent': 'medic-queue-client/1.0',
               'Authorization': 'Bearer ' + MQ_TOKEN}
    req = urllib.request.Request(MQ_URL, data=body, headers=headers, method='POST')
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        # Error bodies are bounded too — a hostile error page can't OOM us.
        try:
            raw = read_bounded(e)
        except ResponseTooLarge:
            return e.code, {'ok': False, 'code': 'response_too_large',
                            'error': f'error body exceeded {RESPONSE_CAP} bytes'}
        text = raw.decode('utf-8', errors='replace')
        try:
            return e.code, json.loads(text)
        except ValueError:
            return e.code, {'ok': False, 'code': 'http_error', '_raw': text[:200]}
    status = r.status
    try:
        raw = read_bounded(r)
    except ResponseTooLarge as e:
        return None, {'ok': False, 'code': 'response_too_large',
                      'error': str(e)[:200]}
    finally:
        r.close()
    try:
        return status, json.loads(raw)
    except ValueError as e:
        # Invalid JSON inside the cap: clean parse error, never a hang.
        return status, {'ok': False, 'code': 'invalid_response_json',
                        'error': str(e)[:200]}

def call(op_body):
    deadline = time.time() + 300
    delay = 1.0
    for attempt in range(6):  # 1 initial + 5 retries
        try:
            st, r = api(op_body)
        except Exception as e:
            st, r = None, {'ok': False, 'code': 'transport_error', 'error': str(e)[:200]}
        if r.get('ok') or (st is not None and 400 <= st < 500):
            return st, r
        if attempt == 5 or time.time() + delay > deadline:
            break
        time.sleep(delay * random.uniform(0.75, 1.25))
        delay *= 2
    r['_blocked'] = True
    return st, r

# ---------- durable local state ----------
def db():
    c = sqlite3.connect(MQ_DB)
    c.execute("""CREATE TABLE IF NOT EXISTS inbox(
        id TEXT PRIMARY KEY, seq INTEGER NOT NULL, sender TEXT NOT NULL,
        key TEXT NOT NULL, type TEXT NOT NULL, payload TEXT NOT NULL,
        sha256 TEXT NOT NULL, received_at INTEGER NOT NULL,
        UNIQUE(sender, key))""")
    c.execute("""CREATE TABLE IF NOT EXISTS quarantine(
        id TEXT PRIMARY KEY, seq INTEGER NOT NULL, sender TEXT NOT NULL,
        key TEXT NOT NULL, reason TEXT NOT NULL, detail TEXT,
        received_at INTEGER NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS delivered(
        id TEXT PRIMARY KEY, delivered_at INTEGER NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS meta(
        key TEXT PRIMARY KEY, value TEXT NOT NULL)""")
    c.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('cursor', '0')")
    c.commit()
    return c

def get_cursor(c):
    return int(c.execute("SELECT value FROM meta WHERE key='cursor'").fetchone()[0])

# ---------- ops ----------
def op_send(to, ptype, payload, key, ttl=604800):
    h = sha256_canon(payload)
    return call({'op': 'send', 'recipient': to, 'type': ptype, 'payload': payload,
                 'sha256': h, 'idempotency_key': key, 'ttl_seconds': ttl})

def op_poll_raw(since_seq, limit=50, include_dead=False, wait=0):
    return call({'op': 'poll', 'since_seq': since_seq,
                 'limit': limit, 'include_dead': include_dead, 'wait_seconds': wait})

def op_ack(mid, stage, note=None):
    body = {'op': 'ack', 'message_id': mid, 'stage': stage}
    if note: body['note'] = note
    return call(body)

def op_ack_read(mid):
    return call({'op': 'ack_read', 'message_id': mid})

def admit_batch(c, messages, next_seq):
    """Atomically admit a polled batch. Returns (admitted, quarantined).

    One transaction: valid payloads -> inbox, hash failures -> quarantine
    (with evidence), cursor advances. Either all of it commits or none does —
    there is no state where the cursor moved but the payloads didn't land.

    (sender, key) conflicts are never silently dropped. An exact duplicate
    (same id AND same sha256 as the existing row) is a safe idempotent
    redelivery and is ignored. Any other content under an existing
    (sender, key) is quarantined with evidence identifying both sides;
    the original row is preserved untouched.
    """
    now = int(time.time())
    admitted, quarantined = 0, 0
    with c:  # transaction
        for m in messages:
            mid, seq = m['id'], m['seq']
            sender, key = m['sender'], m['idempotency_key']
            try:
                expected = sha256_canon(m['payload'])
            except ValueError as e:
                expected = f'<uncanonicalizable: {e}>'
            if expected != m['sha256']:
                c.execute("""INSERT OR IGNORE INTO quarantine
                    (id, seq, sender, key, reason, detail, received_at)
                    VALUES (?,?,?,?,?,?,?)""",
                    (mid, seq, sender, key, 'hash_mismatch',
                     json.dumps({'server_sha256': m['sha256'],
                                 'local_sha256': expected},
                                sort_keys=True), now))
                quarantined += 1
                continue
            existing = c.execute(
                "SELECT id, sha256 FROM inbox WHERE sender=? AND key=?",
                (sender, key)).fetchone()
            if existing is not None:
                ex_id, ex_sha = existing
                if ex_id == mid and ex_sha == m['sha256']:
                    # Exact duplicate redelivery: idempotent, safe to ignore.
                    continue
                # Conflicting valid content under the same (sender, key).
                # Quarantine with evidence; the original row is preserved.
                detail = json.dumps({
                    'existing_id': ex_id,
                    'existing_sha256': ex_sha,
                    'incoming_id': mid,
                    'incoming_seq': seq,
                    'incoming_sha256': m['sha256'],
                }, sort_keys=True)
                cur = c.execute("""INSERT OR IGNORE INTO quarantine
                    (id, seq, sender, key, reason, detail, received_at)
                    VALUES (?,?,?,?,?,?,?)""",
                    (mid, seq, sender, key, 'content_conflict', detail, now))
                quarantined += cur.rowcount
                continue
            c.execute("""INSERT INTO inbox
                (id, seq, sender, key, type, payload, sha256, received_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                (mid, seq, sender, key, m['type'],
                 json.dumps(m['payload'], ensure_ascii=False),
                 m['sha256'], now))
            admitted += 1
        c.execute("UPDATE meta SET value=? WHERE key='cursor'", (str(next_seq),))
    return admitted, quarantined

def pending_output(c):
    """Messages admitted but not yet emitted. Survives crashes."""
    rows = c.execute("""SELECT i.id, i.seq, i.sender, i.key, i.type, i.payload, i.sha256
        FROM inbox i LEFT JOIN delivered d ON d.id = i.id
        WHERE d.id IS NULL ORDER BY i.seq ASC""").fetchall()
    return [{'id': r[0], 'seq': r[1], 'sender': r[2], 'idempotency_key': r[3],
             'type': r[4], 'payload': json.loads(r[5]), 'sha256': r[6]} for r in rows]

def mark_delivered(c, ids):
    now = int(time.time())
    with c:
        c.executemany("INSERT OR IGNORE INTO delivered(id, delivered_at) VALUES (?,?)",
                      [(i, now) for i in ids])

def main(argv):
    if not MQ_TOKEN:
        print('MQ_TOKEN not set', file=sys.stderr); return 2
    kv = {}
    i = 2
    while i < len(argv):
        if argv[i].startswith('--') and i + 1 < len(argv):
            kv[argv[i][2:]] = argv[i + 1]; i += 2
        else: i += 1
    cmd = argv[1] if len(argv) > 1 else ''

    if cmd == 'send':
        payload = json.loads(kv.get('payload', '{}'))
        st, r = op_send(kv['to'], kv.get('type', 'note'), payload,
                       kv.get('key', hashlib.sha256(str(time.time()).encode()).hexdigest()[:16]),
                       int(kv.get('ttl', '604800')))
        print(json.dumps({'http': st, **r}, indent=1))
    elif cmd == 'poll':
        c = db()
        st, r = op_poll_raw(get_cursor(c), limit=int(kv.get('limit', '50')),
                            wait=int(kv.get('wait', '0')),
                            include_dead=kv.get('include_dead') == '1')
        if not r.get('ok'):
            print(json.dumps({'http': st, **r}, indent=1)); return 1
        admitted, quarantined = admit_batch(c, r['messages'], r['next_seq'])
        out = pending_output(c)
        print(json.dumps({'http': st, 'admitted': admitted,
                          'quarantined': quarantined,
                          'next_seq': r['next_seq'],
                          'truncated': r.get('truncated'),
                          'messages': out}, indent=1, ensure_ascii=False))
        if out:
            mark_delivered(c, [m['id'] for m in out])
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
