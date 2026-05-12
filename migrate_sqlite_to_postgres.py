from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import psycopg2
import psycopg2.extras

from config import DB_PATH
from storage import init_db


TABLES = {
    "records": "record_key",
    "imports": "id",
    "txt_records": "record_key",
    "txt_imports": "id",
    "margin_records": "margin_key",
    "cuenta_h_records": "record_key",
    "cuenta_h_imports": "id",
    "subscription_records": "record_key",
    "subscription_imports": "id",
    "subscription_objectives": "periodo",
    "subscription_brand_objectives": "objective_key",
}


class PostgresConnection:
    def __init__(self, url: str):
        self._conn = psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)

    def execute(self, sql: str, params=None):
        cursor = self._conn.cursor()
        cursor.execute(_postgres_sql(sql), tuple(params or ()))
        return cursor

    def executemany(self, sql: str, seq_of_params):
        cursor = self._conn.cursor()
        cursor.executemany(_postgres_sql(sql), [tuple(params) for params in seq_of_params])
        return cursor

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


def main() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("Falta DATABASE_URL. Pegala como variable de entorno antes de ejecutar la migracion.")

    sqlite_path = Path(os.getenv("SQLITE_PATH", DB_PATH))
    if not sqlite_path.exists():
        raise SystemExit(f"No encontre la base SQLite en {sqlite_path}")

    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row

    postgres_conn = PostgresConnection(database_url)
    init_db(postgres_conn)

    try:
        total = 0
        for table, primary_key in TABLES.items():
            copied = migrate_table(sqlite_conn, postgres_conn, table, primary_key)
            total += copied
            print(f"{table}: {copied} filas migradas")

        postgres_conn.commit()
        print(f"Migracion finalizada. Total migrado: {total} filas.")
    finally:
        sqlite_conn.close()
        postgres_conn.close()


def migrate_table(sqlite_conn: sqlite3.Connection, postgres_conn: PostgresConnection, table: str, primary_key: str) -> int:
    rows = sqlite_conn.execute(f"SELECT * FROM {table}").fetchall()
    if not rows:
        return 0

    columns = rows[0].keys()
    quoted_columns = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    update_columns = [column for column in columns if column != primary_key]
    update_sql = ", ".join(f"{column} = EXCLUDED.{column}" for column in update_columns)
    sql = f"""
        INSERT INTO {table} ({quoted_columns})
        VALUES ({placeholders})
        ON CONFLICT ({primary_key}) DO UPDATE SET {update_sql}
    """
    postgres_conn.executemany(sql, ([row[column] for column in columns] for row in rows))
    return len(rows)


def _postgres_sql(sql: str) -> str:
    return (
        sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
        .replace("datetime('now')", "CURRENT_TIMESTAMP")
        .replace("?", "%s")
    )


if __name__ == "__main__":
    main()
