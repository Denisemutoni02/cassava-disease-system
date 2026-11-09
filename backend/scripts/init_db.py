"""Create database tables from SQLAlchemy metadata.

For production PostgreSQL with PostGIS, prefer the canonical DDL:
    psql -U cassava -d cassava -f app/db/schema.sql

This script is a quick bootstrap for dev/test (also creates SQLite for tests).
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import init_db  # noqa: E402


async def main() -> None:
    await init_db()
    print("Database schema created/verified.")


if __name__ == "__main__":
    asyncio.run(main())
