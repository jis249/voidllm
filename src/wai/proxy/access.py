"""In-memory alias and model access caches for the proxy hot path."""

from __future__ import annotations

import threading


def _to_set_map(in_map: dict[str, list[str] | None]) -> dict[str, set[str] | None]:
    out: dict[str, set[str] | None] = {}
    for entity_id, names in in_map.items():
        if not names:
            out[entity_id] = None
        else:
            out[entity_id] = set(names)
    return out


class ModelAccessCache:
    """Org/team/key model allowlists — explicit allow with most-restrictive-wins."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._org: dict[str, set[str] | None] = {}
        self._team: dict[str, set[str] | None] = {}
        self._key: dict[str, set[str] | None] = {}

    def load(
        self,
        org_access: dict[str, list[str] | None],
        team_access: dict[str, list[str] | None],
        key_access: dict[str, list[str] | None],
    ) -> None:
        with self._lock:
            self._org = _to_set_map(org_access)
            self._team = _to_set_map(team_access)
            self._key = _to_set_map(key_access)

    def check(self, org_id: str, team_id: str, key_id: str, model_name: str) -> bool:
        """Return True only when model is explicitly allowed at org level and passes team/key filters."""
        with self._lock:
            org_set = self._org.get(org_id)
            if not org_set or model_name not in org_set:
                return False
            if team_id:
                team_set = self._team.get(team_id)
                if team_set and model_name not in team_set:
                    return False
            key_set = self._key.get(key_id)
            if key_set and model_name not in key_set:
                return False
            return True

    def len(self) -> int:
        with self._lock:
            return len(self._org) + len(self._team) + len(self._key)


class AliasCache:
    """Org/team scoped alias resolution — team checked before org."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._org: dict[str, dict[str, str]] = {}
        self._team: dict[str, dict[str, str]] = {}

    def load(
        self,
        org_aliases: dict[str, dict[str, str]],
        team_aliases: dict[str, dict[str, str]],
    ) -> None:
        with self._lock:
            self._org = org_aliases
            self._team = team_aliases

    def resolve(self, org_id: str, team_id: str, alias: str) -> tuple[str, bool]:
        with self._lock:
            if team_id and team_id in self._team:
                if canonical := self._team[team_id].get(alias):
                    return canonical, True
            if org_id in self._org:
                if canonical := self._org[org_id].get(alias):
                    return canonical, True
            return "", False

    def len(self) -> int:
        with self._lock:
            n = sum(len(v) for v in self._org.values())
            n += sum(len(v) for v in self._team.values())
            return n


async def reload_access_cache(db, cache: ModelAccessCache) -> None:
    org_rows = await db.fetchall("SELECT org_id, model_name FROM org_model_access")
    team_rows = await db.fetchall("SELECT team_id, model_name FROM team_model_access")
    key_rows = await db.fetchall("SELECT key_id, model_name FROM key_model_access")
    org: dict[str, list[str]] = {}
    team: dict[str, list[str]] = {}
    key: dict[str, list[str]] = {}
    for row in org_rows:
        org.setdefault(row["org_id"], []).append(row["model_name"])
    for row in team_rows:
        team.setdefault(row["team_id"], []).append(row["model_name"])
    for row in key_rows:
        key.setdefault(row["key_id"], []).append(row["model_name"])
    cache.load(org, team, key)


async def load_access_cache(db) -> ModelAccessCache:
    cache = ModelAccessCache()
    await reload_access_cache(db, cache)
    return cache


async def load_alias_cache(db) -> AliasCache:
    cache = AliasCache()
    rows = await db.fetchall(
        "SELECT alias, model_name, scope_type, org_id, team_id FROM model_aliases"
    )
    org: dict[str, dict[str, str]] = {}
    team: dict[str, dict[str, str]] = {}
    for row in rows:
        if row["scope_type"] == "team" and row["team_id"]:
            team.setdefault(row["team_id"], {})[row["alias"]] = row["model_name"]
        elif row["org_id"]:
            org.setdefault(row["org_id"], {})[row["alias"]] = row["model_name"]
    cache.load(org, team)
    return cache
