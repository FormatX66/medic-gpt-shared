from __future__ import annotations

import argparse
import base64
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


MAGIC = b"MEDICNMS1"
AAD = b"medic-gpt-shared:nms-tier2:slot3:v1"


def main() -> None:
    parser = argparse.ArgumentParser(description="Decrypt Bruce's NMS Tier 2 input package")
    parser.add_argument("artifact", type=Path)
    parser.add_argument("output_zip", type=Path)
    args = parser.parse_args()

    key_text = os.environ.get("MEDIC_NMS_TIER2_KEY_B64", "")
    if not key_text:
        raise SystemExit("MEDIC_NMS_TIER2_KEY_B64 is not set")
    key = base64.b64decode(key_text, validate=True)
    if len(key) != 32:
        raise SystemExit("MEDIC_NMS_TIER2_KEY_B64 does not decode to 32 bytes")

    payload = args.artifact.read_bytes()
    if not payload.startswith(MAGIC):
        raise SystemExit("unsupported artifact header")
    nonce = payload[len(MAGIC):len(MAGIC) + 12]
    ciphertext_and_tag = payload[len(MAGIC) + 12:]
    plaintext = AESGCM(key).decrypt(nonce, ciphertext_and_tag, AAD)
    args.output_zip.write_bytes(plaintext)
    print(f"decrypted {args.output_zip} ({len(plaintext)} bytes)")


if __name__ == "__main__":
    main()
