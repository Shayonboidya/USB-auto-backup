import os
import hashlib
import sqlite3
import json
from pathlib import Path
from typing import Optional, Tuple

class BackupEngine:
    def __init__(self, db_path: str = None, hash_method: str = "sha256"):
        """
        Initialize the backup engine with a database and hash method.
        :param db_path: Path to the SQLite database file.
        :param hash_method: Hash algorithm to use (e.g., 'sha256', 'md5').
        """
        if db_path is None:
            # Default to backups.db next to this module
            db_path = Path(__file__).parent / "backups.db"
        self.db_path = str(db_path)
        self.hash_method = hash_method
        self._init_db()

    def _init_db(self):
        """Initialize the SQLite database and create the backups table if it doesn't exist."""
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
        """
        Compute the hash of a file.
        :param file_path: Path to the file.
        :return: Hexadecimal hash string or None if error.
        """
        try:
            hash_obj = hashlib.new(self.hash_method)
            with open(file_path, 'rb') as f:
                # Read file in chunks to handle large files efficiently
                for chunk in iter(lambda: f.read(4096), b''):
                    hash_obj.update(chunk)
            return hash_obj.hexdigest()
        except Exception as e:
            print(f"Error computing hash for {file_path}: {e}")
            return None

    def is_duplicate(self, file_hash: str) -> bool:
        """
        Check if a file hash already exists in the database.
        :param file_hash: The hash to check.
        :return: True if duplicate, False otherwise.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM backups WHERE file_hash = ?", (file_hash,))
        result = cursor.fetchone()
        conn.close()
        return result is not None

    def add_backup_record(self, file_hash: str, source_path: str, dest_path: str) -> bool:
        """
        Add a new backup record to the database.
        :param file_hash: The hash of the file.
        :param source_path: Original file path.
        :param dest_path: Backup file path.
        :return: True if successful, False if duplicate or error.
        """
        if self.is_duplicate(file_hash):
            return False  # Duplicate, do not add

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
        """
        Retrieve a backup record by hash.
        :param file_hash: The hash to look up.
        :return: Tuple (id, file_hash, source_path, dest_path, timestamp) or None.
        """
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
