"""SQLite WAL/full-sync session journal; disk originals are committed before jobs."""
import json
import sqlite3
import threading
from pathlib import Path


class Repository:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.lock = threading.RLock()
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, body TEXT NOT NULL)')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.execute('PRAGMA synchronous=FULL')
        return db

    def save(self, item):
        with self.lock, self.connect() as db:
            db.execute('INSERT INTO sessions VALUES (?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body',
                       (item['id'], json.dumps(item, ensure_ascii=False, allow_nan=False)))

    def load(self, sid):
        with self.lock, self.connect() as db:
            row = db.execute('SELECT body FROM sessions WHERE id=?', (sid,)).fetchone()
        if row is None:
            raise FileNotFoundError('Session not found')
        return json.loads(row[0])

    def listing(self):
        with self.lock, self.connect() as db:
            rows = db.execute('SELECT body FROM sessions').fetchall()
        return sorted((json.loads(row[0]) for row in rows), key=lambda x:x['created_at'], reverse=True)
