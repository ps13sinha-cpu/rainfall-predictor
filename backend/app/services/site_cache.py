"""Per-site layer cache for the hyperlocal engine, shared across workers.

Replaces the per-machine JSON files under backend/cache/hyperlocal/ with two tables in
riis.db so every uvicorn worker (and the scheduler) sees the same warm sites:

    site_cache(key TEXT, layer TEXT, payload TEXT, fetched_at REAL, PRIMARY KEY(key, layer))
    site_cache_locks(key TEXT, layer TEXT, locked_at REAL, expires REAL, PRIMARY KEY(key, layer))

Plain sqlite3 (synchronous) on purpose: every call is a few milliseconds, the engine's
old JSON reads were synchronous too, and keeping it free of SQLAlchemy means it can be
used from training scripts and tests without the async engine. WAL mode plus a short
busy timeout keeps concurrent workers from tripping over each other.

Legacy JSON files are imported the first time a site key is asked for and the table has
no rows for it, so sites warmed before the switch stay warm. The files are left in place.
"""
import json
import os
import sqlite3
import threading
import time

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
LEGACY_DIR = os.path.join(BACKEND_ROOT, "cache", "hyperlocal")

DB_PATH = None          # override (tests); None -> derived from settings.database_url
BUSY_TIMEOUT_S = 5.0
LOCK_TTL_S = 90.0       # a fetcher that has not finished in this long is assumed dead

_init_lock = threading.Lock()
_initialised = set()    # db paths whose schema has been ensured


def _path() -> str:
    if DB_PATH:
        return DB_PATH
    try:
        from app.config import settings
        url = settings.database_url
    except Exception:
        url = "sqlite+aiosqlite:///./riis.db"
    if "sqlite" not in url:
        return os.path.join(BACKEND_ROOT, "riis.db")
    path = url.split("///", 1)[-1] if "///" in url else "./riis.db"
    # aiosqlite resolves a relative path against the working directory; match it so the
    # cache lives in the same file as the rest of the app's tables
    return os.path.abspath(path)


def _connect() -> sqlite3.Connection:
    path = _path()
    conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT_S, isolation_level=None)  # autocommit; explicit BEGIN below
    if path not in _initialised:
        with _init_lock:
            if path not in _initialised:
                try:
                    conn.execute("PRAGMA journal_mode=WAL")
                except sqlite3.Error:
                    pass
                conn.execute("""CREATE TABLE IF NOT EXISTS site_cache (
                                    key TEXT NOT NULL, layer TEXT NOT NULL, payload TEXT NOT NULL,
                                    fetched_at REAL NOT NULL, PRIMARY KEY (key, layer))""")
                conn.execute("""CREATE TABLE IF NOT EXISTS site_cache_locks (
                                    key TEXT NOT NULL, layer TEXT NOT NULL, locked_at REAL NOT NULL,
                                    expires REAL NOT NULL, PRIMARY KEY (key, layer))""")
                _initialised.add(path)
    conn.execute(f"PRAGMA busy_timeout={int(BUSY_TIMEOUT_S * 1000)}")
    return conn


# ── Layer rows ────────────────────────────────────────────────────────────────
def load_site(key: str) -> dict:
    """{layer: {"t": fetched_at, "v": payload}} for one site key (legacy JSON shape)."""
    try:
        with _connect() as conn:
            rows = conn.execute("SELECT layer, payload, fetched_at FROM site_cache WHERE key = ?", (key,)).fetchall()
    except sqlite3.Error as e:
        print(f"[RIIS-site-cache] read failed for {key}: {e}")
        return _load_legacy(key)
    if rows:
        out = {}
        for layer, payload, t in rows:
            try:
                out[layer] = {"t": float(t), "v": json.loads(payload)}
            except (ValueError, TypeError):
                continue
        return out
    legacy = _load_legacy(key)
    if legacy:
        save_site(key, {k: (v["t"], v["v"]) for k, v in legacy.items()})
        print(f"[RIIS-site-cache] imported legacy cache for {key} ({len(legacy)} layers)")
    return legacy


