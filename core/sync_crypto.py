"""Clan code and end-to-end encryption for the sync messages.

The relay (an MQTT broker) is only a mailbox: everything it sees is random-looking bytes under a hashed topic.
Construction (standard library only): keys come from the clan code with HMAC-SHA256; the message is XOR-ed with an
HMAC-SHA256 counter-mode keystream (HMAC is a PRF) and authenticated with HMAC-SHA256 over version + nonce +
ciphertext (encrypt-then-MAC, constant-time compare).
"""
import base64
import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Optional

CODE_PREFIX = "SCUM1"
SECRET_BYTES = 16
MAX_PLAINTEXT = 32 * 1024
_VERSION = b"\x01"
_NONCE = 16
_TAG = 16
_CODE_BODY = re.compile(r"^[A-Z2-7]{26}$")


@dataclass(frozen=True)
class Keys:
    room: str       # public, hashed room id used inside topics
    enc: bytes
    mac: bytes


def new_code() -> str:
    """A fresh random clan code, e.g. SCUM1-ABCDE-FGHIJ-...; share it privately (Discord, in the clan chat)."""
    body = base64.b32encode(os.urandom(SECRET_BYTES)).decode().rstrip("=")
    return CODE_PREFIX + "-" + "-".join(body[i:i + 5] for i in range(0, len(body), 5))


def parse_code(code: str) -> Optional[bytes]:
    """The secret behind a clan code, or None when the text is not a valid code (typos are detected by length/alphabet)."""
    if not isinstance(code, str):
        return None
    text = re.sub(r"[\s\-_]", "", code).upper()
    if not text.startswith(CODE_PREFIX):
        return None
    body = text[len(CODE_PREFIX):]
    if not _CODE_BODY.match(body):
        return None
    try:
        secret = base64.b32decode(body + "======")
    except ValueError:
        return None
    return secret if len(secret) == SECRET_BYTES else None


def _kdf(secret: bytes, label: bytes) -> bytes:
    return hmac.new(secret, b"scum-sync/v1/" + label, hashlib.sha256).digest()


def derive(secret: bytes) -> Keys:
    return Keys(room=_kdf(secret, b"room").hex()[:24], enc=_kdf(secret, b"enc"), mac=_kdf(secret, b"mac"))


def keys_from_code(code: str) -> Optional[Keys]:
    secret = parse_code(code)
    return derive(secret) if secret else None


def _keystream(enc: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        out += hmac.new(enc, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        counter += 1
    return bytes(out[:length])


def _xor(data: bytes, stream: bytes) -> bytes:
    return (int.from_bytes(data, "big") ^ int.from_bytes(stream, "big")).to_bytes(len(data), "big") if data else b""


def seal(keys: Keys, message: Any) -> bytes:
    plain = json.dumps(message, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(plain) > MAX_PLAINTEXT:
        raise ValueError("message too large")
    nonce = os.urandom(_NONCE)
    cipher = _xor(plain, _keystream(keys.enc, nonce, len(plain)))
    tag = hmac.new(keys.mac, _VERSION + nonce + cipher, hashlib.sha256).digest()[:_TAG]
    return _VERSION + nonce + cipher + tag


def open_sealed(keys: Keys, blob: bytes) -> Optional[Any]:
    """The decrypted message, or None for anything forged, damaged, truncated or encrypted with another key."""
    if not isinstance(blob, (bytes, bytearray)) or len(blob) < 1 + _NONCE + _TAG or len(blob) > MAX_PLAINTEXT + 64:
        return None
    blob = bytes(blob)
    if blob[:1] != _VERSION:
        return None
    nonce, cipher, tag = blob[1:1 + _NONCE], blob[1 + _NONCE:-_TAG], blob[-_TAG:]
    expected = hmac.new(keys.mac, _VERSION + nonce + cipher, hashlib.sha256).digest()[:_TAG]
    if not hmac.compare_digest(tag, expected):
        return None
    try:
        return json.loads(_xor(cipher, _keystream(keys.enc, nonce, len(cipher))).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
