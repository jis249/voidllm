"""SQL dialect helpers for PostgreSQL."""

from __future__ import annotations

import re

INSERT_OR_IGNORE_RE = re.compile(
    r"INSERT\s+OR\s+IGNORE\s+INTO\s+(\w+)\s*\(([^)]+)\)\s*VALUES\s*\(([^)]+)\)",
    re.IGNORECASE,
)

_INSERT_IGNORE_CONFLICT: dict[str, str] = {
    "mcp_tool_blocklist": "(server_id, tool_name)",
}


def qmark_to_dollar(sql: str) -> str:
    """Convert ? placeholders to $1, $2, ... (skip ? inside single-quoted strings)."""
    out: list[str] = []
    n = 0
    in_quote = False
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch == "'":
            if in_quote and i + 1 < len(sql) and sql[i + 1] == "'":
                out.append("''")
                i += 2
                continue
            in_quote = not in_quote
            out.append(ch)
        elif ch == "?" and not in_quote:
            n += 1
            out.append(f"${n}")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def adapt_sql(sql: str, driver: str) -> str:
    """Translate portable SQL placeholders and syntax for PostgreSQL."""
    if driver != "postgres":
        return sql

    def _replace_insert_or_ignore(match: re.Match[str]) -> str:
        table = match.group(1)
        cols = match.group(2)
        vals = match.group(3)
        conflict = _INSERT_IGNORE_CONFLICT.get(table.lower(), "")
        base = f"INSERT INTO {table} ({cols}) VALUES ({vals})"
        if conflict:
            return f"{base} ON CONFLICT {conflict} DO NOTHING"
        return f"{base} ON CONFLICT DO NOTHING"

    sql = INSERT_OR_IGNORE_RE.sub(_replace_insert_or_ignore, sql)
    sql = sql.replace("DEFAULT (CURRENT_TIMESTAMP)", "DEFAULT CURRENT_TIMESTAMP")
    return qmark_to_dollar(sql)


def _strip_sql_comments(sql: str) -> str:
    """Remove -- line comments (respect single-quoted strings)."""
    lines: list[str] = []
    for line in sql.splitlines():
        out: list[str] = []
        in_quote = False
        i = 0
        while i < len(line):
            ch = line[i]
            if ch == "'":
                if in_quote and i + 1 < len(line) and line[i + 1] == "'":
                    out.append("''")
                    i += 2
                    continue
                in_quote = not in_quote
                out.append(ch)
            elif not in_quote and line[i : i + 2] == "--":
                break
            else:
                out.append(ch)
            i += 1
        lines.append("".join(out))
    return "\n".join(lines)


def split_sql_script(sql: str) -> list[str]:
    """Split a migration script into individual statements."""
    cleaned = _strip_sql_comments(sql)
    statements: list[str] = []
    buf: list[str] = []
    in_quote = False
    i = 0
    while i < len(cleaned):
        ch = cleaned[i]
        if ch == "'":
            if in_quote and i + 1 < len(cleaned) and cleaned[i + 1] == "'":
                buf.append("''")
                i += 2
                continue
            in_quote = not in_quote
            buf.append(ch)
        elif ch == ";" and not in_quote:
            stmt = "".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
        else:
            buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements
