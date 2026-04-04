import sqlite3
from contextlib import contextmanager
from typing import Iterator

import pandas as pd

from spending_tracker.config import get_settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS statements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    file_name TEXT NOT NULL,
    file_hash TEXT NOT NULL UNIQUE,
    uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(account_id) REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS merchant_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_key TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    statement_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    txn_date TEXT NOT NULL,
    description TEXT NOT NULL,
    merchant_key TEXT NOT NULL,
    amount REAL NOT NULL,
    direction TEXT NOT NULL,
    category TEXT,
    source TEXT NOT NULL,
    raw_line TEXT NOT NULL,
    confidence REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(account_id, txn_date, description, amount),
    FOREIGN KEY(statement_id) REFERENCES statements(id),
    FOREIGN KEY(account_id) REFERENCES accounts(id)
);
"""


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    db_path = get_settings().database_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(SCHEMA)


def get_or_create_account(account_name: str) -> int:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM accounts WHERE name = ?",
            (account_name,),
        ).fetchone()
        if row:
            return int(row["id"])

        cursor = conn.execute(
            "INSERT INTO accounts(name) VALUES (?)",
            (account_name,),
        )
        return int(cursor.lastrowid)


def insert_statement(account_id: int, file_name: str, file_hash: str) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO statements(account_id, file_name, file_hash)
            VALUES (?, ?, ?)
            """,
            (account_id, file_name, file_hash),
        )
        return int(cursor.lastrowid)


def statement_exists(file_hash: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM statements WHERE file_hash = ?",
            (file_hash,),
        ).fetchone()
        return row is not None


def list_statements() -> pd.DataFrame:
    with get_connection() as conn:
        df = pd.read_sql_query(
            """
            SELECT
                s.id,
                a.name AS account,
                s.file_name,
                s.file_hash,
                s.uploaded_at,
                COUNT(t.id) AS transaction_count
            FROM statements s
            JOIN accounts a ON a.id = s.account_id
            LEFT JOIN transactions t ON t.statement_id = s.id
            GROUP BY s.id, a.name, s.file_name, s.file_hash, s.uploaded_at
            ORDER BY s.uploaded_at DESC, s.id DESC
            """,
            conn,
        )
    return df


def list_statement_transactions() -> pd.DataFrame:
    with get_connection() as conn:
        df = pd.read_sql_query(
            """
            SELECT
                s.id AS statement_id,
                s.file_name,
                s.uploaded_at,
                a.name AS account,
                t.id,
                t.txn_date,
                t.description,
                t.amount,
                t.direction,
                COALESCE(t.category, 'Needs Review') AS category,
                t.source,
                t.confidence,
                t.raw_line
            FROM transactions t
            JOIN statements s ON s.id = t.statement_id
            JOIN accounts a ON a.id = t.account_id
            ORDER BY s.uploaded_at DESC, s.id DESC, t.txn_date DESC, t.id DESC
            """,
            conn,
        )

    if df.empty:
        return df

    df["txn_date"] = pd.to_datetime(df["txn_date"])
    df["signed_amount"] = df.apply(
        lambda row: -abs(row["amount"]) if row["direction"] == "debit" else abs(row["amount"]),
        axis=1,
    )
    return df


def delete_statement(statement_id: int) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM statements WHERE id = ?",
            (statement_id,),
        ).fetchone()
        if row is None:
            return False

        conn.execute(
            "DELETE FROM transactions WHERE statement_id = ?",
            (statement_id,),
        )
        conn.execute(
            "DELETE FROM statements WHERE id = ?",
            (statement_id,),
        )
        conn.execute(
            """
            DELETE FROM accounts
            WHERE id NOT IN (SELECT DISTINCT account_id FROM statements)
            """
        )
        return True


def delete_all_statements() -> int:
    with get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) AS count FROM statements").fetchone()["count"]
        conn.execute("DELETE FROM transactions")
        conn.execute("DELETE FROM statements")
        conn.execute(
            """
            DELETE FROM accounts
            WHERE id NOT IN (SELECT DISTINCT account_id FROM statements)
            """
        )
    return int(count)


def save_transactions(rows: list[dict]) -> int:
    inserted = 0
    with get_connection() as conn:
        for row in rows:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO transactions(
                    statement_id,
                    account_id,
                    txn_date,
                    description,
                    merchant_key,
                    amount,
                    direction,
                    category,
                    source,
                    raw_line,
                    confidence
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["statement_id"],
                    row["account_id"],
                    row["txn_date"],
                    row["description"],
                    row["merchant_key"],
                    row["amount"],
                    row["direction"],
                    row["category"],
                    row["source"],
                    row["raw_line"],
                    row["confidence"],
                ),
            )
            inserted += cursor.rowcount
    return inserted


