"""Additive column migrations for tables the ORM created before new columns existed.

SQLAlchemy's create_all never alters existing tables, so each additive column added to a
model is also listed here and applied with ALTER TABLE ... ADD COLUMN at startup (the same
pattern as reservoir_live.ensure_schema). Safe to run repeatedly.
"""
from sqlalchemy import text

EXTRA_COLUMNS = {
    "weather_cache": {
        "provider": "VARCHAR(16) DEFAULT 'open_meteo'",
        "provider_fallback": "BOOLEAN DEFAULT 0",
    },
    "reservoirs": {
        "fetched_at": "DATETIME",
    },
}


async def ensure_extra_columns(db) -> list[str]:
    """Add any missing column; returns the 'table.column' names it added."""
    added = []
    for table, cols in EXTRA_COLUMNS.items():
        existing = {row[1] for row in (await db.execute(text(f"PRAGMA table_info({table})"))).fetchall()}
        if not existing:
            continue   # table not created yet; create_all will include the column
        for name, ddl in cols.items():
            if name not in existing:
                await db.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                added.append(f"{table}.{name}")
    await db.commit()
    return added
