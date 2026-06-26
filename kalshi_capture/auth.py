from __future__ import annotations

import base64
import time
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


def load_private_key(path: str | Path) -> rsa.RSAPrivateKey:
    with Path(path).expanduser().open("rb") as key_file:
        private_key = serialization.load_pem_private_key(key_file.read(), password=None)

    if not isinstance(private_key, rsa.RSAPrivateKey):
        raise TypeError("Kalshi private key must be an RSA private key")

    return private_key


def sign_request(
    private_key: rsa.RSAPrivateKey,
    timestamp_ms: str,
    method: str,
    request_path: str,
) -> str:
    path_without_query = request_path.split("?", 1)[0]
    message = f"{timestamp_ms}{method.upper()}{path_without_query}".encode("utf-8")
    signature = private_key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("utf-8")


def auth_headers(
    private_key: rsa.RSAPrivateKey,
    key_id: str,
    method: str,
    request_path: str,
) -> dict[str, str]:
    timestamp_ms = str(int(time.time() * 1000))
    signature = sign_request(private_key, timestamp_ms, method, request_path)
    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-SIGNATURE": signature,
        "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
    }