def save_layer(key: str, layer: str, payload, fetched_at: float | None = None) -> None:
    save_site(key, {layer: (fetched_at if fetched_at is not None else time.time(), payload)})


def save_site(key: str, store: dict) -> None:
    """Upsert every (layer -> (fetched_at, payload)) of a site in one transaction."""
    rows = []
    for layer, (t, v) in store.items():
        try:
            rows.append((key, layer, json.dumps(v, default=str), float(t)))
        except (TypeError, ValueError) as e:
            print(f"[RIIS-site-cache] skip {key}/{layer}: {e}")
    if not rows:
        return
    try:
        with _connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.executemany("INSERT OR REPLACE INTO site_cache (key, layer, payload, fetched_at) VALUES (?, ?, ?, ?)", rows)
            conn.execute("COMMIT")
    except sqlite3.Error as e:
        print(f"[RIIS-site-cache] write failed for {key}: {e}")


def delete_site(key: str) -> None:
    try:
        with _connect() as conn:
            conn.execute("DELETE FROM site_cache WHERE key = ?", (key,))
    except sqlite3.Error as e:
        print(f"[RIIS-site-cache] delete failed for {key}: {e}")


def _load_legacy(key: str) -> dict:
    try:
        with open(os.path.join(LEGACY_DIR, f"{key}.json")) as f:
            data = json.load(f)
        return {k: v for k, v in data.items() if isinstance(v, dict) and "t" in v and "v" in v}
    except Exception:
        return {}


# ── Fetch locks (one worker fetches, the others wait and read) ────────────────
def acquire_lock(key: str, layer: str, ttl_s: float = LOCK_TTL_S) -> bool:
    """True when this caller now holds the (key, layer) lock; False when another holder's
    lock has not expired. Expired locks are taken over."""
    now = time.time()
    try:
        with _connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT expires FROM site_cache_locks WHERE key = ? AND layer = ?", (key, layer)).fetchone()
            if row and row[0] > now:
                conn.execute("COMMIT")
                return False
            conn.execute("INSERT OR REPLACE INTO site_cache_locks (key, layer, locked_at, expires) VALUES (?, ?, ?, ?)",
                         (key, layer, now, now + ttl_s))
            conn.execute("COMMIT")
            return True
    except sqlite3.Error as e:
        print(f"[RIIS-site-cache] lock failed for {key}/{layer}: {e}")
        return True  # never block a fetch because the lock table is unavailable


def release_lock(key: str, layer: str) -> None:
    try:
        with _connect() as conn:
            conn.execute("DELETE FROM site_cache_locks WHERE key = ? AND layer = ?", (key, layer))
    except sqlite3.Error as e:
        print(f"[RIIS-site-cache] unlock failed for {key}/{layer}: {e}")


def lock_held(key: str, layer: str) -> bool:
    """True while another caller's unexpired lock exists."""
    try:
        with _connect() as conn:
            row = conn.execute("SELECT expires FROM site_cache_locks WHERE key = ? AND layer = ?", (key, layer)).fetchone()
        return bool(row and row[0] > time.time())
    except sqlite3.Error:
        return False


def stats() -> dict:
    try:
        with _connect() as conn:
            sites = conn.execute("SELECT COUNT(DISTINCT key) FROM site_cache").fetchone()[0]
            layers = conn.execute("SELECT COUNT(*) FROM site_cache").fetchone()[0]
            locks = conn.execute("SELECT COUNT(*) FROM site_cache_locks WHERE expires > ?", (time.time(),)).fetchone()[0]
        return {"db": _path(), "sites": sites, "layers": layers, "active_locks": locks}
    except sqlite3.Error as e:
        return {"db": _path(), "error": str(e)}
