"""Small persistent review queue. Submissions are private to the host operator."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import sqlite3
import time
from urllib.parse import urlsplit

STATUSES = ('pending', 'in-review', 'accepted', 'declined', 'implemented')


class ValidationError(ValueError):
    def __init__(self, errors):
        self.errors = errors


def valid_url(value):
    try:
        url = urlsplit(value)
        return url.scheme in ('https','http') and bool(url.hostname) and not url.username and not url.password and not any(c.isspace() for c in value)
    except ValueError:
        return False


def validate(payload):
    if not isinstance(payload, dict):
        raise ValidationError({'form':'Send an object containing the suggestion fields.'})
    errors, data = {}, {}
    bounds = {'name':(2,120), 'author':(2,120), 'source_url':(8,500), 'description':(40,4000),
              'instructions':(40,8000), 'author_url':(0,500), 'license':(0,120), 'submitter':(0,120)}
    for field,(lo,hi) in bounds.items():
        value = payload.get(field,'')
        value = value.strip() if isinstance(value,str) else ''
        data[field] = value
        if not lo <= len(value) <= hi or '\x00' in value:
            errors[field] = f'Use {lo}–{hi} characters.' if lo else f'Use at most {hi} characters.'
    data['kind'] = payload.get('kind')
    if data['kind'] not in ('model','game'):
        errors['kind'] = 'Choose a model or a game.'
    for field in ('source_url','author_url'):
        if data[field] and not valid_url(data[field]):
            errors[field] = 'Use a full http:// or https:// URL, without login credentials.'
    data['delivery_mode'] = payload.get('delivery_mode','') if data['kind']=='game' else ''
    if data['kind']=='game' and data['delivery_mode'] not in ('console','ui-and-console'):
        errors['delivery_mode'] = 'Choose console benchmarks or UI + console benchmarks.'
    if payload.get('company'):
        errors['form'] = 'This suggestion could not be accepted.'
    if errors:
        raise ValidationError(errors)
    return data


class SubmissionStore:
    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory/'submissions.sqlite3'
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS submissions (
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, status TEXT NOT NULL,
                    kind TEXT NOT NULL, name TEXT NOT NULL, payload TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, created_epoch INTEGER NOT NULL,
                    digest TEXT NOT NULL, note TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS submissions_rate ON submissions(fingerprint, created_epoch);
                CREATE INDEX IF NOT EXISTS submissions_digest ON submissions(digest, created_epoch);
            ''')
            db.execute('INSERT OR IGNORE INTO settings VALUES (?,?)', ('secret',secrets.token_hex(32)))
            self.secret = db.execute('SELECT value FROM settings WHERE key=?',('secret',)).fetchone()[0]

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def save(self, payload, client_ip, limit):
        now = int(time.time())
        encoded = json.dumps(payload,sort_keys=True,ensure_ascii=False)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        fingerprint = hmac.new(self.secret.encode(), (client_ip or 'unknown').encode(), hashlib.sha256).hexdigest()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            same = db.execute('SELECT id FROM submissions WHERE digest=? AND fingerprint=? AND created_epoch>?',
                              (digest,fingerprint,now-86400)).fetchone()
            if same:
                return same['id'], False
            recent = db.execute('SELECT COUNT(*) FROM submissions WHERE fingerprint=? AND created_epoch>?',
                                (fingerprint,now-3600)).fetchone()[0]
            if recent >= limit:
                return None, False
            ref = 'ARC-'+secrets.token_hex(5).upper()
            db.execute('INSERT INTO submissions (id,created_at,status,kind,name,payload,fingerprint,created_epoch,digest) VALUES (?,?,?,?,?,?,?,?,?)',
                       (ref,datetime.now(timezone.utc).isoformat(), 'pending',payload['kind'],payload['name'],encoded,fingerprint,now,digest))
            return ref, True

    def all(self, status=None):
        with self.connect() as db:
            rows = db.execute('SELECT id,created_at,status,kind,name,payload,note FROM submissions'+
                              (' WHERE status=?' if status else '')+' ORDER BY created_epoch DESC', (status,) if status else ()).fetchall()
            return [dict(row)|{'payload':json.loads(row['payload'])} for row in rows]

    def update(self, reference, status, note=''):
        if status not in STATUSES:
            raise ValueError('Unknown review status')
        with self.connect() as db:
            return bool(db.execute('UPDATE submissions SET status=?,note=? WHERE id=?',(status,note,reference)).rowcount)
