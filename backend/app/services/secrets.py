"""Fernet 密文入库；主密钥独立存储，权限仅限当前用户。"""

import fcntl
import hashlib
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class SecretStorageError(Exception):
    pass


class SecretStore:
    def __init__(self, database_path: Path, key_path: Path | None = None):
        identity = hashlib.sha256(str(database_path).encode()).hexdigest()[:24]
        self.path = key_path or Path.home() / ".config/mini-agent/keys" / f"{identity}.key"

    def _cipher(self, *, create: bool = False) -> Fernet:
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            flags = os.O_RDWR | os.O_NOFOLLOW | (os.O_CREAT if create else 0)
            fd = os.open(self.path, flags, 0o600)
            with os.fdopen(fd, "r+b") as file:
                fcntl.flock(file, fcntl.LOCK_EX)
                os.fchmod(file.fileno(), 0o600)
                key = file.read()
                if not key and create:
                    key = Fernet.generate_key()
                    file.write(key)
                    file.flush()
                    os.fsync(file.fileno())
                return Fernet(key)
        except (OSError, ValueError):
            raise SecretStorageError from None

    def encrypt(self, value: str, *, create: bool = False) -> str:
        return self._cipher(create=create).encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        try:
            return self._cipher().decrypt(value.encode()).decode()
        except (InvalidToken, UnicodeError):
            raise SecretStorageError from None
