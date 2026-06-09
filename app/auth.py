"""
Authentication — v0.6.0.

DESIGN:
  Two separate auth concerns:

  1. OPERATOR AUTH (review / admin / submissions / discover routes)
     Header:  X-API-Key: <OPERATOR_API_KEY>
     or:      Authorization: Bearer <OPERATOR_API_KEY>
     Config:  OPERATOR_API_KEY in .env

  2. WEBHOOK AUTH (POST /webhook only)
     Query param:  ?token=<WEBHOOK_SECRET>
     In JotForm:   Settings → Integrations → Webhook → URL
                   https://yourserver.com/webhook?token=<WEBHOOK_SECRET>
     Config:  WEBHOOK_SECRET in .env

SECURITY LEVELS:
  - If OPERATOR_API_KEY is empty: auth is DISABLED with a startup warning.
    This is acceptable in local dev/test. NEVER in production.
  - If WEBHOOK_SECRET is empty: webhook token check is DISABLED.
    NEVER in production.

USAGE:
  # In a route:
  from app.auth import require_operator
  @router.get("/something")
  def my_route(operator: str = Depends(require_operator)):
      ...

  # For the webhook, call verify_webhook_token(token) directly.
"""
from __future__ import annotations

import logging
import secrets

from fastapi import Depends, Header, HTTPException, Query, status
from typing import Annotated

logger = logging.getLogger("auth")

# ── Lazy settings import to avoid circular imports ────────────────────────────

def _settings():
    from app.config import settings
    return settings


# ── Operator authentication ───────────────────────────────────────────────────

def _get_operator_key(
    x_api_key:     str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> str | None:
    """Extract API key from X-API-Key header or Authorization: Bearer header."""
    if x_api_key:
        return x_api_key.strip()
    if authorization:
        parts = authorization.strip().split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
    return None


def require_operator(
    provided_key: Annotated[str | None, Depends(_get_operator_key)],
) -> str:
    """
    FastAPI dependency: enforce operator authentication.

    Returns the key (caller identity) on success.
    Raises HTTP 401 on missing or wrong key.
    Raises HTTP 503 if OPERATOR_API_KEY is not configured.

    Usage:
        @router.get("/review")
        def list_reviews(op: str = Depends(require_operator)):
            ...
    """
    cfg = _settings()
    expected = cfg.operator_api_key.strip()

    if not expected:
        # Auth is disabled — log a loud warning but allow through
        logger.warning(
            "SECURITY WARNING: OPERATOR_API_KEY not set. "
            "All operator endpoints are publicly accessible. "
            "Set OPERATOR_API_KEY in .env before production."
        )
        return "unauthenticated-dev"

    if not provided_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Provide 'X-API-Key: <key>' header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Constant-time comparison prevents timing attacks
    if not secrets.compare_digest(provided_key, expected):
        logger.warning("Auth failed: wrong API key (first 6 chars: %s...)", provided_key[:6])
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return "operator"


# ── Webhook token verification ────────────────────────────────────────────────

def verify_webhook_token(token: str | None) -> None:
    """
    Verify the webhook secret token.

    Called at the start of POST /webhook.
    Raises HTTP 401 if the token is wrong or missing (when WEBHOOK_SECRET is set).

    Args:
        token: value of ?token= query parameter from the incoming request.
    """
    cfg = _settings()
    expected = cfg.webhook_secret.strip()

    if not expected:
        logger.warning(
            "SECURITY WARNING: WEBHOOK_SECRET not set. "
            "Anyone can POST to /webhook. "
            "Set WEBHOOK_SECRET in .env and update your JotForm webhook URL."
        )
        return  # disabled — allow through

    if not token:
        logger.warning("Webhook rejected: no token in query string")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Missing webhook token. "
                "Add ?token=<WEBHOOK_SECRET> to your JotForm webhook URL."
            ),
        )

    if not secrets.compare_digest(token.strip(), expected):
        logger.warning("Webhook rejected: wrong token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook token.",
        )


# ── Startup security check ────────────────────────────────────────────────────

def warn_if_insecure() -> None:
    """
    Called during app startup. Logs warnings for missing security config.
    Does NOT raise — the app starts regardless, to support dev/test mode.
    """
    cfg = _settings()
    issues = []

    if not cfg.operator_api_key:
        issues.append("OPERATOR_API_KEY not set — operator endpoints are PUBLIC")
    if not cfg.webhook_secret:
        issues.append("WEBHOOK_SECRET not set — anyone can POST to /webhook")

    if issues:
        logger.warning("=" * 60)
        logger.warning("⚠️  SECURITY WARNINGS — NOT SAFE FOR PRODUCTION:")
        for issue in issues:
            logger.warning("    • %s", issue)
        logger.warning(
            "    Generate keys: "
            "python -c \"import secrets; print(secrets.token_urlsafe(32))\""
        )
        logger.warning("=" * 60)
    else:
        logger.info("Security: OPERATOR_API_KEY ✓  WEBHOOK_SECRET ✓")
