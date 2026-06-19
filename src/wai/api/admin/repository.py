"""Raw SQL repository for admin API handlers."""

from __future__ import annotations

import json
import asyncpg
from datetime import datetime, timezone
from typing import Any

from wai.api.admin.common import new_uuid, utc_now_iso
from wai.db.connection import Database

ERR_NOT_FOUND = "not_found"
ERR_CONFLICT = "conflict"


class NotFoundError(Exception):
    pass


class ConflictError(Exception):
    pass


def _translate(err: Exception) -> Exception:
    if isinstance(err, asyncpg.exceptions.UniqueViolationError):
        return ConflictError(str(err))
    return err


async def count_orgs(db: Database) -> int:
    row = await db.fetchone(
        "SELECT COUNT(*) AS c FROM organizations WHERE deleted_at IS NULL"
    )
    return int(row["c"]) if row else 0


async def create_org(
    db: Database,
    *,
    name: str,
    slug: str,
    timezone: str | None,
    daily_token_limit: int,
    monthly_token_limit: int,
    requests_per_minute: int,
    requests_per_day: int,
) -> dict[str, Any]:
    oid = new_uuid()
    try:
        await db.execute(
            """INSERT INTO organizations
               (id, name, slug, timezone, daily_token_limit, monthly_token_limit,
                requests_per_minute, requests_per_day, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            (oid, name, slug, timezone, daily_token_limit, monthly_token_limit,
             requests_per_minute, requests_per_day),
        )
        await db.commit()
    except asyncpg.exceptions.UniqueViolationError as e:
        raise ConflictError(str(e)) from e
    org = await get_org_with_counts(db, oid)
    assert org is not None
    return org


async def get_org(db: Database, org_id: str) -> dict[str, Any] | None:
    row = await db.fetchone(
        """SELECT id, name, slug, timezone, daily_token_limit, monthly_token_limit,
                  requests_per_minute, requests_per_day, created_at, updated_at, deleted_at
           FROM organizations WHERE id = ? AND deleted_at IS NULL""",
        (org_id,),
    )
    return dict(row) if row else None


async def get_org_with_counts(db: Database, org_id: str) -> dict[str, Any] | None:
    row = await db.fetchone(
        """SELECT o.id, o.name, o.slug, o.timezone, o.daily_token_limit, o.monthly_token_limit,
                  o.requests_per_minute, o.requests_per_day, o.created_at, o.updated_at, o.deleted_at,
                  (SELECT COUNT(*) FROM org_memberships m WHERE m.org_id = o.id) AS member_count,
                  (SELECT COUNT(*) FROM teams t WHERE t.org_id = o.id AND t.deleted_at IS NULL) AS team_count
           FROM organizations o WHERE o.id = ? AND o.deleted_at IS NULL""",
        (org_id,),
    )
    return dict(row) if row else None


async def list_orgs_with_counts(
    db: Database, cursor: str, limit: int, include_deleted: bool
) -> list[dict[str, Any]]:
    deleted_clause = "" if include_deleted else "AND o.deleted_at IS NULL"
    params: list[Any] = []
    cursor_clause = ""
    if cursor:
        cursor_clause = "AND o.id > ?"
        params.append(cursor)
    params.append(limit)
    rows = await db.fetchall(
        f"""SELECT o.id, o.name, o.slug, o.timezone, o.daily_token_limit, o.monthly_token_limit,
                   o.requests_per_minute, o.requests_per_day, o.created_at, o.updated_at, o.deleted_at,
                   (SELECT COUNT(*) FROM org_memberships m WHERE m.org_id = o.id) AS member_count,
                   (SELECT COUNT(*) FROM teams t WHERE t.org_id = o.id AND t.deleted_at IS NULL) AS team_count
            FROM organizations o WHERE 1=1 {deleted_clause} {cursor_clause}
            ORDER BY o.id LIMIT ?""",
        tuple(params),
    )
    return [dict(r) for r in rows]


async def update_org(db: Database, org_id: str, fields: dict[str, Any]) -> None:
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [org_id]
    try:
        cur = await db.execute(
            f"UPDATE organizations SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND deleted_at IS NULL",
            tuple(vals),
        )
        await db.commit()
        if cur.rowcount == 0:
            raise NotFoundError(org_id)
    except asyncpg.exceptions.UniqueViolationError as e:
        raise ConflictError(str(e)) from e


async def delete_org(db: Database, org_id: str) -> None:
    cur = await db.execute(
        "UPDATE organizations SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND deleted_at IS NULL",
        (org_id,),
    )
    await db.commit()
    if cur.rowcount == 0:
        raise NotFoundError(org_id)


async def get_org_by_slug(db: Database, slug: str) -> dict[str, Any] | None:
    row = await db.fetchone(
        "SELECT id, name, slug FROM organizations WHERE slug = ? AND deleted_at IS NULL",
        (slug,),
    )
    return dict(row) if row else None


async def create_user(
    db: Database,
    *,
    email: str,
    display_name: str,
    password_hash: str | None,
    auth_provider: str,
    is_system_admin: bool = False,
    external_id: str | None = None,
) -> dict[str, Any]:
    uid = new_uuid()
    try:
        await db.execute(
            """INSERT INTO users (id, email, display_name, password_hash, auth_provider,
                                  external_id, is_system_admin, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            (uid, email, display_name, password_hash, auth_provider, external_id,
             1 if is_system_admin else 0),
        )
        await db.commit()
    except asyncpg.exceptions.UniqueViolationError as e:
        raise ConflictError(str(e)) from e
    user = await get_user(db, uid)
    assert user is not None
    return user


async def get_user(db: Database, user_id: str) -> dict[str, Any] | None:
    row = await db.fetchone(
        """SELECT id, email, display_name, auth_provider, is_system_admin,
                  created_at, updated_at, deleted_at
           FROM users WHERE id = ? AND deleted_at IS NULL""",
        (user_id,),
    )
    if not row:
        return None
    d = dict(row)
    d["is_system_admin"] = bool(d["is_system_admin"])
    return d


async def get_user_by_external_id(db: Database, provider: str, external_id: str) -> dict[str, Any] | None:
    row = await db.fetchone(
        """SELECT id, email, display_name, auth_provider, is_system_admin,
                  created_at, updated_at, deleted_at
           FROM users WHERE auth_provider = ? AND external_id = ? AND deleted_at IS NULL""",
        (provider, external_id),
    )
    if not row:
        return None
    d = dict(row)
    d["is_system_admin"] = bool(d["is_system_admin"])
    return d


async def get_user_password_hash(db: Database, email: str) -> tuple[str, str]:
    row = await db.fetchone(
        "SELECT id, password_hash FROM users WHERE email = ? AND deleted_at IS NULL",
        (email,),
    )
    if not row:
        raise NotFoundError("user")
    if not row["password_hash"]:
        raise NotFoundError("no_password")
    return row["id"], row["password_hash"]


async def list_users(db: Database, cursor: str, limit: int, include_deleted: bool) -> list[dict[str, Any]]:
    deleted_clause = "" if include_deleted else "AND deleted_at IS NULL"
    params: list[Any] = []
    cursor_clause = ""
    if cursor:
        cursor_clause = "AND id > ?"
        params.append(cursor)
    params.append(limit)
    rows = await db.fetchall(
        f"""SELECT id, email, display_name, auth_provider, is_system_admin,
                   created_at, updated_at, deleted_at
            FROM users WHERE 1=1 {deleted_clause} {cursor_clause}
            ORDER BY id LIMIT ?""",
        tuple(params),
    )
    out = []
    for r in rows:
        d = dict(r)
        d["is_system_admin"] = bool(d["is_system_admin"])
        out.append(d)
    return out


async def update_user(db: Database, user_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    if not fields:
        user = await get_user(db, user_id)
        if not user:
            raise NotFoundError(user_id)
        return user
    sets = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [user_id]
    try:
        cur = await db.execute(
            f"UPDATE users SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND deleted_at IS NULL",
            tuple(vals),
        )
        await db.commit()
        if cur.rowcount == 0:
            raise NotFoundError(user_id)
    except asyncpg.exceptions.UniqueViolationError as e:
        raise ConflictError(str(e)) from e
    user = await get_user(db, user_id)
    assert user is not None
    return user


async def delete_user(db: Database, user_id: str) -> None:
    cur = await db.execute(
        "UPDATE users SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND deleted_at IS NULL",
        (user_id,),
    )
    await db.commit()
    if cur.rowcount == 0:
        raise NotFoundError(user_id)


async def resolve_user_role(db: Database, user_id: str) -> tuple[str, str]:
    row = await db.fetchone(
        """SELECT u.is_system_admin, om.role, om.org_id
           FROM users u
           LEFT JOIN org_memberships om ON om.user_id = u.id
           WHERE u.id = ? AND u.deleted_at IS NULL
           ORDER BY om.created_at LIMIT 1""",
        (user_id,),
    )
    if not row:
        raise NotFoundError(user_id)
    if row["is_system_admin"]:
        org_row = await db.fetchone(
            "SELECT org_id FROM org_memberships WHERE user_id = ? LIMIT 1", (user_id,)
        )
        org_id = org_row["org_id"] if org_row else ""
        return "system_admin", org_id
    if not row["org_id"]:
        raise NotFoundError("membership")
    return row["role"], row["org_id"]


async def get_user_org_role(db: Database, user_id: str, org_id: str) -> str:
    row = await db.fetchone(
        "SELECT role FROM org_memberships WHERE user_id = ? AND org_id = ?",
        (user_id, org_id),
    )
    if not row:
        raise NotFoundError("membership")
    return row["role"]


async def create_org_membership(db: Database, org_id: str, user_id: str, role: str) -> dict[str, Any]:
    mid = new_uuid()
    try:
        await db.execute(
            "INSERT INTO org_memberships (id, org_id, user_id, role, created_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (mid, org_id, user_id, role),
        )
        await db.commit()
    except asyncpg.exceptions.UniqueViolationError as e:
        raise ConflictError(str(e)) from e
    m = await get_org_membership(db, mid)
    assert m is not None
    return m


async def get_org_membership(db: Database, membership_id: str) -> dict[str, Any] | None:
    row = await db.fetchone(
        "SELECT id, org_id, user_id, role, created_at FROM org_memberships WHERE id = ?",
        (membership_id,),
    )
    return dict(row) if row else None


async def list_org_memberships(db: Database, org_id: str, cursor: str, limit: int) -> list[dict[str, Any]]:
    params: list[Any] = [org_id]
    cursor_clause = ""
    if cursor:
        cursor_clause = "AND id > ?"
        params.append(cursor)
    params.append(limit)
    rows = await db.fetchall(
        f"""SELECT id, org_id, user_id, role, created_at FROM org_memberships
            WHERE org_id = ? {cursor_clause} ORDER BY id LIMIT ?""",
        tuple(params),
    )
    return [dict(r) for r in rows]


async def update_org_membership(db: Database, membership_id: str, role: str | None) -> dict[str, Any]:
    if role is None:
        m = await get_org_membership(db, membership_id)
        if not m:
            raise NotFoundError(membership_id)
        return m
    cur = await db.execute(
        "UPDATE org_memberships SET role = ? WHERE id = ?", (role, membership_id)
    )
    await db.commit()
    if cur.rowcount == 0:
        raise NotFoundError(membership_id)
    m = await get_org_membership(db, membership_id)
    assert m is not None
    return m


async def delete_org_membership(db: Database, membership_id: str) -> None:
    cur = await db.execute("DELETE FROM org_memberships WHERE id = ?", (membership_id,))
    await db.commit()
    if cur.rowcount == 0:
        raise NotFoundError(membership_id)


async def count_teams(db: Database, org_id: str) -> int:
    row = await db.fetchone(
        "SELECT COUNT(*) AS c FROM teams WHERE org_id = ? AND deleted_at IS NULL", (org_id,)
    )
    return int(row["c"]) if row else 0


async def create_team(db: Database, org_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    tid = new_uuid()
    try:
        await db.execute(
            """INSERT INTO teams (id, org_id, name, slug, daily_token_limit, monthly_token_limit,
                                  requests_per_minute, requests_per_day, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            (tid, org_id, fields["name"], fields["slug"], fields.get("daily_token_limit", 0),
             fields.get("monthly_token_limit", 0), fields.get("requests_per_minute", 0),
             fields.get("requests_per_day", 0)),
        )
        await db.commit()
    except asyncpg.exceptions.UniqueViolationError as e:
        raise ConflictError(str(e)) from e
    team = await get_team(db, tid)
    assert team is not None
    return team


async def get_team(db: Database, team_id: str) -> dict[str, Any] | None:
    row = await db.fetchone(
        """SELECT id, org_id, name, slug, daily_token_limit, monthly_token_limit,
                  requests_per_minute, requests_per_day, created_at, updated_at, deleted_at
           FROM teams WHERE id = ? AND deleted_at IS NULL""",
        (team_id,),
    )
    return dict(row) if row else None


async def get_team_with_counts(db: Database, team_id: str) -> dict[str, Any] | None:
    row = await db.fetchone(
        """SELECT t.id, t.org_id, t.name, t.slug, t.daily_token_limit, t.monthly_token_limit,
                  t.requests_per_minute, t.requests_per_day, t.created_at, t.updated_at, t.deleted_at,
                  (SELECT COUNT(*) FROM team_memberships tm WHERE tm.team_id = t.id) AS member_count,
                  (SELECT COUNT(*) FROM api_keys k WHERE k.team_id = t.id AND k.deleted_at IS NULL) AS key_count
           FROM teams t WHERE t.id = ? AND t.deleted_at IS NULL""",
        (team_id,),
    )
    return dict(row) if row else None


async def get_team_by_name(db: Database, org_id: str, name: str) -> dict[str, Any] | None:
    row = await db.fetchone(
        "SELECT id, org_id, name, slug FROM teams WHERE org_id = ? AND name = ? AND deleted_at IS NULL",
        (org_id, name),
    )
    return dict(row) if row else None


async def list_teams_with_counts(
    db: Database, org_id: str, cursor: str, limit: int, include_deleted: bool
) -> list[dict[str, Any]]:
    deleted_clause = "" if include_deleted else "AND t.deleted_at IS NULL"
    params: list[Any] = [org_id]
    cursor_clause = ""
    if cursor:
        cursor_clause = "AND t.id > ?"
        params.append(cursor)
    params.append(limit)
    rows = await db.fetchall(
        f"""SELECT t.id, t.org_id, t.name, t.slug, t.daily_token_limit, t.monthly_token_limit,
                   t.requests_per_minute, t.requests_per_day, t.created_at, t.updated_at, t.deleted_at,
                   (SELECT COUNT(*) FROM team_memberships tm WHERE tm.team_id = t.id) AS member_count,
                   (SELECT COUNT(*) FROM api_keys k WHERE k.team_id = t.id AND k.deleted_at IS NULL) AS key_count
            FROM teams t WHERE t.org_id = ? {deleted_clause} {cursor_clause}
            ORDER BY t.id LIMIT ?""",
        tuple(params),
    )
    return [dict(r) for r in rows]


async def list_user_teams(db: Database, org_id: str, user_id: str) -> list[dict[str, Any]]:
    rows = await db.fetchall(
        """SELECT t.id, t.org_id, t.name, t.slug, t.daily_token_limit, t.monthly_token_limit,
                  t.requests_per_minute, t.requests_per_day, t.created_at, t.updated_at, t.deleted_at,
                  (SELECT COUNT(*) FROM team_memberships tm2 WHERE tm2.team_id = t.id) AS member_count,
                  (SELECT COUNT(*) FROM api_keys k WHERE k.team_id = t.id AND k.deleted_at IS NULL) AS key_count
           FROM teams t
           JOIN team_memberships tm ON tm.team_id = t.id AND tm.user_id = ?
           WHERE t.org_id = ? AND t.deleted_at IS NULL""",
        (user_id, org_id),
    )
    return [dict(r) for r in rows]


async def update_team(db: Database, team_id: str, fields: dict[str, Any]) -> None:
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [team_id]
    try:
        cur = await db.execute(
            f"UPDATE teams SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND deleted_at IS NULL",
            tuple(vals),
        )
        await db.commit()
        if cur.rowcount == 0:
            raise NotFoundError(team_id)
    except asyncpg.exceptions.UniqueViolationError as e:
        raise ConflictError(str(e)) from e


async def delete_team(db: Database, team_id: str) -> None:
    cur = await db.execute(
        "UPDATE teams SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND deleted_at IS NULL",
        (team_id,),
    )
    await db.commit()
    if cur.rowcount == 0:
        raise NotFoundError(team_id)


async def is_team_member(db: Database, user_id: str, team_id: str) -> bool:
    row = await db.fetchone(
        "SELECT 1 FROM team_memberships WHERE user_id = ? AND team_id = ? LIMIT 1",
        (user_id, team_id),
    )
    return row is not None


async def create_team_membership(db: Database, team_id: str, user_id: str, role: str) -> dict[str, Any]:
    mid = new_uuid()
    try:
        await db.execute(
            "INSERT INTO team_memberships (id, team_id, user_id, role, created_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (mid, team_id, user_id, role),
        )
        await db.commit()
    except asyncpg.exceptions.UniqueViolationError as e:
        raise ConflictError(str(e)) from e
    m = await get_team_membership(db, mid)
    assert m is not None
    return m


async def get_team_membership(db: Database, membership_id: str) -> dict[str, Any] | None:
    row = await db.fetchone(
        "SELECT id, team_id, user_id, role, created_at FROM team_memberships WHERE id = ?",
        (membership_id,),
    )
    return dict(row) if row else None


async def list_team_memberships(db: Database, team_id: str, cursor: str, limit: int) -> list[dict[str, Any]]:
    params: list[Any] = [team_id]
    cursor_clause = ""
    if cursor:
        cursor_clause = "AND id > ?"
        params.append(cursor)
    params.append(limit)
    rows = await db.fetchall(
        f"""SELECT id, team_id, user_id, role, created_at FROM team_memberships
            WHERE team_id = ? {cursor_clause} ORDER BY id LIMIT ?""",
        tuple(params),
    )
    return [dict(r) for r in rows]


async def update_team_membership(db: Database, membership_id: str, role: str | None) -> dict[str, Any]:
    if role is None:
        m = await get_team_membership(db, membership_id)
        if not m:
            raise NotFoundError(membership_id)
        return m
    cur = await db.execute(
        "UPDATE team_memberships SET role = ? WHERE id = ?", (role, membership_id)
    )
    await db.commit()
    if cur.rowcount == 0:
        raise NotFoundError(membership_id)
    m = await get_team_membership(db, membership_id)
    assert m is not None
    return m


async def delete_team_membership(db: Database, membership_id: str) -> None:
    cur = await db.execute("DELETE FROM team_memberships WHERE id = ?", (membership_id,))
    await db.commit()
    if cur.rowcount == 0:
        raise NotFoundError(membership_id)


async def create_service_account(
    db: Database, name: str, org_id: str, team_id: str | None, created_by: str
) -> dict[str, Any]:
    sid = new_uuid()
    await db.execute(
        """INSERT INTO service_accounts (id, name, org_id, team_id, created_by, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
        (sid, name, org_id, team_id, created_by),
    )
    await db.commit()
    sa = await get_service_account(db, sid)
    assert sa is not None
    return sa


async def get_service_account(db: Database, sa_id: str) -> dict[str, Any] | None:
    row = await db.fetchone(
        """SELECT id, name, org_id, team_id, created_by, created_at, updated_at, deleted_at
           FROM service_accounts WHERE id = ? AND deleted_at IS NULL""",
        (sa_id,),
    )
    return dict(row) if row else None


async def get_service_account_with_counts(db: Database, sa_id: str) -> dict[str, Any] | None:
    row = await db.fetchone(
        """SELECT sa.id, sa.name, sa.org_id, sa.team_id, sa.created_by, sa.created_at, sa.updated_at, sa.deleted_at,
                  (SELECT COUNT(*) FROM api_keys k WHERE k.service_account_id = sa.id AND k.deleted_at IS NULL) AS key_count
           FROM service_accounts sa WHERE sa.id = ? AND sa.deleted_at IS NULL""",
        (sa_id,),
    )
    return dict(row) if row else None


async def list_service_accounts_with_counts(
    db: Database, org_id: str, created_by: str, cursor: str, limit: int, include_deleted: bool
) -> list[dict[str, Any]]:
    deleted_clause = "" if include_deleted else "AND sa.deleted_at IS NULL"
    params: list[Any] = [org_id]
    creator_clause = ""
    if created_by:
        creator_clause = "AND sa.created_by = ?"
        params.append(created_by)
    cursor_clause = ""
    if cursor:
        cursor_clause = "AND sa.id > ?"
        params.append(cursor)
    params.append(limit)
    rows = await db.fetchall(
        f"""SELECT sa.id, sa.name, sa.org_id, sa.team_id, sa.created_by, sa.created_at, sa.updated_at, sa.deleted_at,
                   (SELECT COUNT(*) FROM api_keys k WHERE k.service_account_id = sa.id AND k.deleted_at IS NULL) AS key_count
            FROM service_accounts sa
            WHERE sa.org_id = ? {creator_clause} {deleted_clause} {cursor_clause}
            ORDER BY sa.id LIMIT ?""",
        tuple(params),
    )
    return [dict(r) for r in rows]


async def update_service_account(db: Database, sa_id: str, name: str | None) -> dict[str, Any]:
    if name is not None:
        cur = await db.execute(
            "UPDATE service_accounts SET name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND deleted_at IS NULL",
            (name, sa_id),
        )
        await db.commit()
        if cur.rowcount == 0:
            raise NotFoundError(sa_id)
    sa = await get_service_account_with_counts(db, sa_id)
    if not sa:
        raise NotFoundError(sa_id)
    return sa


async def delete_service_account(db: Database, sa_id: str) -> None:
    cur = await db.execute(
        "UPDATE service_accounts SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND deleted_at IS NULL",
        (sa_id,),
    )
    await db.commit()
    if cur.rowcount == 0:
        raise NotFoundError(sa_id)


async def revoke_user_sessions(db: Database, user_id: str) -> None:
    await db.execute(
        """UPDATE api_keys SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
           WHERE user_id = ? AND key_type = 'session_key' AND deleted_at IS NULL""",
        (user_id,),
    )
    await db.commit()


async def create_api_key(db: Database, params: dict[str, Any]) -> dict[str, Any]:
    kid = new_uuid()
    await db.execute(
        """INSERT INTO api_keys (id, key_hash, key_hint, key_type, name, org_id, team_id, user_id,
                                 service_account_id, daily_token_limit, monthly_token_limit,
                                 requests_per_minute, requests_per_day, expires_at, created_by,
                                 created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
        (
            kid, params["key_hash"], params["key_hint"], params["key_type"], params["name"],
            params["org_id"], params.get("team_id"), params.get("user_id"),
            params.get("service_account_id"), params.get("daily_token_limit", 0),
            params.get("monthly_token_limit", 0), params.get("requests_per_minute", 0),
            params.get("requests_per_day", 0), params.get("expires_at"), params["created_by"],
        ),
    )
    await db.commit()
    key = await get_api_key(db, kid)
    assert key is not None
    return key


async def get_api_key(db: Database, key_id: str) -> dict[str, Any] | None:
    row = await db.fetchone(
        """SELECT id, key_hash, key_hint, key_type, name, org_id, team_id, user_id, service_account_id,
                  daily_token_limit, monthly_token_limit, requests_per_minute, requests_per_day,
                  expires_at, last_used_at, created_by, created_at, updated_at, deleted_at
           FROM api_keys WHERE id = ? AND deleted_at IS NULL""",
        (key_id,),
    )
    return dict(row) if row else None


async def list_api_keys(
    db: Database, org_id: str, cursor: str, limit: int, include_deleted: bool
) -> list[dict[str, Any]]:
    deleted_clause = "" if include_deleted else "AND deleted_at IS NULL"
    params: list[Any] = [org_id]
    cursor_clause = ""
    if cursor:
        cursor_clause = "AND id > ?"
        params.append(cursor)
    params.append(limit)
    rows = await db.fetchall(
        f"""SELECT id, key_hint, key_type, name, org_id, team_id, user_id, service_account_id,
                   daily_token_limit, monthly_token_limit, requests_per_minute, requests_per_day,
                   expires_at, last_used_at, created_by, created_at, updated_at
            FROM api_keys WHERE org_id = ? {deleted_clause} {cursor_clause}
            ORDER BY id LIMIT ?""",
        tuple(params),
    )
    return [dict(r) for r in rows]


async def update_api_key(db: Database, key_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    if fields:
        sets = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values()) + [key_id]
        cur = await db.execute(
            f"UPDATE api_keys SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND deleted_at IS NULL",
            tuple(vals),
        )
        await db.commit()
        if cur.rowcount == 0:
            raise NotFoundError(key_id)
    key = await get_api_key(db, key_id)
    if not key:
        raise NotFoundError(key_id)
    return key


async def delete_api_key(db: Database, key_id: str) -> None:
    cur = await db.execute(
        "UPDATE api_keys SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND deleted_at IS NULL",
        (key_id,),
    )
    await db.commit()
    if cur.rowcount == 0:
        raise NotFoundError(key_id)


async def create_invite_token(db: Database, params: dict[str, Any]) -> dict[str, Any]:
    iid = new_uuid()
    await db.execute(
        """INSERT INTO invite_tokens (id, token_hash, token_hint, org_id, email, role, expires_at, created_by, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
        (iid, params["token_hash"], params["token_hint"], params["org_id"],
         params["email"], params["role"], params["expires_at"], params["created_by"]),
    )
    await db.commit()
    row = await db.fetchone("SELECT * FROM invite_tokens WHERE id = ?", (iid,))
    return dict(row) if row else {}


async def list_invite_tokens(db: Database, org_id: str, cursor: str, limit: int) -> list[dict[str, Any]]:
    params: list[Any] = [org_id]
    cursor_clause = ""
    if cursor:
        cursor_clause = "AND id > ?"
        params.append(cursor)
    params.append(limit)
    rows = await db.fetchall(
        f"""SELECT id, token_hint, org_id, email, role, expires_at, redeemed_at, created_by, created_at
            FROM invite_tokens WHERE org_id = ? {cursor_clause} ORDER BY id LIMIT ?""",
        tuple(params),
    )
    return [dict(r) for r in rows]


async def revoke_invite_token(db: Database, invite_id: str, org_id: str) -> None:
    cur = await db.execute(
        "DELETE FROM invite_tokens WHERE id = ? AND org_id = ?", (invite_id, org_id)
    )
    await db.commit()
    if cur.rowcount == 0:
        raise NotFoundError(invite_id)


async def revoke_invite_tokens_by_email(db: Database, org_id: str, email: str) -> None:
    await db.execute(
        "DELETE FROM invite_tokens WHERE org_id = ? AND email = ? AND redeemed_at IS NULL",
        (org_id, email),
    )
    await db.commit()


async def get_invite_token_by_hash(db: Database, token_hash: str) -> dict[str, Any] | None:
    row = await db.fetchone(
        "SELECT * FROM invite_tokens WHERE token_hash = ?", (token_hash,)
    )
    return dict(row) if row else None


async def redeem_invite_token(db: Database, invite_id: str) -> None:
    cur = await db.execute(
        "UPDATE invite_tokens SET redeemed_at = CURRENT_TIMESTAMP WHERE id = ? AND redeemed_at IS NULL",
        (invite_id,),
    )
    await db.commit()
    if cur.rowcount == 0:
        raise NotFoundError(invite_id)


async def load_all_active_keys(db: Database) -> list[dict[str, Any]]:
    rows = await db.fetchall(
        """SELECT k.id, k.key_hash, k.key_type, k.name, k.org_id, k.team_id, k.user_id, k.service_account_id,
                  k.daily_token_limit, k.monthly_token_limit, k.requests_per_minute, k.requests_per_day,
                  k.expires_at,
                  o.daily_token_limit AS org_daily_token_limit,
                  o.monthly_token_limit AS org_monthly_token_limit,
                  o.requests_per_minute AS org_requests_per_minute,
                  o.requests_per_day AS org_requests_per_day,
                  t.daily_token_limit AS team_daily_token_limit,
                  t.monthly_token_limit AS team_monthly_token_limit,
                  t.requests_per_minute AS team_requests_per_minute,
                  t.requests_per_day AS team_requests_per_day,
                  u.is_system_admin, om.role AS membership_role
           FROM api_keys k
           JOIN organizations o ON o.id = k.org_id
           LEFT JOIN teams t ON t.id = k.team_id
           LEFT JOIN users u ON u.id = k.user_id
           LEFT JOIN org_memberships om ON om.user_id = k.user_id AND om.org_id = k.org_id
           WHERE k.deleted_at IS NULL"""
    )
    return [dict(r) for r in rows]


async def get_setting(db: Database, key: str) -> str | None:
    row = await db.fetchone("SELECT value FROM settings WHERE key = ?", (key,))
    return row["value"] if row else None


async def set_setting(db: Database, key: str, value: str) -> None:
    await db.execute(
        """INSERT INTO settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP""",
        (key, value),
    )
    await db.commit()


async def get_org_model_access(db: Database, org_id: str) -> list[str]:
    rows = await db.fetchall(
        "SELECT model_name FROM org_model_access WHERE org_id = ? ORDER BY model_name", (org_id,)
    )
    return [r["model_name"] for r in rows]


async def set_org_model_access(db: Database, org_id: str, models: list[str]) -> None:
    async with db.transaction() as conn:
        await conn.execute("DELETE FROM org_model_access WHERE org_id = ?", (org_id,))
        for m in models:
            await conn.execute(
                "INSERT INTO org_model_access (id, org_id, model_name) VALUES (?, ?, ?)",
                (new_uuid(), org_id, m),
            )


async def get_team_model_access(db: Database, team_id: str) -> list[str]:
    rows = await db.fetchall(
        "SELECT model_name FROM team_model_access WHERE team_id = ? ORDER BY model_name", (team_id,)
    )
    return [r["model_name"] for r in rows]


async def set_team_model_access(db: Database, team_id: str, models: list[str]) -> None:
    async with db.transaction() as conn:
        await conn.execute("DELETE FROM team_model_access WHERE team_id = ?", (team_id,))
        for m in models:
            await conn.execute(
                "INSERT INTO team_model_access (id, team_id, model_name) VALUES (?, ?, ?)",
                (new_uuid(), team_id, m),
            )


async def get_key_model_access(db: Database, key_id: str) -> list[str]:
    rows = await db.fetchall(
        "SELECT model_name FROM key_model_access WHERE key_id = ? ORDER BY model_name", (key_id,)
    )
    return [r["model_name"] for r in rows]


async def set_key_model_access(db: Database, key_id: str, models: list[str]) -> None:
    async with db.transaction() as conn:
        await conn.execute("DELETE FROM key_model_access WHERE key_id = ?", (key_id,))
        for m in models:
            await conn.execute(
                "INSERT INTO key_model_access (id, key_id, model_name) VALUES (?, ?, ?)",
                (new_uuid(), key_id, m),
            )


async def count_active_keys(db: Database, org_id: str) -> int:
    row = await db.fetchone(
        "SELECT COUNT(*) AS c FROM api_keys WHERE org_id = ? AND deleted_at IS NULL", (org_id,)
    )
    return int(row["c"]) if row else 0


async def count_org_members(db: Database, org_id: str) -> int:
    row = await db.fetchone(
        "SELECT COUNT(*) AS c FROM org_memberships WHERE org_id = ?", (org_id,)
    )
    return int(row["c"]) if row else 0


async def count_team_keys(db: Database, team_id: str) -> int:
    row = await db.fetchone(
        "SELECT COUNT(*) AS c FROM api_keys WHERE team_id = ? AND deleted_at IS NULL", (team_id,)
    )
    return int(row["c"]) if row else 0


async def count_team_members(db: Database, team_id: str) -> int:
    row = await db.fetchone(
        "SELECT COUNT(*) AS c FROM team_memberships WHERE team_id = ?", (team_id,)
    )
    return int(row["c"]) if row else 0


async def count_user_keys(db: Database, org_id: str, user_id: str) -> int:
    row = await db.fetchone(
        "SELECT COUNT(*) AS c FROM api_keys WHERE org_id = ? AND user_id = ? AND deleted_at IS NULL",
        (org_id, user_id),
    )
    return int(row["c"]) if row else 0


async def get_user_team_id(db: Database, org_id: str, user_id: str) -> str:
    row = await db.fetchone(
        """SELECT t.id FROM teams t
           JOIN team_memberships tm ON tm.team_id = t.id
           WHERE t.org_id = ? AND tm.user_id = ? AND t.deleted_at IS NULL LIMIT 1""",
        (org_id, user_id),
    )
    return row["id"] if row else ""


async def get_hourly_usage_totals(
    db: Database, org_id: str, team_id: str, user_id: str, from_iso: str
) -> dict[str, Any]:
    clauses = ["org_id = ?", "timestamp >= ?"]
    params: list[Any] = [org_id, from_iso]
    if team_id:
        clauses.append("team_id = ?")
        params.append(team_id)
    if user_id:
        clauses.append("user_id = ?")
        params.append(user_id)
    where = " AND ".join(clauses)
    row = await db.fetchone(
        f"""SELECT COALESCE(SUM(request_count), 0) AS total_requests,
                   COALESCE(SUM(total_tokens), 0) AS total_tokens,
                   COALESCE(SUM(cost_estimate), 0) AS cost_estimate
            FROM usage_hourly WHERE {where}""",
        tuple(params),
    )
    return dict(row) if row else {"total_requests": 0, "total_tokens": 0, "cost_estimate": 0.0}


async def get_scoped_usage_aggregates(
    db: Database, org_id: str, team_id: str, user_id: str,
    from_iso: str, to_iso: str, group_by: str,
) -> list[dict[str, Any]]:
    group_col = {
        "model": "model_name", "team": "team_id", "key": "key_id",
        "user": "user_id", "day": "date(timestamp)", "hour": "strftime('%Y-%m-%dT%H:00:00+00:00', timestamp)",
    }.get(group_by, "model_name")
    clauses = ["org_id = ?", "timestamp >= ?", "timestamp < ?"]
    params: list[Any] = [org_id, from_iso, to_iso]
    if team_id:
        clauses.append("team_id = ?")
        params.append(team_id)
    if user_id:
        clauses.append("user_id = ?")
        params.append(user_id)
    where = " AND ".join(clauses)
    rows = await db.fetchall(
        f"""SELECT {group_col} AS group_key,
                   COUNT(*) AS total_requests,
                   COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                   COALESCE(SUM(total_tokens), 0) AS total_tokens,
                   COALESCE(SUM(cost_estimate), 0) AS cost_estimate,
                   COALESCE(AVG(duration_ms), 0) AS avg_duration_ms
            FROM usage_events WHERE {where}
            GROUP BY {group_col} ORDER BY group_key""",
        tuple(params),
    )
    return [dict(r) for r in rows]


async def get_monthly_token_usage(db: Database, org_id: str) -> int:
    row = await db.fetchone(
        """SELECT COALESCE(SUM(total_tokens), 0) AS t FROM usage_events
           WHERE org_id = ? AND timestamp >= datetime('now', 'start of month')""",
        (org_id,),
    )
    return int(row["t"]) if row else 0


async def list_audit_logs(db: Database, filters: dict[str, Any], limit: int) -> tuple[list[dict], bool]:
    clauses = ["1=1"]
    params: list[Any] = []
    if filters.get("org_id"):
        clauses.append("org_id = ?")
        params.append(filters["org_id"])
    if filters.get("actor_id"):
        clauses.append("actor_id = ?")
        params.append(filters["actor_id"])
    if filters.get("resource_type"):
        clauses.append("resource_type = ?")
        params.append(filters["resource_type"])
    if filters.get("action"):
        clauses.append("action = ?")
        params.append(filters["action"])
    if filters.get("from"):
        clauses.append("timestamp >= ?")
        params.append(filters["from"])
    if filters.get("to"):
        clauses.append("timestamp <= ?")
        params.append(filters["to"])
    if filters.get("cursor"):
        clauses.append("id < ?")
        params.append(filters["cursor"])
    params.append(limit + 1)
    where = " AND ".join(clauses)
    rows = await db.fetchall(
        f"""SELECT id, timestamp, org_id, actor_id, actor_type, actor_key_id, action,
                   resource_type, resource_id, description, ip_address, status_code, request_id
            FROM audit_logs WHERE {where} ORDER BY timestamp DESC, id DESC LIMIT ?""",
        tuple(params),
    )
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]
    return [dict(r) for r in rows], has_more
