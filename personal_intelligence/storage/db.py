"""
Local-first SQLite database connection, encryption-at-rest, and initialization manager.
"""

import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Optional

from personal_intelligence.storage.crypto import DatabaseEncryptor, KeyManager


class DatabaseManager:
    """
    Manages local SQLite database connections, schema migrations, encryption-at-rest, and transactions.
    Ensures zero external server requirements, local-first data privacy, and external key management.
    """

    DEFAULT_DB_NAME = "personal_intelligence.db"

    def __init__(
        self,
        db_path: Optional[str] = None,
        use_encryption: bool = False,
        encryption_key: Optional[bytes] = None,
        key_manager: Optional[KeyManager] = None,
    ) -> None:
        self.use_encryption = use_encryption
        self.key_manager = key_manager or KeyManager()
        self.encryptor = DatabaseEncryptor(key=encryption_key, key_manager=self.key_manager)

        if db_path is None:
            data_dir = Path.home() / ".personal_intelligence"
            data_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = str(data_dir / self.DEFAULT_DB_NAME)
            self._anchor_conn = None
        elif db_path == ":memory:":
            self.db_path = f"file:memdb_{id(self)}?mode=memory&cache=shared"
            self._anchor_conn = sqlite3.connect(self.db_path, uri=True)
            self._anchor_conn.execute("PRAGMA foreign_keys = ON;")
        else:
            self.db_path = db_path
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self._anchor_conn = None

        self._active_conn_count = 0

    def get_connection(self) -> sqlite3.Connection:
        """Returns a configured SQLite connection with foreign keys enabled."""
        # If using shared memory database
        if self.db_path.startswith("file:memdb_"):
            conn = sqlite3.connect(self.db_path, uri=True)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON;")
            return conn

        # If the file on disk is an encrypted vault, decrypt it into a temporary working path if needed
        if os.path.exists(self.db_path) and self.encryptor.is_encrypted_file(self.db_path):
            # In encrypted-at-rest mode, decrypt to transient working database
            decrypted_bytes = self.encryptor.decrypt_bytes(open(self.db_path, "rb").read())
            temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
            temp_db.write(decrypted_bytes)
            temp_db.close()
            conn = sqlite3.connect(temp_db.name)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON;")
            return conn

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def seal_encrypted_database(self, target_path: Optional[str] = None) -> str:
        """
        Encrypts the SQLite database file at rest using the external master key.
        Guarantees that plaintext is sealed and MAC-authenticated.
        """
        out_path = target_path or self.db_path
        if not os.path.exists(self.db_path):
            self.initialize_schema()

        # If already encrypted, do not double-encrypt
        if self.encryptor.is_encrypted_file(self.db_path):
            return self.db_path

        temp_enc = self.db_path + ".enc.tmp"
        self.encryptor.encrypt_file(self.db_path, temp_enc)

        # Replace plaintext database file with encrypted file
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        os.rename(temp_enc, out_path)
        return out_path

    def unseal_database(self, source_path: Optional[str] = None, target_path: Optional[str] = None) -> str:
        """
        Decrypts an encrypted database vault using the external master key.
        """
        src = source_path or self.db_path
        dst = target_path or self.db_path
        if not self.encryptor.is_encrypted_file(src):
            return src

        temp_dec = dst + ".dec.tmp"
        self.encryptor.decrypt_file(src, temp_dec)
        if os.path.exists(dst):
            os.remove(dst)
        os.rename(temp_dec, dst)
        return dst

    def initialize_schema(self) -> None:
        """Executes the DDL schema to set up all required tables and indexes."""
        schema_path = Path(__file__).parent / "schema.sql"
        if not schema_path.exists():
            raise FileNotFoundError(f"Schema file not found at {schema_path}")

        with open(schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()

        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            # Check if event_log table has source_id and provenance_json
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='event_log';")
            if cursor.fetchone():
                cursor.execute("PRAGMA table_info(event_log);")
                event_cols = {row["name"] for row in cursor.fetchall()}
                if "source_id" not in event_cols:
                    cursor.execute("ALTER TABLE event_log ADD COLUMN source_id TEXT;")
                if "provenance_json" not in event_cols:
                    cursor.execute("ALTER TABLE event_log ADD COLUMN provenance_json TEXT;")

            # Check if reasoning_episodes table needs migration
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='reasoning_episodes';")
            if cursor.fetchone():
                cursor.execute("PRAGMA table_info(reasoning_episodes);")
                columns = {row["name"] for row in cursor.fetchall()}
                if "created_at" not in columns:
                    cursor.execute("DROP TABLE reasoning_episodes;")

            # Check if situations table has next_evaluation_at
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='situations';")
            if cursor.fetchone():
                cursor.execute("PRAGMA table_info(situations);")
                columns = {row["name"] for row in cursor.fetchall()}
                if "next_evaluation_at" not in columns:
                    cursor.execute("ALTER TABLE situations ADD COLUMN next_evaluation_at TEXT;")

            with conn:
                conn.executescript(schema_sql)
        finally:
            conn.close()
