from __future__ import annotations

from fastapi import Header

from frame.identity import Identity, resolve


def current_identity(
    x_frame_identity: str | None = Header(default=None, alias="X-Frame-Identity"),
) -> Identity:
    """Development stand-in for the IdP.

    Real deployments resolve the identity from a verified token and read the
    row-access policies that apply to it. Everything downstream — predicate
    injection, the cache key's policy fingerprint — is already correct.
    """
    return resolve(x_frame_identity)
