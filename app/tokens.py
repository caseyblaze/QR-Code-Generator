import hashlib
import secrets


ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def base62_encode(data: bytes) -> str:
    number = int.from_bytes(data, "big")
    if number == 0:
        return ALPHABET[0]

    base = len(ALPHABET)
    chars = []
    while number > 0:
        number, remainder = divmod(number, base)
        chars.append(ALPHABET[remainder])

    return "".join(reversed(chars))


def generate_token(url: str, secret: str, length: int) -> str:
    nonce = secrets.token_hex(8)
    payload = f"{url}:{nonce}:{secret}".encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return base62_encode(digest)[:length]
