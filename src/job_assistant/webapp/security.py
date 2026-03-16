from __future__ import annotations

import base64
import hashlib
import hmac
import os
from typing import Final


_SCRYPT_N: Final[int] = 2**14
_SCRYPT_R: Final[int] = 8
_SCRYPT_P: Final[int] = 1
_DKLEN: Final[int] = 64


class PasswordManager:
    def hash_password(self, password: str) -> str:
        salt = os.urandom(16)
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=_SCRYPT_N,
            r=_SCRYPT_R,
            p=_SCRYPT_P,
            dklen=_DKLEN,
        )
        salt_b64 = base64.urlsafe_b64encode(salt).decode("ascii")
        digest_b64 = base64.urlsafe_b64encode(digest).decode("ascii")
        return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt_b64}${digest_b64}"

    def verify_password(self, password: str, stored_hash: str) -> bool:
        try:
            algorithm, n_raw, r_raw, p_raw, salt_b64, digest_b64 = stored_hash.split("$", 5)
            if algorithm != "scrypt":
                return False
            expected = base64.urlsafe_b64decode(digest_b64.encode("ascii"))
            salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
            computed = hashlib.scrypt(
                password.encode("utf-8"),
                salt=salt,
                n=int(n_raw),
                r=int(r_raw),
                p=int(p_raw),
                dklen=len(expected),
            )
            return hmac.compare_digest(computed, expected)
        except Exception:
            return False
