# SPDX-License-Identifier: AGPL-3.0-or-later
"""Passkeys (WebAuthn): registration and sign-in ceremonies.

The relying party is the site the passkey is bound to. It comes from
``OPENCHART_PUBLIC_ORIGIN`` when set; otherwise from the request's Host, which
browsers only allow for ``localhost`` over plain HTTP (they require HTTPS for
anything else, and refuse IP addresses as relying-party IDs).
"""

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import Request
from webauthn import (
    base64url_to_bytes,
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.exceptions import InvalidAuthenticationResponse, InvalidRegistrationResponse
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from openchart_api.config import Settings

RP_NAME = "OpenChart AI"
CEREMONY_SECONDS = 300

PasskeyError = (InvalidRegistrationResponse, InvalidAuthenticationResponse, ValueError, KeyError)


@dataclass(frozen=True)
class RelyingParty:
    id: str
    origin: str


def relying_party(request: Request, settings: Settings) -> RelyingParty:
    if settings.public_origin and settings.public_host:
        return RelyingParty(settings.public_host, settings.public_origin)
    host = request.headers.get("host", "")
    hostname = urlsplit(f"//{host}").hostname or ""
    return RelyingParty(hostname, f"{request.url.scheme}://{host}")


def _descriptors(credential_ids: list[bytes]) -> list[PublicKeyCredentialDescriptor]:
    return [PublicKeyCredentialDescriptor(id=c) for c in credential_ids]


def registration_options(
    rp: RelyingParty,
    *,
    user_id: UUID,
    email: str,
    display_name: str,
    existing: list[bytes],
) -> tuple[dict[str, Any], str]:
    """Options for navigator.credentials.create(), and the challenge to remember."""
    options = generate_registration_options(
        rp_id=rp.id,
        rp_name=RP_NAME,
        user_id=user_id.bytes,
        user_name=email,
        user_display_name=display_name,
        exclude_credentials=_descriptors(existing),
        authenticator_selection=AuthenticatorSelectionCriteria(
            # Discoverable, so it can sign in without typing an email.
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        timeout=CEREMONY_SECONDS * 1000,
    )
    return json.loads(options_to_json(options)), bytes_to_base64url(options.challenge)


@dataclass(frozen=True)
class NewCredential:
    credential_id: bytes
    public_key: bytes
    sign_count: int
    backed_up: bool
    transports: list[str]


def verify_registration(
    rp: RelyingParty, credential: dict[str, Any], challenge: str
) -> NewCredential:
    verified = verify_registration_response(
        credential=credential,
        expected_challenge=base64url_to_bytes(challenge),
        expected_rp_id=rp.id,
        expected_origin=rp.origin,
        require_user_verification=True,
    )
    transports = [
        t
        for t in credential.get("response", {}).get("transports", []) or []
        if t in {member.value for member in AuthenticatorTransport}
    ]
    return NewCredential(
        credential_id=verified.credential_id,
        public_key=verified.credential_public_key,
        sign_count=verified.sign_count,
        backed_up=verified.credential_backed_up,
        transports=transports,
    )


def authentication_options(
    rp: RelyingParty, *, allow: list[bytes] | None, user_verification: bool
) -> tuple[dict[str, Any], str]:
    """Options for navigator.credentials.get(). ``allow=None`` lets the browser
    offer any passkey for this site (passwordless sign-in)."""
    options = generate_authentication_options(
        rp_id=rp.id,
        allow_credentials=_descriptors(allow) if allow else None,
        user_verification=(
            UserVerificationRequirement.REQUIRED
            if user_verification
            else UserVerificationRequirement.PREFERRED
        ),
        timeout=CEREMONY_SECONDS * 1000,
    )
    return json.loads(options_to_json(options)), bytes_to_base64url(options.challenge)


def credential_id_of(credential: dict[str, Any]) -> bytes:
    return base64url_to_bytes(str(credential["rawId"]))


def verify_authentication(
    rp: RelyingParty,
    credential: dict[str, Any],
    challenge: str,
    *,
    public_key: bytes,
    sign_count: int,
    user_verification: bool,
) -> int:
    """Verify a signed challenge. Returns the new signature counter.

    The library rejects a counter that did not increase (a cloned
    authenticator), unless the authenticator does not use counters at all.
    """
    verified = verify_authentication_response(
        credential=credential,
        expected_challenge=base64url_to_bytes(challenge),
        expected_rp_id=rp.id,
        expected_origin=rp.origin,
        credential_public_key=public_key,
        credential_current_sign_count=sign_count,
        require_user_verification=user_verification,
    )
    return verified.new_sign_count
