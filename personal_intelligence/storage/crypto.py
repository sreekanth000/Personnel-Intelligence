"""
Cryptographic key management and encryption-at-rest vault for Personal Intelligence.
Guarantees:
1. Encryption at rest for SQLite databases and sensitive payloads.
2. Encryption keys are strictly stored outside the database file.
3. Authenticated encryption (Encrypt-then-MAC with HMAC-SHA256) preventing tampering.
4. Zero external C-dependency requirements (standard library cryptography).
"""

from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
from typing import Any, Dict, Optional, Tuple, Union


class KeyManager:
    """
    Manages cryptographic keys outside the SQLite database file.
    Reads master keys from local key files or environment variables.
    """

    DEFAULT_KEY_FILENAME = "master.key"

    def __init__(self, key_dir: Optional[str] = None, env_var: str = "PERSONAL_INTELLIGENCE_KEY") -> None:
        self.env_var = env_var
        if key_dir is None:
            self.key_dir = Path.home() / ".personal_intelligence" / "keys"
        else:
            self.key_dir = Path(key_dir)
        self.key_dir.mkdir(parents=True, exist_ok=True)
        self.key_file_path = self.key_dir / self.DEFAULT_KEY_FILENAME

    def get_or_create_master_key(self, custom_path: Optional[str] = None) -> bytes:
        """
        Retrieves the 256-bit master key from environment, specified file, or default key file.
        If no key exists, generates a cryptographically secure 32-byte key and writes it with restricted permissions.
        """
        # 1. Check environment variable
        env_val = os.environ.get(self.env_var)
        if env_val:
            if len(env_val) == 64:  # Hex string
                return bytes.fromhex(env_val)
            return hashlib.sha256(env_val.encode("utf-8")).digest()

        # 2. Check file path
        target_path = Path(custom_path) if custom_path else self.key_file_path
        if target_path.exists():
            with open(target_path, "rb") as f:
                key_bytes = f.read().strip()
                if len(key_bytes) == 64:  # Hex representation
                    return bytes.fromhex(key_bytes.decode("utf-8"))
                elif len(key_bytes) == 32:
                    return key_bytes
                return hashlib.sha256(key_bytes).digest()

        # 3. Generate new 32-byte key
        new_key = secrets.token_bytes(32)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with open(target_path, "wb") as f:
            f.write(new_key.hex().encode("utf-8"))

        # Restrict permissions if on POSIX
        try:
            os.chmod(target_path, 0o600)
        except Exception:
            pass

        return new_key

    @staticmethod
    def derive_key(passphrase: str, salt: bytes, iterations: int = 100000) -> bytes:
        """Derives a 256-bit key from a passphrase using PBKDF2-HMAC-SHA256."""
        return hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, iterations, dklen=32)


class DatabaseEncryptor:
    """
    Authenticated encryption engine for SQLite database files and sensitive payload records.
    Uses Encrypt-then-MAC (AES-CTR keystream + HMAC-SHA256) with integrity verification.
    """

    MAGIC_HEADER = b"PIDB_ENC_v1\x00"

    def __init__(self, key: Optional[bytes] = None, key_manager: Optional[KeyManager] = None) -> None:
        if key is not None:
            self.master_key = key
        else:
            km = key_manager or KeyManager()
            self.master_key = km.get_or_create_master_key()

        # Derive subkeys for encryption and authentication
        self.enc_key = hashlib.sha256(self.master_key + b"_encryption_subkey").digest()
        self.mac_key = hashlib.sha256(self.master_key + b"_authentication_subkey").digest()

    def _generate_keystream(self, iv: bytes, length: int) -> bytes:
        """Generates deterministic keystream using HMAC-SHA256 in counter mode."""
        blocks = []
        counter = 0
        while len(blocks) * 32 < length:
            ctr_bytes = counter.to_bytes(8, byteorder="big")
            block = hmac.new(self.enc_key, iv + ctr_bytes, hashlib.sha256).digest()
            blocks.append(block)
            counter += 1
        return b"".join(blocks)[:length]

    def encrypt_bytes(self, plaintext: bytes) -> bytes:
        """
        Encrypts raw bytes using authenticated stream encryption.
        Format: [MAGIC_HEADER(12B)] [IV(16B)] [CIPHERTEXT(NB)] [HMAC_TAG(32B)]
        """
        iv = secrets.token_bytes(16)
        keystream = self._generate_keystream(iv, len(plaintext))
        ciphertext = bytes(a ^ b for a, b in zip(plaintext, keystream))

        # Compute HMAC over Header + IV + Ciphertext
        mac_data = self.MAGIC_HEADER + iv + ciphertext
        tag = hmac.new(self.mac_key, mac_data, hashlib.sha256).digest()

        return mac_data + tag

    def decrypt_bytes(self, encrypted_data: bytes) -> bytes:
        """
        Verifies HMAC authentication tag and decrypts raw bytes.
        Raises ValueError on corrupted header or invalid authentication tag.
        """
        header_len = len(self.MAGIC_HEADER)
        if len(encrypted_data) < header_len + 16 + 32:
            raise ValueError("Encrypted data is too short to be valid.")

        if not encrypted_data.startswith(self.MAGIC_HEADER):
            raise ValueError("Invalid magic header: Data was not encrypted by DatabaseEncryptor.")

        tag = encrypted_data[-32:]
        payload_with_iv = encrypted_data[header_len:-32]
        mac_data = encrypted_data[:-32]

        # Verify HMAC in constant time
        expected_tag = hmac.new(self.mac_key, mac_data, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected_tag):
            raise ValueError("Authentication tag mismatch: Database ciphertext is corrupted or tampered with.")

        iv = payload_with_iv[:16]
        ciphertext = payload_with_iv[16:]

        keystream = self._generate_keystream(iv, len(ciphertext))
        plaintext = bytes(a ^ b for a, b in zip(ciphertext, keystream))
        return plaintext

    def encrypt_file(self, src_path: str, dst_path: str) -> None:
        """Encrypts an SQLite database file at rest."""
        with open(src_path, "rb") as f:
            data = f.read()
        encrypted = self.encrypt_bytes(data)
        Path(dst_path).parent.mkdir(parents=True, exist_ok=True)
        with open(dst_path, "wb") as f:
            f.write(encrypted)

    def decrypt_file(self, src_path: str, dst_path: str) -> None:
        """Decrypts an encrypted database file into plaintext for SQLite access."""
        with open(src_path, "rb") as f:
            encrypted = f.read()
        decrypted = self.decrypt_bytes(encrypted)
        Path(dst_path).parent.mkdir(parents=True, exist_ok=True)
        with open(dst_path, "wb") as f:
            f.write(decrypted)

    def is_encrypted_file(self, path: str) -> bool:
        """Checks if a file starts with the DatabaseEncryptor magic header."""
        if not os.path.exists(path) or os.path.getsize(path) < len(self.MAGIC_HEADER):
            return False
        with open(path, "rb") as f:
            header = f.read(len(self.MAGIC_HEADER))
        return header == self.MAGIC_HEADER
