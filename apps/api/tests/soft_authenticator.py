# SPDX-License-Identifier: AGPL-3.0-or-later
"""A software WebAuthn authenticator for tests.

Produces the same JSON a browser sends after navigator.credentials.create()
and .get(): CBOR "none" attestation with a real P-256 key, and properly
signed assertions. Knobs let tests misbehave on purpose (wrong origin, no
user verification, a counter that goes backwards).
"""

import base64
import hashlib
import json
import os
import struct
from typing import Any

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class SoftAuthenticator:
    def __init__(self, origin: str = "http://testserver", rp_id: str = "testserver") -> None:
        self.origin = origin
        self.rp_id = rp_id
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(16)
        self.sign_count = 0
        self.user_handle = b""

    def _client_data(self, kind: str, challenge: str, origin: str | None) -> bytes:
        return json.dumps(
            {
                "type": kind,
                "challenge": challenge,
                "origin": origin or self.origin,
                "crossOrigin": False,
            }
        ).encode()

    def _auth_data(self, rp_id: str | None, *, uv: bool, attested: bool = False) -> bytes:
        flags = 0x01 | (0x04 if uv else 0) | (0x40 if attested else 0)
        data = hashlib.sha256((rp_id or self.rp_id).encode()).digest()
        data += bytes([flags]) + struct.pack(">I", self.sign_count)
        if attested:
            numbers = self.key.public_key().public_numbers()
            cose_key = cbor2.dumps(
                {
                    1: 2,  # kty: EC2
                    3: -7,  # alg: ES256
                    -1: 1,  # crv: P-256
                    -2: numbers.x.to_bytes(32, "big"),
                    -3: numbers.y.to_bytes(32, "big"),
                }
            )
            data += bytes(16) + struct.pack(">H", len(self.credential_id)) + self.credential_id
            data += cose_key
        return data

    def create(self, options: dict[str, Any], *, origin: str | None = None) -> dict[str, Any]:
        self.user_handle = unb64url(options["user"]["id"])
        client_data = self._client_data("webauthn.create", options["challenge"], origin)
        attestation = cbor2.dumps(
            {
                "fmt": "none",
                "attStmt": {},
                "authData": self._auth_data(options["rp"]["id"], uv=True, attested=True),
            }
        )
        return {
            "id": b64url(self.credential_id),
            "rawId": b64url(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64url(client_data),
                "attestationObject": b64url(attestation),
                "transports": ["internal"],
            },
            "clientExtensionResults": {},
            "authenticatorAttachment": "platform",
        }

    def get(
        self,
        options: dict[str, Any],
        *,
        origin: str | None = None,
        rp_id: str | None = None,
        uv: bool = True,
        bump_counter: bool = True,
    ) -> dict[str, Any]:
        if bump_counter:
            self.sign_count += 1
        client_data = self._client_data("webauthn.get", options["challenge"], origin)
        auth_data = self._auth_data(rp_id or options.get("rpId"), uv=uv)
        signature = self.key.sign(
            auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256())
        )
        return {
            "id": b64url(self.credential_id),
            "rawId": b64url(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64url(client_data),
                "authenticatorData": b64url(auth_data),
                "signature": b64url(signature),
                "userHandle": b64url(self.user_handle),
            },
            "clientExtensionResults": {},
            "authenticatorAttachment": "platform",
        }
