"""Генерация WS-токена для ручного теста Avanpost.

Использование:
    python scripts/encrypt_ws_token.py
    python scripts/encrypt_ws_token.py --key <base64> --fcm <token> --usr <usrXXX> --date 261027
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from datetime import UTC, datetime

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

DEFAULT_KEY_B64 = "k7Xq3vN8mR2pL9wT4yB6cD1eF5gH0jK8sV3nM7qP2rU="
DEFAULT_FCM = "cM7xQ2vN8pL4wT6yB1nK3mR9dF5gH0jA2sV8qP4rU6tX"
DEFAULT_USR = "usrAbCdEfGhIjKlMnOpQr"
DEFAULT_DATE = None  # yyMMdd; None → сегодня UTC
DEFAULT_IP = "203.0.113.42"


def build_ws_token(key_b64: str, fcm_token: str, usr_id: str, date_str: str) -> str:
    key = base64.b64decode(key_b64)
    if len(key) != 32:
        raise ValueError(f"key must be 32 bytes, got {len(key)}")

    plaintext = f"{fcm_token}|{usr_id}|{date_str}"
    pt_bytes = plaintext.encode("utf-8")

    iv = hashlib.sha256(pt_bytes).digest()[:12]
    ct_and_tag = AESGCM(key).encrypt(iv, pt_bytes, None)
    payload_bin = iv + ct_and_tag
    return base64.b64encode(payload_bin).decode("ascii")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--key", default=DEFAULT_KEY_B64)
    parser.add_argument("--fcm", default=DEFAULT_FCM)
    parser.add_argument("--usr", default=DEFAULT_USR)
    parser.add_argument(
        "--date",
        default=DEFAULT_DATE,
        help="yyMMdd (например 261027); по умолчанию сегодня UTC",
    )
    parser.add_argument("--ip", default=DEFAULT_IP)
    args = parser.parse_args()

    date_str = args.date or datetime.now(UTC).strftime("%y%m%d")

    try:
        payload_b64 = build_ws_token(args.key, args.fcm, args.usr, date_str)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    plaintext = f"{args.fcm}|{args.usr}|{date_str}"
    key = base64.b64decode(args.key)

    print("KEY_B64       :", args.key)
    print("KEY hex       :", key.hex())
    print("PLAINTEXT     :", plaintext)
    print("PLAINTEXT len :", len(plaintext.encode("utf-8")))
    print("DATE          :", date_str, "(yyMMdd)")
    print("Payload len   :", len(payload_b64))
    print("Payload base64:", payload_b64)
    print()

    params_json = json.dumps(
        {"payload": payload_b64, "client_ip": args.ip},
        ensure_ascii=False,
    )
    print("JSON @Params (для вставки в SQL Server):")
    print(params_json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
