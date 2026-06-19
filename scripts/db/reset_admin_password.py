"""Reset admin password (dev helper)."""
from __future__ import annotations

import asyncio
import sys

import bcrypt

from wai.config import load
from wai.db.connection import Database


async def main() -> None:
    email = sys.argv[1] if len(sys.argv) > 1 else "admin@wai.local"
    password = sys.argv[2] if len(sys.argv) > 2 else "WaiAdmin123!"
    cfg, _ = load("wai.yaml")
    db = Database(cfg.database.driver, cfg.database.dsn)
    await db.connect()
    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    await db.execute(
        "UPDATE users SET password_hash = ? WHERE email = ?",
        (pw_hash, email),
    )
    print(f"Password reset for {email}")
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
