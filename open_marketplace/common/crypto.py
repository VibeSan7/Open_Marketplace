from hashlib import sha256
from secrets import token_urlsafe


def hash_one_time_token(raw_token: str) -> str:
    return sha256(raw_token.encode("ascii")).hexdigest()


def generate_one_time_token() -> tuple[str, str]:
    raw_token = token_urlsafe(32)
    return raw_token, hash_one_time_token(raw_token)
