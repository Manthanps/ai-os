import base64
import getpass
import os
import subprocess
import hashlib
import json
from cryptography.fernet import Fernet, InvalidToken


SERVICE_NAME = "avaos_encryption_key"
FALLBACK_KEY_PATH = os.path.join(os.path.dirname(__file__), "secure_key.json")


def _keychain_get():
    if os.name != "posix":
        return None
    try:
        user = getpass.getuser()
        out = subprocess.check_output(
            ["security", "find-generic-password", "-a", user, "-s", SERVICE_NAME, "-w"],
            text=True,
            stderr=subprocess.STDOUT,
        ).strip()
        if out:
            return out.encode("utf-8")
    except Exception:
        return None
    return None


def _keychain_set(key_bytes):
    if os.name != "posix":
        return False
    try:
        user = getpass.getuser()
        subprocess.check_call(
            ["security", "add-generic-password", "-a", user, "-s", SERVICE_NAME, "-w", key_bytes.decode("utf-8"), "-U"]
        )
        return True
    except Exception:
        return False


def _fallback_get():
    if os.path.exists(FALLBACK_KEY_PATH):
        try:
            with open(FALLBACK_KEY_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("key", "").encode("utf-8")
        except Exception:
            return None
    return None


def _fallback_set(key_bytes):
    try:
        with open(FALLBACK_KEY_PATH, "w", encoding="utf-8") as f:
            json.dump({"key": key_bytes.decode("utf-8")}, f)
        os.chmod(FALLBACK_KEY_PATH, 0o600)
        return True
    except Exception:
        return False


def get_key():
    key = _keychain_get()
    if key:
        return key
    key = _fallback_get()
    if key:
        return key
    key = Fernet.generate_key()
    if not _keychain_set(key):
        _fallback_set(key)
    return key


def encrypt_data(data: bytes) -> bytes:
    key = get_key()
    f = Fernet(key)
    return f.encrypt(data)


def decrypt_data(data: bytes) -> bytes:
    key = get_key()
    f = Fernet(key)
    return f.decrypt(data)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encrypt_file(path: str) -> str:
    with open(path, "rb") as f:
        raw = f.read()
    enc = encrypt_data(raw)
    out_path = path + ".enc"
    with open(out_path, "wb") as f:
        f.write(enc)
    return out_path


def decrypt_file(path: str) -> str:
    with open(path, "rb") as f:
        enc = f.read()
    raw = decrypt_data(enc)
    out_path = path.replace(".enc", "")
    with open(out_path, "wb") as f:
        f.write(raw)
    return out_path


def write_secure(path: str, content: str) -> str:
    data = content.encode("utf-8")
    enc = encrypt_data(data)
    with open(path, "wb") as f:
        f.write(enc)
    return path


def read_secure(path: str) -> str:
    with open(path, "rb") as f:
        enc = f.read()
    raw = decrypt_data(enc)
    return raw.decode("utf-8")


def verify_integrity(path: str, expected_sha256: str) -> bool:
    with open(path, "rb") as f:
        data = f.read()
    return sha256_bytes(data) == expected_sha256
