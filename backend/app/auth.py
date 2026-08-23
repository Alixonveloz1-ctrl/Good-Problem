"""Single user access control (PRD 41).

The application has exactly one user: the owner. There is no sign up, no
invitations, no roles and no password recovery, so there is no login screen and
no OAuth consent screen to click through from a phone.

Access is enforced *outside* the application:

* Cloud Run ingress is restricted and the service requires authentication.
* Identity Aware Proxy sits in front and only the owner's Google account holds
  ``roles/iap.httpsResourceAccessor``.

IAP forwards the verified identity in ``X-Goog-Authenticated-User-Email`` and a
signed assertion in ``X-Goog-IAP-JWT-Assertion``. This module reads the header,
compares it against the configured owner and refuses everything else. It is the
second lock, not the first one: if the request reached the container at all,
IAP already vouched for it.

With ``AAUS_OWNER_EMAIL`` unset the gate is open, which is what running the
stack on a laptop needs.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from .errors import Forbidden
from .settings import Settings

IAP_EMAIL_HEADER = "x-goog-authenticated-user-email"
IAP_JWT_HEADER = "x-goog-iap-jwt-assertion"
DEV_EMAIL_HEADER = "x-dev-user-email"


@dataclass(frozen=True)
class Owner:
    email: str
    verified: bool
    """True when the identity came from IAP rather than from dev mode."""


def _strip_prefix(raw: str) -> str:
    # IAP sends "accounts.google.com:owner@example.com".
    return raw.split(":", 1)[-1].strip().lower() if raw else ""


def identify(request: Request, settings: Settings) -> Owner:
    header = request.headers.get(IAP_EMAIL_HEADER, "")
    email = _strip_prefix(header)
    verified = bool(email) and IAP_JWT_HEADER in request.headers

    if not settings.owner_email:
        # Dev mode: no owner configured, so nothing to enforce.
        return Owner(email=email or request.headers.get(DEV_EMAIL_HEADER, "dev@localhost"),
                     verified=False)

    if not email:
        raise Forbidden(
            "Falta la identidad de IAP. Este servicio solo acepta peticiones a traves de "
            "Identity Aware Proxy."
        )
    if email != settings.owner_email.strip().lower():
        raise Forbidden(f"La cuenta {email} no es la propietaria de este estudio.")
    return Owner(email=email, verified=verified)