def upsert_mapping(merchant_key: str, category: str, transaction_source: str = "user_mapping") -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO merchant_mappings(merchant_key, category)
            VALUES (?, ?)
            ON CONFLICT(merchant_key)
            DO UPDATE SET category = excluded.category
            """,
            (merchant_key, category),
        )
        conn.execute(
            """
            UPDATE transactions
            SET category = ?, source = ?, confidence = 1.0
            WHERE merchant_key = ?
            """,
            (category, transaction_source, merchant_key),
        )


def get_mapping(merchant_key: str) -> str | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT category FROM merchant_mappings WHERE merchant_key = ?",
            (merchant_key,),
        ).fetchone()
        return None if row is None else str(row["category"])


def load_transactions() -> pd.DataFrame:
    with get_connection() as conn:
        df = pd.read_sql_query(
            """
            SELECT
                t.id,
                a.name AS account,
                t.txn_date,
                t.description,
                t.merchant_key,
                t.amount,
                t.direction,
                COALESCE(t.category, 'Needs Review') AS category,
                t.source,
                t.confidence,
                t.raw_line
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            ORDER BY t.txn_date DESC, t.id DESC
            """,
            conn,
        )

    if df.empty:
        return df

    df["txn_date"] = pd.to_datetime(df["txn_date"])
    df["year"] = df["txn_date"].dt.year
    df["month"] = df["txn_date"].dt.to_period("M").astype(str)
    df["day"] = df["txn_date"].dt.date.astype(str)
    df["signed_amount"] = df.apply(
        lambda row: -abs(row["amount"]) if row["direction"] == "debit" else abs(row["amount"]),
        axis=1,
    )
    return df


def get_accounts() -> list[str]:
    with get_connection() as conn:
        rows = conn.execute("SELECT name FROM accounts ORDER BY name").fetchall()
    return [str(row["name"]) for row in rows]


def get_categories() -> list[str]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT category
            FROM transactions
            WHERE category IS NOT NULL
            ORDER BY category
            """
        ).fetchall()
    return [str(row["category"]) for row in rows]


def get_uncategorized() -> pd.DataFrame:
    with get_connection() as conn:
        df = pd.read_sql_query(
            """
            SELECT
                id,
                description,
                merchant_key,
                amount,
                direction,
                txn_date,
                raw_line,
                COALESCE(category, 'Needs Review') AS category
            FROM transactions
            WHERE category IS NULL OR category = 'Needs Review'
            ORDER BY txn_date DESC, id DESC
            """,
            conn,
        )
    if not df.empty:
        df["txn_date"] = pd.to_datetime(df["txn_date"])
    return df


def list_merchants() -> pd.DataFrame:
    with get_connection() as conn:
        df = pd.read_sql_query(
            """
            WITH merchant_stats AS (
                SELECT
                    t.merchant_key,
                    MIN(t.description) AS sample_description,
                    COUNT(*) AS transaction_count,
                    SUM(CASE WHEN t.direction = 'debit' THEN t.amount ELSE 0 END) AS debit_total,
                    SUM(CASE WHEN t.direction = 'credit' THEN t.amount ELSE 0 END) AS credit_total,
                    MAX(t.txn_date) AS latest_txn_date,
                    COALESCE(MAX(m.category), MAX(t.category), 'Needs Review') AS category,
                    CASE WHEN MAX(m.category) IS NULL THEN 0 ELSE 1 END AS has_mapping
                FROM transactions t
                LEFT JOIN merchant_mappings m ON m.merchant_key = t.merchant_key
                GROUP BY t.merchant_key
            )
            SELECT
                merchant_key,
                sample_description,
                transaction_count,
                debit_total,
                credit_total,
                latest_txn_date,
                category,
                has_mapping
            FROM merchant_stats
            ORDER BY transaction_count DESC, latest_txn_date DESC, merchant_key ASC
            """,
            conn,
        )

    if not df.empty:
        df["latest_txn_date"] = pd.to_datetime(df["latest_txn_date"])
    return df


def update_transaction_category(
    transaction_id: int,
    category: str | None,
    source: str,
    confidence: float | None,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE transactions
            SET category = ?, source = ?, confidence = ?
            WHERE id = ?
            """,
            (category, source, confidence, transaction_id),
        )
