from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd
import streamlit as st

from config import DATA_DIR, DB_PATH
from transform import add_derived_columns


MARGIN_CONCEPT_COLUMNS = {
    "Comisión Cambio Modelo Contado": "Margen Cambio Modelo Contado",
    "Comisión venta de unidades 1ra. parte": "Margen Venta 1ra parte",
    "Comisión venta de unidades 2da. parte": "Margen Venta 2da parte",
}


class PostgresConnection:
    def __init__(self, url: str):
        import psycopg2
        import psycopg2.extras

        self._conn = psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)

    def execute(self, sql: str, params: Iterable | None = None):
        cursor = self._conn.cursor()
        cursor.execute(_postgres_sql(sql), tuple(params or ()))
        return cursor

    def executemany(self, sql: str, seq_of_params: Iterable[Iterable]):
        cursor = self._conn.cursor()
        cursor.executemany(_postgres_sql(sql), [tuple(params) for params in seq_of_params])
        return cursor

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


def get_connection(db_path: Path = DB_PATH):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    database_url = _database_url()
    if database_url:
        conn = PostgresConnection(database_url)
    else:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
    init_db(conn)
    backfill_derived_fields(conn)
    prune_txt_records_to_plan_channel(conn)
    consolidate_txt_records_by_key(conn)
    return conn


def _database_url() -> str:
    try:
        secrets_url = st.secrets.get("DATABASE_URL", "")
    except Exception:
        secrets_url = ""
    return secrets_url or os.getenv("DATABASE_URL", "")


def _postgres_sql(sql: str) -> str:
    return (
        sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
        .replace("datetime('now')", "CURRENT_TIMESTAMP")
        .replace("?", "%s")
    )


