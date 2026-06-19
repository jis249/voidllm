"""First-run bootstrap when WAI_ADMIN_KEY is set and no api_keys exist."""

from __future__ import annotations

import logging
import os
import secrets
import string
from dataclasses import dataclass

import bcrypt

from wai.api.admin.common import (
    KEY_TYPE_USER,
    ROLE_ORG_ADMIN,
    ROLE_SYSTEM_ADMIN,
    KeyInfo,
    generate_key,
    hash_key,
    hint_key,
    new_uuid,
)
from wai.config.models import SettingsConfig
from wai.db.connection import Database


@dataclass
class BootstrapResult:
    api_key: str
    email: str
    password: str


def _generate_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


class KeyCacheLike:
    def set(self, key_hash: str, info: KeyInfo) -> None: ...


async def bootstrap(
    db: Database,
    settings: SettingsConfig,
    hmac_secret: bytes,
    key_cache: KeyCacheLike | None = None,
    log: logging.Logger | None = None,
) -> BootstrapResult | None:
    """Create org, admin user, and API key on first run. Returns credentials or None."""
    logger = log or logging.getLogger("wai.bootstrap")
    admin_key = settings.admin_key
    if not admin_key:
        return None
    if len(admin_key) < 32:
        raise ValueError("admin key must be at least 32 characters")

    row = await db.fetchone(
        "SELECT COUNT(*) AS cnt FROM api_keys WHERE deleted_at IS NULL"
    )
    if row and row["cnt"] > 0:
        logger.warning("WAI_ADMIN_KEY is set but database already has keys, ignoring")
        return None

    org_name = settings.bootstrap.org_name
    org_slug = settings.bootstrap.org_slug
    admin_email = settings.bootstrap.admin_email
    password = _generate_password()
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    plaintext_key = generate_key(KEY_TYPE_USER)
    key_hash = hash_key(plaintext_key, hmac_secret)
    key_hint = hint_key(plaintext_key)

    org_id = new_uuid()
    user_id = new_uuid()
    membership_id = new_uuid()
    key_id = new_uuid()

    async with db.transaction() as conn:
        await conn.execute(
            "INSERT INTO organizations (id, name, slug, created_at, updated_at) "
            "VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (org_id, org_name, org_slug),
        )
        await conn.execute(
            """INSERT INTO users (id, email, display_name, password_hash, auth_provider,
                                  is_system_admin, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'local', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            (user_id, admin_email, "Admin", password_hash),
        )
        await conn.execute(
            "INSERT INTO org_memberships (id, org_id, user_id, role, created_at) "
            "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (membership_id, org_id, user_id, ROLE_ORG_ADMIN),
        )
        await conn.execute(
            """INSERT INTO api_keys (id, key_hash, key_hint, key_type, name, org_id, user_id,
                                     created_by, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            (key_id, key_hash, key_hint, KEY_TYPE_USER, "Bootstrap Admin Key", org_id, user_id, user_id),
        )

    if key_cache is not None:
        key_cache.set(
            key_hash,
            KeyInfo(
                id=key_id,
                key_type=KEY_TYPE_USER,
                role=ROLE_SYSTEM_ADMIN,
                org_id=org_id,
                user_id=user_id,
                name="Bootstrap Admin Key",
            ),
        )

    os.environ.pop("WAI_ADMIN_KEY", None)
    logger.warning("bootstrap complete, default organization and system admin created (key_hint=%s)", key_hint)

    return BootstrapResult(api_key=plaintext_key, email=admin_email, password=password)


def print_bootstrap_credentials(result: BootstrapResult | None) -> None:
    if result is None:
        return
    import sys

    print("", file=sys.stderr)
    print("========================================", file=sys.stderr)
    print(" BOOTSTRAP COMPLETE — COPY THESE NOW", file=sys.stderr)
    print("========================================", file=sys.stderr)
    print(f"  API Key:    {result.api_key}", file=sys.stderr)
    print(f"  Email:      {result.email}", file=sys.stderr)
    print(f"  Password:   {result.password}", file=sys.stderr)
    print("========================================", file=sys.stderr)
    print("", file=sys.stderr)
