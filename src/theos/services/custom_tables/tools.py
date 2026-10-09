"""User-owned SQLite tables and parameterized query templates."""

import hashlib
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from harness import tool


def identifier(name: str) -> str:
    """Accept ordinary SQL identifiers before interpolation."""
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,62}", name):
        raise ValueError("Use a table or column name with letters, numbers, and underscores.")
    return '"' + name + '"'


def custom_tools(db, owner, directory: Path):
    """Keep custom SQL in a separate database with no application credentials."""
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / (hashlib.sha256(owner.encode()).hexdigest() + ".sqlite3")

    @contextmanager
    def connect():
        connection = sqlite3.connect(path)
        path.chmod(0o600)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @tool
    async def create_custom_table(
        name: str, columns: dict[str, Literal["TEXT", "INTEGER", "REAL", "BLOB"]]
    ):
        """Create a table in your private database."""
        if not 1 <= len(columns) <= 40:
            raise ValueError("Supply from 1 to 40 columns.")
        with connect() as conn:
            definition = ",".join(f"{identifier(k)} {v}" for k, v in columns.items())
            conn.execute(f"CREATE TABLE {identifier(name)} ({definition})")
        return {"created": name}

    @tool
    async def delete_custom_table(name: str):
        """Delete a table and its rows after confirmation."""
        with connect() as conn:
            conn.execute(f"DROP TABLE {identifier(name)}")
        return {"deleted": name}

    @tool
    async def create_query_template(name: str, sql: str):
        """Save one SELECT, INSERT, UPDATE, or DELETE statement with named parameters."""
        if len(sql) > 10000 or not re.match(r"^\s*(SELECT|INSERT|UPDATE|DELETE)\b", sql, re.I):
            raise ValueError("Use one SELECT, INSERT, UPDATE, or DELETE statement.")
        return db.put_record(owner, "query", name, {"sql": sql})

    @tool
    async def execute_query_template(name: str, parameters: dict):
        """Run a saved query with bound parameters in your private database."""
        query = db.record(owner, "query", name)["sql"]
        with connect() as conn:
            # The authorizer also blocks ATTACH, PRAGMA, schema writes, and extension loading.
            allowed = {
                sqlite3.SQLITE_SELECT,
                sqlite3.SQLITE_READ,
                sqlite3.SQLITE_INSERT,
                sqlite3.SQLITE_UPDATE,
                sqlite3.SQLITE_DELETE,
                sqlite3.SQLITE_TRANSACTION,
                sqlite3.SQLITE_FUNCTION,
            }

            def authorize(action, arg1, arg2, database, source):
                if action not in allowed or (
                    action == sqlite3.SQLITE_FUNCTION and arg2 == "load_extension"
                ):
                    return sqlite3.SQLITE_DENY
                if action in {
                    sqlite3.SQLITE_INSERT,
                    sqlite3.SQLITE_UPDATE,
                    sqlite3.SQLITE_DELETE,
                } and str(arg1).startswith("sqlite_"):
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK

            conn.set_authorizer(authorize)
            deadline = time.monotonic() + 2
            conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            cursor = conn.execute(query, parameters)
            if cursor.description:
                return {"rows": [dict(row) for row in cursor.fetchmany(500)], "limit": 500}
            return {"changed": cursor.rowcount}

    @tool
    async def list_custom_tables_and_templates():
        """List your tables and saved query templates."""
        with connect() as conn:
            tables = [
                dict(row)
                for row in conn.execute("SELECT name,sql FROM sqlite_master WHERE type='table'")
            ]
        return {"tables": tables, "templates": db.records(owner, "query")}

    return [
        create_custom_table,
        delete_custom_table,
        create_query_template,
        execute_query_template,
        list_custom_tables_and_templates,
    ]