def _read_sql(conn, sql: str) -> pd.DataFrame:
    rows = conn.execute(sql).fetchall()
    return pd.DataFrame([dict(row) for row in rows])


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS records (
            record_key TEXT PRIMARY KEY,
            fecha TEXT,
            factura TEXT,
            matricula TEXT,
            importe REAL,
            cliente TEXT,
            producto TEXT,
            row_hash TEXT NOT NULL,
            data_json TEXT NOT NULL,
            source_file TEXT,
            first_imported_at TEXT NOT NULL,
            last_imported_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS imports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_file TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            total_rows INTEGER NOT NULL,
            inserted_rows INTEGER NOT NULL,
            updated_rows INTEGER NOT NULL,
            unchanged_rows INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS txt_records (
            record_key TEXT PRIMARY KEY,
            row_hash TEXT NOT NULL,
            data_json TEXT NOT NULL,
            source_file TEXT,
            first_imported_at TEXT NOT NULL,
            last_imported_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS txt_imports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_file TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            total_rows INTEGER NOT NULL,
            inserted_rows INTEGER NOT NULL,
            updated_rows INTEGER NOT NULL,
            unchanged_rows INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS margin_records (
            margin_key TEXT PRIMARY KEY,
            data_json TEXT NOT NULL,
            source_file TEXT,
            first_imported_at TEXT NOT NULL,
            last_imported_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cuenta_h_records (
            record_key TEXT PRIMARY KEY,
            row_hash TEXT NOT NULL,
            data_json TEXT NOT NULL,
            source_file TEXT,
            first_imported_at TEXT NOT NULL,
            last_imported_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cuenta_h_imports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_file TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            total_rows INTEGER NOT NULL,
            inserted_rows INTEGER NOT NULL,
            updated_rows INTEGER NOT NULL,
            unchanged_rows INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS subscription_records (
            record_key TEXT PRIMARY KEY,
            row_hash TEXT NOT NULL,
            data_json TEXT NOT NULL,
            source_file TEXT,
            first_imported_at TEXT NOT NULL,
            last_imported_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS subscription_imports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_file TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            total_rows INTEGER NOT NULL,
            inserted_rows INTEGER NOT NULL,
            updated_rows INTEGER NOT NULL,
            unchanged_rows INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS subscription_objectives (
            periodo TEXT PRIMARY KEY,
            objetivo INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def load_records(conn: sqlite3.Connection) -> pd.DataFrame:
    rows = conn.execute("SELECT * FROM records").fetchall()
    if not rows:
        return pd.DataFrame()

    decoded = []
    for row in rows:
        base = dict(row)
        data = json.loads(base.pop("data_json") or "{}")
        decoded.append({**data, **base})
    return add_derived_columns(pd.DataFrame(decoded))


def load_imports(conn: sqlite3.Connection) -> pd.DataFrame:
    return _read_sql(conn, "SELECT * FROM imports ORDER BY imported_at DESC, id DESC")


def load_txt_records(conn: sqlite3.Connection) -> pd.DataFrame:
    prune_txt_records_to_plan_channel(conn)
    consolidate_txt_records_by_key(conn)
    rows = conn.execute("SELECT * FROM txt_records").fetchall()
    if not rows:
        return pd.DataFrame()

    decoded = []
    for row in rows:
        base = dict(row)
        data = json.loads(base.pop("data_json") or "{}")
        decoded.append({**data, **base})
    return pd.DataFrame(decoded)


def load_txt_imports(conn: sqlite3.Connection) -> pd.DataFrame:
    return _read_sql(conn, "SELECT * FROM txt_imports ORDER BY imported_at DESC, id DESC")


def load_margin_records(conn: sqlite3.Connection) -> pd.DataFrame:
    rows = conn.execute("SELECT * FROM margin_records").fetchall()
    if not rows:
        return pd.DataFrame()

    decoded = []
    for row in rows:
        base = dict(row)
        data = json.loads(base.pop("data_json") or "{}")
        decoded.append({**data, **base})
    return pd.DataFrame(decoded)


def load_cuenta_h_records(conn: sqlite3.Connection) -> pd.DataFrame:
    rows = conn.execute("SELECT * FROM cuenta_h_records").fetchall()
    if not rows:
        return pd.DataFrame()

    decoded = []
    for row in rows:
        base = dict(row)
        data = json.loads(base.pop("data_json") or "{}")
        decoded.append({**data, **base})
    return pd.DataFrame(decoded)


def load_cuenta_h_imports(conn: sqlite3.Connection) -> pd.DataFrame:
    return _read_sql(conn, "SELECT * FROM cuenta_h_imports ORDER BY imported_at DESC, id DESC")


def load_subscription_records(conn: sqlite3.Connection) -> pd.DataFrame:
    rows = conn.execute("SELECT * FROM subscription_records").fetchall()
    if not rows:
        return pd.DataFrame()

    decoded = []
    for row in rows:
        base = dict(row)
        data = json.loads(base.pop("data_json") or "{}")
        decoded.append({**data, **base})
    return pd.DataFrame(decoded)


def load_subscription_imports(conn: sqlite3.Connection) -> pd.DataFrame:
    return _read_sql(conn, "SELECT * FROM subscription_imports ORDER BY imported_at DESC, id DESC")


def load_subscription_objectives(conn: sqlite3.Connection) -> pd.DataFrame:
    return _read_sql(conn, "SELECT * FROM subscription_objectives ORDER BY periodo DESC")


def save_subscription_objective(conn: sqlite3.Connection, periodo: str, objetivo: int) -> None:
    now = datetime.utcnow().isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO subscription_objectives (periodo, objetivo, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(periodo) DO UPDATE SET objetivo = excluded.objetivo, updated_at = excluded.updated_at
        """,
        (periodo, int(objetivo), now),
    )
    conn.commit()


def upsert_subscription_records(
    conn: sqlite3.Connection,
    df: pd.DataFrame,
    source_file: str,
    key_columns: Iterable[str],
) -> dict[str, int]:
    now = datetime.utcnow().isoformat(timespec="seconds")
    inserted = updated = unchanged = 0
    key_columns = list(key_columns)

    for _, row in df.iterrows():
        row_dict = _clean_row(row.to_dict())
        record_key = make_record_key(row_dict, key_columns)
        row_hash = str(pd.util.hash_pandas_object(pd.Series(row_dict), index=True).sum())
        existing = conn.execute(
            "SELECT data_json, row_hash FROM subscription_records WHERE record_key = ?",
            (record_key,),
        ).fetchone()

        if existing is None:
            conn.execute(
                """
                INSERT INTO subscription_records (
                    record_key, row_hash, data_json, source_file, first_imported_at, last_imported_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (record_key, row_hash, json.dumps(row_dict, ensure_ascii=False, default=str), source_file, now, now),
            )
            inserted += 1
            continue

        merged = _merge_rows(json.loads(existing["data_json"]), row_dict)
        merged_hash = str(pd.util.hash_pandas_object(pd.Series(merged), index=True).sum())
        if merged_hash == existing["row_hash"]:
            unchanged += 1
            continue

        conn.execute(
            """
            UPDATE subscription_records
            SET row_hash = ?, data_json = ?, source_file = ?, last_imported_at = ?
            WHERE record_key = ?
            """,
            (merged_hash, json.dumps(merged, ensure_ascii=False, default=str), source_file, now, record_key),
        )
        updated += 1

    conn.execute(
        """
        INSERT INTO subscription_imports (
            source_file, imported_at, total_rows, inserted_rows, updated_rows, unchanged_rows
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (source_file, now, len(df), inserted, updated, unchanged),
    )
    conn.commit()

    return {
        "total": len(df),
        "inserted": inserted,
        "updated": updated,
        "unchanged": unchanged,
    }


def upsert_cuenta_h_records(
    conn: sqlite3.Connection,
    df: pd.DataFrame,
    source_file: str,
    key_columns: Iterable[str],
) -> dict[str, int]:
    now = datetime.utcnow().isoformat(timespec="seconds")
    inserted = updated = unchanged = 0
    key_columns = list(key_columns)

    for _, row in df.iterrows():
        row_dict = _clean_row(row.to_dict())
        record_key = make_record_key(row_dict, key_columns)
        row_hash = str(pd.util.hash_pandas_object(pd.Series(row_dict), index=True).sum())

        existing = conn.execute(
            "SELECT data_json, row_hash FROM cuenta_h_records WHERE record_key = ?",
            (record_key,),
        ).fetchone()

        if existing is None:
            conn.execute(
                """
                INSERT INTO cuenta_h_records (
                    record_key, row_hash, data_json, source_file, first_imported_at, last_imported_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    record_key,
                    row_hash,
                    json.dumps(row_dict, ensure_ascii=False, default=str),
                    source_file,
                    now,
                    now,
                ),
            )
            inserted += 1
            continue

        merged = _merge_rows(json.loads(existing["data_json"]), row_dict)
        merged_hash = str(pd.util.hash_pandas_object(pd.Series(merged), index=True).sum())
        if merged_hash == existing["row_hash"]:
            unchanged += 1
            continue

        conn.execute(
            """
            UPDATE cuenta_h_records
            SET row_hash = ?, data_json = ?, source_file = ?, last_imported_at = ?
            WHERE record_key = ?
            """,
            (
                merged_hash,
                json.dumps(merged, ensure_ascii=False, default=str),
                source_file,
                now,
                record_key,
            ),
        )
        updated += 1

    conn.execute(
        """
        INSERT INTO cuenta_h_imports (
            source_file, imported_at, total_rows, inserted_rows, updated_rows, unchanged_rows
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (source_file, now, len(df), inserted, updated, unchanged),
    )
    conn.commit()

    return {
        "total": len(df),
        "inserted": inserted,
        "updated": updated,
        "unchanged": unchanged,
    }


def upsert_txt_records(
    conn: sqlite3.Connection,
    df: pd.DataFrame,
    source_file: str,
    key_columns: Iterable[str],
) -> dict[str, int]:
    now = datetime.utcnow().isoformat(timespec="seconds")
    inserted = updated = unchanged = skipped = 0
    key_columns = ["Pedido ABCnet"] if "Pedido ABCnet" in df.columns else list(key_columns)

    for _, row in df.iterrows():
        row_dict = _clean_row(row.to_dict())
        if not _is_plan_savings_channel(row_dict):
            skipped += 1
            continue

        record_key = make_record_key(row_dict, key_columns)
        row_hash = str(pd.util.hash_pandas_object(pd.Series(row_dict), index=True).sum())

        existing = conn.execute(
            "SELECT data_json, row_hash FROM txt_records WHERE record_key = ?",
            (record_key,),
        ).fetchone()

        if existing is None:
            conn.execute(
                """
                INSERT INTO txt_records (
                    record_key, row_hash, data_json, source_file, first_imported_at, last_imported_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    record_key,
                    row_hash,
                    json.dumps(row_dict, ensure_ascii=False, default=str),
                    source_file,
                    now,
                    now,
                ),
            )
            inserted += 1
            continue

        merged = _merge_rows(json.loads(existing["data_json"]), row_dict)
        merged_hash = str(pd.util.hash_pandas_object(pd.Series(merged), index=True).sum())

        if merged_hash == existing["row_hash"]:
            unchanged += 1
            continue

        conn.execute(
            """
            UPDATE txt_records
            SET row_hash = ?, data_json = ?, source_file = ?, last_imported_at = ?
            WHERE record_key = ?
            """,
            (
                merged_hash,
                json.dumps(merged, ensure_ascii=False, default=str),
                source_file,
                now,
                record_key,
            ),
        )
        updated += 1

    conn.execute(
        """
        INSERT INTO txt_imports (
            source_file, imported_at, total_rows, inserted_rows, updated_rows, unchanged_rows
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (source_file, now, len(df), inserted, updated, unchanged),
    )
    consolidated = consolidate_txt_records_by_key(conn, commit=False)
    removed_non_plan = prune_txt_records_to_plan_channel(conn, commit=False)
    conn.commit()

    return {
        "total": len(df),
        "inserted": inserted,
        "updated": updated,
        "unchanged": unchanged,
        "skipped": skipped,
        "consolidated": consolidated,
        "removed_non_plan": removed_non_plan,
    }


def prune_txt_records_to_plan_channel(conn: sqlite3.Connection, commit: bool = True) -> int:
    rows = conn.execute("SELECT record_key, data_json FROM txt_records").fetchall()
    delete_keys = []

    for row in rows:
        data = json.loads(row["data_json"] or "{}")
        if not _is_plan_savings_channel(data):
            delete_keys.append((row["record_key"],))

    if not delete_keys:
        return 0

    conn.executemany("DELETE FROM txt_records WHERE record_key = ?", delete_keys)
    if commit:
        conn.commit()
    return len(delete_keys)


def consolidate_txt_records_by_key(
    conn: sqlite3.Connection,
    key_column: str = "Pedido ABCnet",
    commit: bool = True,
) -> int:
    rows = conn.execute(
        """
        SELECT record_key, data_json, row_hash, source_file, first_imported_at, last_imported_at
        FROM txt_records
        """
    ).fetchall()
    grouped: dict[str, list[sqlite3.Row]] = {}

    for row in rows:
        data = json.loads(row["data_json"] or "{}")
        group_key = _normalize_key(data.get(key_column))
        if not group_key:
            continue
        grouped.setdefault(group_key, []).append(row)

    consolidated = 0
    changed = False
    for group_key, group_rows in grouped.items():
        if len(group_rows) <= 1 and group_rows[0]["record_key"] == group_key:
            continue

        ordered_rows = sorted(
            group_rows,
            key=lambda row: (
                _row_completeness(json.loads(row["data_json"] or "{}")),
                _as_text(row["last_imported_at"]),
            ),
        )
        merged_data: dict = {}
        for row in ordered_rows:
            merged_data = _merge_rows(merged_data, json.loads(row["data_json"] or "{}"))

        row_hash = str(pd.util.hash_pandas_object(pd.Series(merged_data), index=True).sum())
        first_imported_at = min(_as_text(row["first_imported_at"]) for row in group_rows)
        last_imported_at = max(_as_text(row["last_imported_at"]) for row in group_rows)
        latest_row = max(group_rows, key=lambda row: _as_text(row["last_imported_at"]))
        source_file = _as_text(latest_row["source_file"])

        conn.executemany(
            "DELETE FROM txt_records WHERE record_key = ?",
            [(row["record_key"],) for row in group_rows],
        )
        conn.execute(
            """
            INSERT INTO txt_records (
                record_key, row_hash, data_json, source_file, first_imported_at, last_imported_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                group_key,
                row_hash,
                json.dumps(merged_data, ensure_ascii=False, default=str),
                source_file,
                first_imported_at,
                last_imported_at,
            ),
        )
        consolidated += len(group_rows) - 1
        changed = True

    if commit and changed:
        conn.commit()
    return consolidated


def apply_txt_margins(conn: sqlite3.Connection, margins_df: pd.DataFrame, source_file: str) -> dict[str, int]:
    now = datetime.utcnow().isoformat(timespec="seconds")
    stored_margins = _upsert_margin_records(conn, margins_df, source_file, now)
    rows = conn.execute("SELECT record_key, data_json, row_hash FROM txt_records").fetchall()
    margin_lookup: dict[tuple[str, str], list[dict]] = {}
    for _, margin_row in margins_df.iterrows():
        key = (_normalize_key(margin_row.get("Grupo margen")), _normalize_order(margin_row.get("Orden margen")))
        margin_lookup.setdefault(key, []).append(margin_row.to_dict())

    matched_rows = updated = unchanged = 0
    matched_margins = 0

    for row in rows:
        data = json.loads(row["data_json"] or "{}")
        key = (_normalize_key(data.get("Grupo")), _normalize_order(data.get("Orden")))
        margins = margin_lookup.get(key, [])
        if not margins:
            continue

        matched_rows += 1
        matched_margins += len(margins)
        enriched = data.copy()
        concepts = set(_split_margin_concepts(enriched.get("Concepto margen")))
        margin_sources = set(_split_margin_concepts(enriched.get("Archivo margen")))

        for margin in margins:
            concept = margin.get("Concepto margen")
            amount = _as_float(margin.get("Importe margen")) or 0
            concept_column = MARGIN_CONCEPT_COLUMNS.get(str(concept))
            if concept_column:
                enriched[concept_column] = amount
            concepts.add(str(concept))
            margin_sources.add(source_file)
            enriched["Contrato margen"] = margin.get("Contrato margen")
            enriched["Fecha margen"] = margin.get("Fecha margen")
            enriched["Suscripcion margen"] = margin.get("Suscripcion margen")
            enriched["Cuota margen"] = margin.get("Cuota margen")

        total_margin = sum(_as_float(enriched.get(column)) or 0 for column in MARGIN_CONCEPT_COLUMNS.values())
        enriched["Margen total"] = total_margin
        enriched["Concepto margen"] = " | ".join(sorted(concept for concept in concepts if concept and concept != "None"))
        enriched["Importe margen"] = total_margin
        enriched["Archivo margen"] = " | ".join(sorted(source for source in margin_sources if source and source != "None"))
        enriched_hash = str(pd.util.hash_pandas_object(pd.Series(enriched), index=True).sum())

        if enriched_hash == row["row_hash"]:
            unchanged += 1
            continue

        conn.execute(
            """
            UPDATE txt_records
            SET row_hash = ?, data_json = ?, last_imported_at = ?
            WHERE record_key = ?
            """,
            (
                enriched_hash,
                json.dumps(enriched, ensure_ascii=False, default=str),
                now,
                row["record_key"],
            ),
        )
        updated += 1

    conn.commit()
    return {
        "margins": len(margins_df),
        "stored_margins": stored_margins,
        "matched": matched_rows,
        "matched_margins": matched_margins,
        "updated": updated,
        "unchanged": unchanged,
        "unmatched": max(len(margins_df) - matched_margins, 0),
    }


def _upsert_margin_records(
    conn: sqlite3.Connection,
    margins_df: pd.DataFrame,
    source_file: str,
    imported_at: str,
) -> int:
    stored = 0
    for _, row in margins_df.iterrows():
        row_dict = _clean_row(row.to_dict())
        margin_key = make_record_key(
            row_dict,
            ["Contrato margen", "Concepto margen", "Fecha margen", "Importe margen"],
        )
        existing = conn.execute(
            "SELECT data_json FROM margin_records WHERE margin_key = ?",
            (margin_key,),
        ).fetchone()

        if existing is None:
            conn.execute(
                """
                INSERT INTO margin_records (
                    margin_key, data_json, source_file, first_imported_at, last_imported_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    margin_key,
                    json.dumps(row_dict, ensure_ascii=False, default=str),
                    source_file,
                    imported_at,
                    imported_at,
                ),
            )
            stored += 1
            continue

        merged = _merge_rows(json.loads(existing["data_json"]), row_dict)
        conn.execute(
            """
            UPDATE margin_records
            SET data_json = ?, source_file = ?, last_imported_at = ?
            WHERE margin_key = ?
            """,
            (
                json.dumps(merged, ensure_ascii=False, default=str),
                source_file,
                imported_at,
                margin_key,
            ),
        )
        stored += 1
    return stored


def backfill_derived_fields(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT record_key, data_json, row_hash FROM records").fetchall()
    updated = 0

    for row in rows:
        data = json.loads(row["data_json"] or "{}")
        enriched = add_derived_columns(pd.DataFrame([data])).iloc[0].to_dict()

        if (
            data.get("marca") == enriched.get("marca")
            and data.get("tipo_operacion") == enriched.get("tipo_operacion")
            and data.get("fecha_matriculacion") == enriched.get("fecha_matriculacion")
        ):
            continue

        data["marca"] = enriched.get("marca")
        data["tipo_operacion"] = enriched.get("tipo_operacion")
        data["fecha_matriculacion"] = enriched.get("fecha_matriculacion")
        if data.get("fecha_matriculacion"):
            data["fecha"] = data.get("fecha_matriculacion")
        row_hash = str(pd.util.hash_pandas_object(pd.Series(data), index=True).sum())

        conn.execute(
            """
            UPDATE records
            SET data_json = ?, row_hash = ?, last_imported_at = datetime('now')
            WHERE record_key = ?
            """,
            (
                json.dumps(data, ensure_ascii=False, default=str),
                row_hash,
                row["record_key"],
            ),
        )
        updated += 1

    if updated:
        conn.commit()

    return {"updated": updated, "total": len(rows)}


def upsert_records(
    conn: sqlite3.Connection,
    df: pd.DataFrame,
    source_file: str,
    key_columns: Iterable[str],
) -> dict[str, int]:
    now = datetime.utcnow().isoformat(timespec="seconds")
    inserted = updated = unchanged = 0
    key_columns = list(key_columns)

    for _, row in df.iterrows():
        row_dict = _clean_row(row.to_dict())
        record_key = make_record_key(row_dict, key_columns)
        row_hash = pd.util.hash_pandas_object(pd.Series(row_dict), index=True).sum()
        row_hash = str(row_hash)

        existing = conn.execute(
            "SELECT data_json, row_hash FROM records WHERE record_key = ?",
            (record_key,),
        ).fetchone()

        if existing is None:
            conn.execute(
                """
                INSERT INTO records (
                    record_key, fecha, factura, matricula, importe, cliente, producto,
                    row_hash, data_json, source_file, first_imported_at, last_imported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _record_values(record_key, row_dict, row_hash, source_file, now, now),
            )
            inserted += 1
            continue

        merged = _merge_rows(json.loads(existing["data_json"]), row_dict)
        merged_hash = pd.util.hash_pandas_object(pd.Series(merged), index=True).sum()
        merged_hash = str(merged_hash)

        if merged_hash == existing["row_hash"]:
            unchanged += 1
            continue

        conn.execute(
            """
            UPDATE records
            SET fecha = ?, factura = ?, matricula = ?, importe = ?, cliente = ?,
                producto = ?, row_hash = ?, data_json = ?, source_file = ?,
                last_imported_at = ?
            WHERE record_key = ?
            """,
            (
                _as_text(merged.get("fecha")),
                _as_text(merged.get("factura")),
                _as_text(merged.get("matricula")),
                _as_float(merged.get("importe")),
                _as_text(merged.get("cliente")),
                _as_text(merged.get("producto")),
                merged_hash,
                json.dumps(merged, ensure_ascii=False, default=str),
                source_file,
                now,
                record_key,
            ),
        )
        updated += 1

    conn.execute(
        """
        INSERT INTO imports (
            source_file, imported_at, total_rows, inserted_rows, updated_rows, unchanged_rows
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (source_file, now, len(df), inserted, updated, unchanged),
    )
    conn.commit()

    return {
        "total": len(df),
        "inserted": inserted,
        "updated": updated,
        "unchanged": unchanged,
    }


def make_record_key(row: dict, key_columns: Iterable[str]) -> str:
    values = [_as_text(row.get(column)).strip().upper() for column in key_columns]
    values = [value for value in values if value]
    if values:
        return " | ".join(values)
    return str(pd.util.hash_pandas_object(pd.Series(row), index=True).sum())


def _record_values(
    record_key: str,
    row_dict: dict,
    row_hash: str,
    source_file: str,
    first_imported_at: str,
    last_imported_at: str,
) -> tuple:
    return (
        record_key,
        _as_text(row_dict.get("fecha_matriculacion") or row_dict.get("fecha")),
        _as_text(row_dict.get("factura")),
        _as_text(row_dict.get("matricula")),
        _as_float(row_dict.get("importe")),
        _as_text(row_dict.get("cliente")),
        _as_text(row_dict.get("producto")),
        row_hash,
        json.dumps(row_dict, ensure_ascii=False, default=str),
        source_file,
        first_imported_at,
        last_imported_at,
    )


def _merge_rows(existing: dict, incoming: dict) -> dict:
    merged = existing.copy()
    for key, value in incoming.items():
        if _is_empty(value):
            continue
        if _is_empty(merged.get(key)) or merged.get(key) != value:
            merged[key] = value
    return merged


def _clean_row(row: dict) -> dict:
    return {key: (None if _is_empty(value) else value) for key, value in row.items()}


def _row_completeness(row: dict) -> int:
    return sum(0 if _is_empty(value) else 1 for value in row.values())


def _is_plan_savings_channel(row: dict) -> bool:
    channel = _as_text(row.get("Canal Vta.") or row.get("Canal Vta") or row.get("Canal Venta"))
    normalized = channel.upper()
    return "PLAN" in normalized and "AHORRO" in normalized


def _is_empty(value) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return str(value).strip() == ""


def _as_text(value) -> str:
    if _is_empty(value):
        return ""
    return str(value)


def _as_float(value) -> float | None:
    if _is_empty(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        text = str(value).replace("$", "").replace(" ", "")
        if "," in text and "." in text:
            if text.rfind(".") > text.rfind(","):
                text = text.replace(",", "")
            else:
                text = text.replace(".", "").replace(",", ".")
        elif "," in text:
            text = text.replace(",", ".")
        return float(text)
    except ValueError:
        return None


def _normalize_key(value) -> str:
    if _is_empty(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return re_sub_digits(text)


def _normalize_order(value) -> str:
    text = _normalize_key(value)
    return text.zfill(3) if text else ""


def re_sub_digits(value: str) -> str:
    return "".join(char for char in value if char.isdigit())


def _split_margin_concepts(value) -> list[str]:
    if _is_empty(value):
        return []
    return [item.strip() for item in str(value).split("|") if item.strip()]
