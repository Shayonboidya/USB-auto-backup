import os
import hashlib
import sqlite3
import json
from pathlib import Path
from typing import Optional, Tuple

class BackupEngine:
    def __init__(self, db_path: str = None, hash_method: str = "sha256"):
        if db_path is None:
            db_path = Path(__file__).parent / "backups.db"
        self.db_path = str(db_path)
        self.hash_method = hash_method
        self._init_db()

    def _init_db(self):
        """Initialize SQLite DB and create backups table if needed."""
        db_path = Path(self.db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS backups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_hash TEXT NOT NULL UNIQUE,
                source_path TEXT NOT NULL,
                dest_path TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()

    def compute_file_hash(self, file_path: str) -> Optional[str]:
        try:
            hash_obj = hashlib.new(self.hash_method)
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(4096), b''):
                    hash_obj.update(chunk)
            return hash_obj.hexdigest()
        except Exception as e:
            print(f"Error computing hash for {file_path}: {e}")
            return None

    def is_duplicate(self, file_hash: str) -> bool:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM backups WHERE file_hash = ?", (file_hash,))
        result = cursor.fetchone()
        conn.close()
        return result is not None

    def add_backup_record(self, file_hash: str, source_path: str, dest_path: str) -> bool:
        if self.is_duplicate(file_hash):
            return False
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO backups (file_hash, source_path, dest_path)
                VALUES (?, ?, ?)
            ''', (file_hash, source_path, dest_path))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error adding backup record: {e}")
            return False

    def get_backup_record(self, file_hash: str) -> Optional[Tuple]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, file_hash, source_path, dest_path, timestamp
            FROM backups
            WHERE file_hash = ?
        ''', (file_hash,))
        result = cursor.fetchone()
        conn.close()
        return result
