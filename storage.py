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
        self.contacts.execute('CREATE TABLE IF NOT EXISTS contacts(participant TEXT PRIMARY KEY, contact TEXT NOT NULL, consent TEXT NOT NULL, created REAL NOT NULL)')
        for p in self.directory.glob('*.sqlite'): os.chmod(p,0o600)

    def load(self,chat_id):
        row=self.db.execute('SELECT state FROM sessions WHERE chat_id=?',(chat_id,)).fetchone()
        return json.loads(row[0]) if row else None

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
