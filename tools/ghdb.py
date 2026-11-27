#!/usr/bin/env python3
"""Journal access for CLOUD scheduled tasks. Same commands as jdb.py, but docs live in this git repo.
The repo is the transit inbox: a Windows job on Sarantis's PC pulls it every 5 minutes into his database.
  python3 ghdb.py put <collection> <doc_id> < doc.json      write + commit + push (retries on conflicts)
  python3 ghdb.py putdir <collection> <dir>                 every <id>.json in <dir>, ONE commit
  python3 ghdb.py get <collection> <doc_id>                 print a doc ('null' if none)
  python3 ghdb.py list <collection> [--prefix P] [--ids] [--where k=v] [--since k=v]
  python3 ghdb.py runlog start|end <pass_doc_id> ...        same as jdb.py runlog
Reads see (1) this repo's <collection>/<id>.json, newest first, else (2) _seed/<collection>/<id>.json, the baseline
snapshot of watch, setup, conids and tradable as of 2026-11-27. Scans of the last 7 trading days, ext, notes, market and filings are seeded too. Minute docs are not here, but `list minutes --ids` also lists the ids already in his database.
Env: GHDB_REPO (default /tmp/inbox). The repo is cloned on first use (shallow)."""
import os, sys, json, re, time, random, subprocess

REPO = os.environ.get('GHDB_REPO', '/tmp/inbox')
URL = 'https://github.com/breadgoat1984/trading-journal-inbox'
OK_COL = re.compile(r'^[a-z][a-z0-9_]{0,40}$'); OK_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.+\-]{0,120}$')
J = lambda x: json.dumps(x, separators=(',', ':'), ensure_ascii=False)
GIT = ['git', '-C', REPO, '-c', 'user.name=Claude', '-c', 'user.email=noreply@anthropic.com']


