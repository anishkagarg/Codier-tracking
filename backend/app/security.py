import base64
import hashlib
import hmac
import os
import secrets


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    rounds = 240_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, rounds)
    return f"pbkdf2_sha256${rounds}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    if stored.startswith("pbkdf2_sha256$"):
        try:
            _, rounds, salt, digest = stored.split("$", 3)
            actual = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.urlsafe_b64decode(salt), int(rounds))
            return hmac.compare_digest(base64.urlsafe_b64decode(digest), actual)
        except (ValueError, TypeError):
            return False
    if stored.startswith(("$2a$", "$2b$", "$2y$")):
        try:
            import bcrypt
            return bcrypt.checkpw(password.encode(), stored.encode())
        except (ImportError, ValueError):
            return False
    return False


def hash_otp(code: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.sha256(salt + code.encode()).hexdigest()
    return salt.hex() + ":" + digest


def verify_otp(code: str, stored: str) -> bool:
    try:
        salt, digest = stored.split(":", 1)
        return hmac.compare_digest(hashlib.sha256(bytes.fromhex(salt) + code.encode()).hexdigest(), digest)
    except (ValueError, TypeError):
        return False

