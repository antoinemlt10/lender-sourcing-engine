"""SQLite persistence for scored accounts.

One table, keyed by company name. The full Account is stored as JSON in the
`data` column; `segment` and `final_score` are duplicated as plain columns so
the database is easy to inspect with any SQLite browser.
"""

from __future__ import annotations

import json
import sqlite3
from types import TracebackType

from lender_engine.models import Account


class AccountStore:
    def __init__(self, path: str = "lenders.db"):
        self._conn = sqlite3.connect(path)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                name TEXT PRIMARY KEY,
                segment TEXT,
                final_score INTEGER,
                data TEXT
            )
            """
        )
        self._conn.commit()

    def upsert(self, account: Account) -> None:
        self._conn.execute(
            """
            INSERT INTO accounts (name, segment, final_score, data)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                segment = excluded.segment,
                final_score = excluded.final_score,
                data = excluded.data
            """,
            (account.name, account.segment, account.final_score, json.dumps(account.to_dict())),
        )
        self._conn.commit()

    def all_accounts(self) -> list[Account]:
        rows = self._conn.execute(
            "SELECT data FROM accounts ORDER BY final_score DESC"
        ).fetchall()
        return [Account.from_dict(json.loads(row[0])) for row in rows]

    def get(self, name: str) -> Account | None:
        row = self._conn.execute(
            "SELECT data FROM accounts WHERE name = ?", (name,)
        ).fetchone()
        return Account.from_dict(json.loads(row[0])) if row else None

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "AccountStore":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
