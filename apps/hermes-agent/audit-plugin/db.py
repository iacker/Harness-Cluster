import logging
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_DB_PATH: Path = Path(__file__).parent / "data" / "audit.db"
_BUSY_TIMEOUT: int = 5

logger = logging.getLogger("audit_to_db")


def _connect(timeout: int = _BUSY_TIMEOUT, path: Path | None = None) -> sqlite3.Connection:
    db_path = path or _DB_PATH
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path, timeout=timeout)
        return conn
    except Exception:
        logger.exception("Failed to open DB at %s", db_path)
        raise


def _migrate_llm_calls_to_api_calls(conn: sqlite3.Connection) -> None:
    has_old = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='llm_calls'"
    ).fetchone()
    has_new = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='api_calls'"
    ).fetchone()
    if has_old and not has_new:
        logger.info("Migrating legacy llm_calls table to api_calls")
        conn.execute("ALTER TABLE llm_calls RENAME TO api_calls")
        for idx in (
            "idx_llm_calls_session_time",
            "idx_llm_calls_provider_model_time",
            "idx_llm_calls_time",
        ):
            conn.execute(f"DROP INDEX IF EXISTS {idx}")


def init_db() -> None:
    try:
        conn = _connect()
        conn.execute("PRAGMA journal_mode=WAL")
        _migrate_llm_calls_to_api_calls(conn)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tool_calls (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT    NOT NULL,
                session_id  TEXT    NOT NULL,
                task_id     TEXT,
                tool_name   TEXT    NOT NULL,
                result      INTEGER NOT NULL,
                duration_ms INTEGER NOT NULL,
                arg_name    TEXT,
                arg_value   TEXT,
                error       TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS api_calls (
                id                        INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp                 TEXT    NOT NULL,
                session_id                TEXT    NOT NULL,
                task_id                   TEXT,
                provider                  TEXT,
                model                     TEXT,
                platform                  TEXT,
                finish_reason             TEXT,
                api_call_count            INTEGER NOT NULL DEFAULT 0,
                api_duration              REAL    NOT NULL DEFAULT 0.0,
                assistant_tool_call_count INTEGER NOT NULL DEFAULT 0,
                input_tokens              INTEGER NOT NULL DEFAULT 0,
                output_tokens             INTEGER NOT NULL DEFAULT 0,
                cache_read_tokens         INTEGER NOT NULL DEFAULT 0,
                cache_write_tokens        INTEGER NOT NULL DEFAULT 0,
                reasoning_tokens          INTEGER NOT NULL DEFAULT 0,
                prompt_tokens             INTEGER NOT NULL DEFAULT 0,
                total_tokens              INTEGER NOT NULL DEFAULT 0,
                request_count             INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tool_calls_session_time
            ON tool_calls (session_id, timestamp)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tool_calls_time
            ON tool_calls (timestamp)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_api_calls_session_time
            ON api_calls (session_id, timestamp)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_api_calls_provider_model_time
            ON api_calls (provider, model, timestamp)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_api_calls_time
            ON api_calls (timestamp)
        """)
        conn.commit()
        conn.close()
    except Exception:
        logger.exception("Failed to initialise database")
        raise


def insert_api_call(
    session_id: str,
    task_id: str | None,
    provider: str | None,
    model: str | None,
    api_call_count: int = 0,
    api_duration: float = 0.0,
    assistant_tool_call_count: int = 0,
    platform: str | None = None,
    finish_reason: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    reasoning_tokens: int = 0,
    prompt_tokens: int = 0,
    total_tokens: int = 0,
    request_count: int = 0,
) -> None:
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f') + 'Z'
    try:
        conn = _connect()
        conn.execute(
            "INSERT INTO api_calls"
            " (timestamp, session_id, task_id, provider, model, platform, finish_reason,"
            "  api_call_count, api_duration, assistant_tool_call_count,"
            "  input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,"
            "  reasoning_tokens, prompt_tokens, total_tokens, request_count)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (timestamp, session_id, task_id, provider, model, platform, finish_reason,
             api_call_count, api_duration, assistant_tool_call_count,
             input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
             reasoning_tokens, prompt_tokens, total_tokens, request_count),
        )
        conn.commit()
        conn.close()
    except Exception:
        logger.exception("Failed to insert API call for %s/%s", provider, model)
        raise


def prune(
    days: int | None = None,
    before: str | None = None,
    db_path: str | Path | None = None,
) -> int:
    """Delete entries older than `days` days or older than `before` (YYYY-MM-DD).

    Exactly one of `days` or `before` must be provided. `db_path` overrides the
    default module-relative DB location. Returns total rows deleted.
    """
    if (days is None) == (before is None):
        print("prune: provide exactly one of `days` or `before`", file=sys.stderr)
        raise ValueError("provide exactly one of `days` or `before`")

    if days is not None:
        if days < 0:
            print(f"prune: days must be >= 0, got {days}", file=sys.stderr)
            raise ValueError("days must be >= 0")
        cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff = cutoff_dt.strftime('%Y-%m-%dT%H:%M:%S.%f') + 'Z'
    else:
        try:
            datetime.strptime(before, '%Y-%m-%d')
        except ValueError:
            print(f"prune: invalid date {before!r}, expected YYYY-MM-DD", file=sys.stderr)
            raise
        cutoff = f"{before}T00:00:00.000000Z"

    target = Path(db_path) if db_path else _DB_PATH
    print(f"prune: using database {target}", flush=True)
    if not target.exists():
        print(f"prune: database file not found: {target}", file=sys.stderr)
        raise FileNotFoundError(target)
    try:
        conn = _connect(path=target)
        tool_deleted = conn.execute(
            "DELETE FROM tool_calls WHERE timestamp < ?", (cutoff,)
        ).rowcount
        llm_deleted = conn.execute(
            "DELETE FROM api_calls WHERE timestamp < ?", (cutoff,)
        ).rowcount
        conn.commit()
        conn.close()
    except Exception as e:
        print(
            f"prune: failed to delete entries older than {cutoff} from {target}: {e}",
            file=sys.stderr,
        )
        raise

    total = tool_deleted + llm_deleted
    print(
        f"prune: deleted {tool_deleted} tool_calls and {llm_deleted} api_calls "
        f"older than {cutoff} (total {total})"
    )
    return total


def insert_call(
    tool_name: str,
    result: int,
    session_id: str,
    duration_ms: int,
    task_id: str | None = None,
    arg_name: str | None = None,
    arg_value: str | None = None,
    error: str | None = None,
) -> None:
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f') + 'Z'
    try:
        conn = _connect()
        conn.execute(
            "INSERT INTO tool_calls"
            " (timestamp, session_id, task_id, tool_name, result, duration_ms, arg_name, arg_value, error)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (timestamp, session_id, task_id, tool_name, result, duration_ms, arg_name, arg_value, error),
        )
        conn.commit()
        conn.close()
    except Exception:
        logger.exception("Failed to insert call for tool %s", tool_name)
        raise
