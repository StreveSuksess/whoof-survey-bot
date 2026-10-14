"""Private local persistence; contact details never enter response exports."""
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self,directory):
        self.directory=Path(directory); self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        os.chmod(self.directory,0o700)
        self.db=sqlite3.connect(self.directory/'responses.sqlite')
        self.contacts=sqlite3.connect(self.directory/'contacts.sqlite')
        self.active_update=None
        self.db.execute('CREATE TABLE IF NOT EXISTS sessions(chat_id INTEGER PRIMARY KEY, state TEXT NOT NULL, updated REAL NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS survey_reminders(chat_id INTEGER PRIMARY KEY, participant TEXT NOT NULL, activity REAL NOT NULL, attempted_at REAL, opted_out INTEGER NOT NULL DEFAULT 0)')
        self.contacts.execute('CREATE TABLE IF NOT EXISTS contacts(participant TEXT PRIMARY KEY, contact TEXT NOT NULL, consent TEXT NOT NULL, created REAL NOT NULL)')
        for p in self.directory.glob('*.sqlite'): os.chmod(p,0o600)

    def load(self,chat_id):
        row=self.db.execute('SELECT state FROM sessions WHERE chat_id=?',(chat_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def seed_reminders(self,version):
        """Existing unfinished sessions keep their last saved activity on upgrade."""
        with self.db:
            for chat,raw,updated in self.db.execute('SELECT chat_id,state,updated FROM sessions').fetchall():
                s=json.loads(raw)
                if s.get('version')==version and s.get('mode')=='core' and s.get('started') and not s.get('complete') and not s.get('screened_out'):
                    self.db.execute('INSERT OR IGNORE INTO survey_reminders(chat_id,participant,activity) VALUES (?,?,?)',(chat,s['participant'],updated))

    def reminder_activity(self,chat,participant,now=None):
        # Incoming activity is independent of cursor/answer commits. Never checkpoint here.
        now=time.time() if now is None else now
        with self.db:
            self.db.execute('''INSERT INTO survey_reminders(chat_id,participant,activity) VALUES (?,?,?)
                ON CONFLICT(chat_id) DO UPDATE SET participant=excluded.participant, activity=excluded.activity,
                attempted_at=CASE WHEN participant=excluded.participant THEN attempted_at ELSE NULL END,
                opted_out=CASE WHEN participant=excluded.participant THEN opted_out ELSE 0 END''',(chat,participant,now))

    def reminder_candidates(self,now,delay=86400):
        rows=self.db.execute('''SELECT s.chat_id,s.state FROM sessions s JOIN survey_reminders r ON s.chat_id=r.chat_id
            WHERE r.attempted_at IS NULL AND r.opted_out=0 AND r.activity<=? ORDER BY r.activity''',(now-delay,)).fetchall()
        return [(chat,json.loads(raw)) for chat,raw in rows]

    def claim_reminder(self,chat,participant,now,delay=86400):
        # Claim before network I/O: uncertain delivery must never cause a second ping.
        with self.db:
            return self.db.execute('''UPDATE survey_reminders SET attempted_at=? WHERE chat_id=? AND participant=?
                AND attempted_at IS NULL AND opted_out=0 AND activity<=?''',(now,chat,participant,now-delay)).rowcount==1

    def stop_reminders(self,chat,participant):
        with self.db:
            self.db.execute('''INSERT INTO survey_reminders(chat_id,participant,activity,opted_out) VALUES (?,?,?,1)
                ON CONFLICT(chat_id) DO UPDATE SET opted_out=1 WHERE participant=excluded.participant''',(chat,participant,time.time()))

    def save(self,chat_id,state):
        # Q33 only exists in the separate contact database.
        if 'Q33' in state.get('answers',{}): raise ValueError('Contact must not be stored with answers')
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO sessions VALUES (?,?,?)',(chat_id,json.dumps(state,ensure_ascii=False),time.time()))
            self.checkpoint_update()

    @contextmanager
    def update(self,update_id):
        """Attach the Telegram cursor to the same commit as each state mutation."""
        self.active_update=update_id
        try: yield
        finally: self.active_update=None

    def checkpoint_update(self):
        if self.active_update is not None:
            self.db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)',('offset',str(self.active_update+1)))

    def save_contact(self,participant,contact):
        with self.contacts:
            self.contacts.execute('INSERT OR REPLACE INTO contacts VALUES (?,?,?,?)',(participant,contact,'Q32:c1',time.time()))

    def remove_contact(self,participant):
        with self.contacts: self.contacts.execute('DELETE FROM contacts WHERE participant=?',(participant,))

    def delete(self,chat_id):
        state=self.load(chat_id)
        if state: self.remove_contact(state['participant'])
        with self.db:
            self.db.execute('DELETE FROM sessions WHERE chat_id=?',(chat_id,))
            self.db.execute('DELETE FROM survey_reminders WHERE chat_id=?',(chat_id,))
            self.checkpoint_update()

    def offset(self,value=None):
        if value is not None:
            with self.db: self.db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)',('offset',str(value)))
        row=self.db.execute('SELECT value FROM meta WHERE key=?',('offset',)).fetchone()
        return int(row[0]) if row else 0

    def purge_expired(self,days=365):
        cutoff=time.time()-days*86400
        for (chat_id,) in self.db.execute('SELECT chat_id FROM sessions WHERE updated<?',(cutoff,)).fetchall(): self.delete(chat_id)
        with self.contacts: self.contacts.execute('DELETE FROM contacts WHERE created<?',(cutoff,))

    def export(self):
        rows=[]
        for (raw,) in self.db.execute('SELECT state FROM sessions'):
            state=json.loads(raw)
            if state.get('complete'):
                rows.append({k:state[k] for k in ('participant','version','mode','channel','answers','complete','screened_out') if k in state})
        return rows