def sh(args, check=False):
    r = subprocess.run(args, capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit('command failed: %s\n%s' % (' '.join(args[:6]), (r.stderr or r.stdout)[:400]))
    return r


def ensure():
    if not os.path.isdir(os.path.join(REPO, '.git')):
        sh(['git', 'clone', '--depth', '1', URL, REPO], check=True)
    else:
        sh(GIT + ['pull', '--rebase', '--autostash', '-q'])


def check(col, i=None):
    if not OK_COL.match(col): raise SystemExit('bad collection name')
    if i is not None and not OK_ID.match(i): raise SystemExit('bad doc id')


def publish(msg):
    """commit what is staged and push; on a rejected push pull --rebase and retry."""
    if sh(GIT + ['diff', '--cached', '--quiet']).returncode == 0:
        return 'nothing to commit'
    sh(GIT + ['commit', '-q', '-m', msg], check=True)
    last = ''
    for k in range(8):
        r = sh(GIT + ['push', '-q', 'origin', 'HEAD:main'])
        if r.returncode == 0:
            return 'pushed'
        last = (r.stderr or r.stdout)[:300]
        time.sleep(1 + random.random() * 2 + k)
        sh(GIT + ['pull', '--rebase', '--autostash', '-q'])
    raise SystemExit('push failed after retries: ' + last)


def write_doc(col, i, d):
    dd = os.path.join(REPO, col); os.makedirs(dd, exist_ok=True)
    p = os.path.join(dd, i + '.json'); new = J(d)
    if os.path.exists(p) and open(p, encoding='utf-8').read() == new:
        return False
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f: f.write(new)
    os.replace(tmp, p)
    if J(json.load(open(p, encoding='utf-8'))) != new: raise SystemExit('write verification failed')
    sh(GIT + ['add', os.path.join(col, i + '.json')], check=True)
    return True


def put(col, i, raw=None):
    check(col, i); ensure()
    raw = raw if raw is not None else (sys.stdin.buffer.read().decode('utf-8'))
    d = json.loads(raw)
    if not isinstance(d, dict): raise SystemExit('doc must be a JSON object')
    ch = write_doc(col, i, d)
    print('unchanged' if not ch else 'ok %s/%s %s' % (col, i, publish('%s/%s' % (col, i))))


def putdir(col, d):
    check(col); ensure(); n = 0
    for f in sorted(os.listdir(d)):
        if f.endswith('.json') and not f.startswith('.'):
            i = f[:-5]; check(col, i)
            dd = json.load(open(os.path.join(d, f), encoding='utf-8'))
            if write_doc(col, i, dd): n += 1
    print('putdir %s: %d changed; %s' % (col, n, publish('%s: %d docs' % (col, n)) if n else 'nothing to push'))


def paths(col):
    out = {}
    for base in ('_seed/' + col, col):  # repo copy overrides the seed
        cd = os.path.join(REPO, base)
        if os.path.isdir(cd):
            for f in os.listdir(cd):
                if f.endswith('.json') and not f.startswith('.'): out[f[:-5]] = os.path.join(cd, f)
    return out


def keep_doc(d, wh, si):
    if not isinstance(d, dict): return False
    for k, v in wh:
        x = d.get(k)
        if str(x if not isinstance(x, bool) else str(x).lower()) != v: return False
    for k, v in si:
        x = d.get(k)
        if x is None or str(x) < v: return False
    return True


def get(col, i):
    check(col, i); ensure(); p = paths(col).get(i)
    print(open(p, encoding='utf-8').read() if p else 'null')


def lst(col, prefix, ids_only, wh, si):
    check(col); ensure(); ps = paths(col)
    if col == 'minutes' and ids_only and not (wh or si):  # ids of minute docs already in Sarantis's database (no content here)
        mi = os.path.join(REPO, '_seed', 'minutes_ids.txt')
        if os.path.exists(mi):
            for k in open(mi).read().split():
                ps.setdefault(k, None)
    for k in sorted(ps):
        if not k.startswith(prefix): continue
        d = json.load(open(ps[k], encoding='utf-8')) if (ps[k] and (wh or si or not ids_only)) else None
        if (wh or si) and not keep_doc(d, wh, si): continue
        print(k if ids_only else J({'id': k, 'doc': d}))


def runlog(a):
    import datetime
    mode, pid = a[0], a[1]; check('runs', pid); ensure()
    m = re.match(r'^(\d{4}-\d{2}-\d{2})-([a-z]+)-(\d{4})$', pid)
    now = datetime.datetime.now(datetime.timezone.utc); nows = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    p = os.path.join(REPO, 'runs', pid + '.json'); d = json.load(open(p, encoding='utf-8')) if os.path.exists(p) else {}
    d['id'] = pid
    if m:
        d['kind'] = m.group(2); d['scheduled_utc'] = '%sT%s:%s:00Z' % (m.group(1), m.group(3)[:2], m.group(3)[2:])
    if mode == 'start':
        d['started_utc'] = nows; d['status'] = 'running'
        if m:
            sch = datetime.datetime.strptime(d['scheduled_utc'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
            d['start_lag_s'] = int((now - sch).total_seconds())
    elif mode == 'end':
        d['ended_utc'] = nows; d['status'] = a[2] if len(a) > 2 else 'ok'
        if '--rows' in a: d['rows'] = int(a[a.index('--rows') + 1])
        if '--error' in a: d['error'] = a[a.index('--error') + 1][:500]
        if d.get('started_utc'):
            st = datetime.datetime.strptime(d['started_utc'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
            d['run_s'] = int((now - st).total_seconds())
    else: raise SystemExit('runlog start|end')
    write_doc('runs', pid, d)
    print('runlog %s %s %s' % (mode, pid, publish('runlog %s %s' % (mode, pid))))


if __name__ == '__main__':
    a = sys.argv[1:]
    if len(a) >= 3 and a[0] == 'put': put(a[1], a[2])
    elif len(a) >= 3 and a[0] == 'get': get(a[1], a[2])
    elif len(a) >= 2 and a[0] == 'list':
        pre = a[a.index('--prefix') + 1] if '--prefix' in a else ''
        wh = [tuple(a[j + 1].split('=', 1)) for j, x in enumerate(a) if x == '--where']
        si = [tuple(a[j + 1].split('=', 1)) for j, x in enumerate(a) if x == '--since']
        lst(a[1], pre, '--ids' in a, wh, si)
    elif len(a) >= 3 and a[0] == 'putdir': putdir(a[1], a[2])
    elif len(a) >= 3 and a[0] == 'runlog': runlog(a[1:])
    else: print(__doc__); sys.exit(2)
