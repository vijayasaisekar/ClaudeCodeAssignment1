"""
Pure I/O loaders for the three heterogeneous raw sources described in
`data_dictionary.md`. No feature logic belongs here — only loading and basic
type coercion, so ingestion can be unit-tested and swapped independently of
`transforms.py`.
"""

import sqlite3
from contextlib import closing
from pathlib import Path

import pandas as pd


def load_customers(path: str = "data/customers.csv") -> pd.DataFrame:
    """Load customers.csv: one row per customer, label column included (not used by features)."""
    customers = pd.read_csv(path)
    customers["signup_date"] = pd.to_datetime(customers["signup_date"])
    return customers


def load_transactions(path: str = "data/transactions.db") -> pd.DataFrame:
    """Load the row-level `transactions` table from the SQLite database.

    SQLite stores txn_timestamp as ISO-8601 text, so it is cast to a real datetime here.
    The full row-level frame is returned — aggregation happens in transforms.py.
    """
    with closing(sqlite3.connect(path)) as conn:
        transactions = pd.read_sql(
            "SELECT customer_id, txn_timestamp, category, channel, amount, is_returned "
            "FROM transactions",
            conn,
        )
    transactions["txn_timestamp"] = pd.to_datetime(transactions["txn_timestamp"])
    transactions["is_returned"] = transactions["is_returned"].astype("int64")
    return transactions


def load_monthly_agg(path: str = "data/transactions_monthly_agg.parquet") -> pd.DataFrame:
    """Load the pre-aggregated customer x month parquet extract, unmodified.

    Customer-months with no activity have no row in this file.
    """
    monthly_agg = pd.read_parquet(Path(path))
    monthly_agg["txn_month"] = pd.to_datetime(monthly_agg["txn_month"])
    return monthly_agg
