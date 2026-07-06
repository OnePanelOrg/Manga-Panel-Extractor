import os
from functools import lru_cache
from typing import Optional

import jwt
from fastapi import Header, HTTPException
from jwt import PyJWKClient


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


@lru_cache(maxsize=1)
def _jwks_client() -> PyJWKClient:
    issuer = _required_env("CLERK_ISSUER").rstrip("/")
    jwks_url = os.environ.get(
        "CLERK_JWKS_URL",
        f"{issuer}/.well-known/jwks.json",
    ).strip()
    return PyJWKClient(jwks_url, cache_keys=True)


def verify_session_token(token: str) -> str:
    try:
        signing_key = _jwks_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=_required_env("CLERK_ISSUER").rstrip("/"),
            options={
                "require": ["exp", "iat", "sub"],
                "verify_aud": False,
            },
        )
    except (jwt.PyJWTError, RuntimeError) as error:
        raise HTTPException(
            status_code=401,
            detail="Your session is invalid or expired. Please sign in again.",
        ) from error

    authorized_parties = {
        party.strip()
        for party in os.environ.get("CLERK_AUTHORIZED_PARTIES", "").split(",")
        if party.strip()
    }
    if authorized_parties and claims.get("azp") not in authorized_parties:
        raise HTTPException(status_code=401, detail="Invalid session origin.")

    if claims.get("sts") not in (None, "active"):
        raise HTTPException(status_code=401, detail="Your session is not active.")

    return claims["sub"]


def require_user(
    authorization: Optional[str] = Header(default=None),
) -> str:
    scheme, separator, token = (authorization or "").partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    return verify_session_token(token.strip())
