from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import pymysql
from dotenv import load_dotenv
from pymysql.cursors import DictCursor


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SQLITE_PATH = ROOT_DIR / "web_logs" / "data" / "pumbot.db"
MYSQL_SCHEMA_PATH = ROOT_DIR / "web_logs" / "models_mysql.sql"

TABLES = [
    "users",
    "guild_members",
    "guild_member_name_history",
    "guild_messages",
    "roles",
    "guild_config",
    "birthdays",
    "bot_messages",
    "warnings",
    "counting_state",
    "counting_user_stats",
    "auto_publisher_channels",
    "selfrole_panels",
    "selfrole_mappings",
    "server_stats",
    "log_channels",
    "twitch_config",
    "tickets",
    "ticket_messages",
    "ticket_logs",
    "close_reasons",
]

TRUNCATE_ORDER = list(reversed(TABLES))


def sqlite_connect(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(f"SQLite-Datei nicht gefunden: {path}")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def mysql_connect(database: str | None = None):
    required = {
        "DB_HOST": os.getenv("DB_HOST", "127.0.0.1"),
        "DB_USER": os.getenv("DB_USER", ""),
        "DB_NAME": os.getenv("DB_NAME", ""),
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        raise RuntimeError(f"Fehlende ENV-Werte: {', '.join(missing)}")

    return pymysql.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", ""),
        password=os.getenv("DB_PASSWORD", ""),
        database=database or os.getenv("DB_NAME", ""),
        charset=os.getenv("DB_CHARSET", "utf8mb4"),
        cursorclass=DictCursor,
        autocommit=False,
    )


def ensure_mysql_schema(conn) -> None:
    sql = MYSQL_SCHEMA_PATH.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        for statement in sql.split(";"):
            statement = statement.strip()
            if not statement:
                continue
            try:
                cur.execute(statement)
            except pymysql.err.OperationalError as exc:
                if exc.args and exc.args[0] == 1061:
                    continue
                raise
    conn.commit()


def sqlite_tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row["name"] for row in rows}


def sqlite_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def mysql_columns(conn, table: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT COLUMN_NAME
               FROM INFORMATION_SCHEMA.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
               ORDER BY ORDINAL_POSITION""",
            (table,),
        )
        return [row["COLUMN_NAME"] for row in cur.fetchall()]


def normalize_value(value: Any) -> Any:
    if isinstance(value, str) and "T" in value and ":" in value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return value
    return value


def truncate_mysql_tables(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("SET FOREIGN_KEY_CHECKS = 0")
        for table in TRUNCATE_ORDER:
            cur.execute(f"TRUNCATE TABLE `{table}`")
        cur.execute("SET FOREIGN_KEY_CHECKS = 1")
    conn.commit()


def copy_table(
    sqlite_conn: sqlite3.Connection,
    mysql_conn,
    table: str,
    batch_size: int,
) -> int:
    source_columns = sqlite_columns(sqlite_conn, table)
    target_columns = mysql_columns(mysql_conn, table)
    columns = [column for column in source_columns if column in target_columns]
    if not columns:
        return 0

    quoted_columns = ", ".join(f"`{column}`" for column in columns)
    placeholders = ", ".join(["%s"] * len(columns))
    update_columns = [column for column in columns if column != "id"]
    if update_columns:
        updates = ", ".join(f"`{column}` = VALUES(`{column}`)" for column in update_columns)
        sql = (
            f"INSERT INTO `{table}` ({quoted_columns}) VALUES ({placeholders}) "
            f"ON DUPLICATE KEY UPDATE {updates}"
        )
    else:
        sql = f"INSERT IGNORE INTO `{table}` ({quoted_columns}) VALUES ({placeholders})"

    rows = sqlite_conn.execute(f"SELECT {quoted_columns} FROM `{table}`").fetchall()
    if not rows:
        return 0

    copied = 0
    with mysql_conn.cursor() as cur:
        batch: list[tuple[Any, ...]] = []
        for row in rows:
            batch.append(tuple(normalize_value(row[column]) for column in columns))
            if len(batch) >= batch_size:
                cur.executemany(sql, batch)
                copied += len(batch)
                batch.clear()
        if batch:
            cur.executemany(sql, batch)
            copied += len(batch)
    mysql_conn.commit()
    return copied


def reset_auto_increment(conn) -> None:
    with conn.cursor() as cur:
        for table in TABLES:
            columns = mysql_columns(conn, table)
            if "id" not in columns:
                continue
            cur.execute(f"SELECT COALESCE(MAX(`id`), 0) + 1 AS next_id FROM `{table}`")
            next_id = cur.fetchone()["next_id"]
            cur.execute(f"ALTER TABLE `{table}` AUTO_INCREMENT = %s", (next_id,))
    conn.commit()


def migrate_sqlite_to_mysql(
    sqlite_path: Path = DEFAULT_SQLITE_PATH,
    truncate: bool = False,
    batch_size: int = 1000,
) -> dict[str, Any]:
    load_dotenv(ROOT_DIR / ".env")

    sqlite_conn = sqlite_connect(sqlite_path)
    mysql_conn = mysql_connect()
    try:
        ensure_mysql_schema(mysql_conn)
        if truncate:
            truncate_mysql_tables(mysql_conn)

        existing_source_tables = sqlite_tables(sqlite_conn)
        tables: list[dict[str, Any]] = []
        total = 0
        for table in TABLES:
            if table not in existing_source_tables:
                tables.append({"table": table, "copied": 0, "skipped": True})
                continue
            copied = copy_table(sqlite_conn, mysql_conn, table, batch_size)
            total += copied
            tables.append({"table": table, "copied": copied, "skipped": False})

        reset_auto_increment(mysql_conn)
        return {
            "ok": True,
            "sqlite_path": str(sqlite_path),
            "truncate": truncate,
            "total": total,
            "tables": tables,
        }
    finally:
        mysql_conn.close()
        sqlite_conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migriert die lokale SQLite-Datei web_logs/data/pumbot.db nach MySQL/MariaDB."
    )
    parser.add_argument(
        "--sqlite",
        type=Path,
        default=DEFAULT_SQLITE_PATH,
        help=f"Pfad zur SQLite-Datei. Default: {DEFAULT_SQLITE_PATH}",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Leert die Zieltabellen vor der Migration.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Anzahl Datensaetze pro INSERT-Batch.",
    )
    args = parser.parse_args()

    result = migrate_sqlite_to_mysql(args.sqlite, args.truncate, args.batch_size)
    for table in result["tables"]:
        if table["skipped"]:
            print(f"{table['table']}: uebersprungen, Tabelle fehlt in SQLite")
        else:
            print(f"{table['table']}: {table['copied']} Zeilen migriert")
    print(f"Fertig. Insgesamt {result['total']} Zeilen migriert.")


if __name__ == "__main__":
    main()
