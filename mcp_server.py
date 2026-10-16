"""
Model Context Protocol (MCP) Server for SQLite Sales Database.
Provides secure, read-only tools for schema inspection and query execution.
"""

import os
import re
import sqlite3
from typing import Any, Dict, List, Optional

try:
    import sqlparse
    from sqlparse.sql import Statement
    from sqlparse.tokens import Keyword, DML
    HAS_SQLPARSE = True
except ImportError:
    HAS_SQLPARSE = False


class SecurityViolationError(ValueError):
    """Raised when an unauthorized or potentially unsafe query is attempted."""
    pass


class MCPServer:
    """
    In-process MCP Server providing safe, read-only tools to interact with SQLite database.
    """

    def __init__(self, database_url: Optional[str] = None):
        if database_url is None:
            database_url = os.getenv("DATABASE_URL", "sqlite:///./data/sales.db")
        
        self.database_url = database_url
        self.db_path = self._resolve_db_path(database_url)

    def _resolve_db_path(self, url: str) -> str:
        """Extract and resolve the filesystem path from the database URL."""
        if url.startswith("sqlite:///"):
            path = url[len("sqlite:///"):]
        elif url.startswith("sqlite://"):
            path = url[len("sqlite://"):]
        else:
            path = url

        # Strip query parameters if present
        if "?" in path:
            path = path.split("?")[0]

        if not os.path.isabs(path):
            path = os.path.abspath(path)
        return path

    def _get_connection(self) -> sqlite3.Connection:
        """Get a read-only SQLite connection."""
        if not os.path.exists(self.db_path):
            raise FileNotFoundError(f"Database file not found at: {self.db_path}")

        # Open in read-only mode using SQLite URI
        uri = f"file:{self.db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        
        # Enforce SQLite engine-level read-only pragma
        try:
            conn.execute("PRAGMA query_only = ON;")
        except sqlite3.Error:
            pass

        return conn

    def list_tables(self) -> List[str]:
        """
        Tool 1: Returns a list of user table names in the database.
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name;
            """)
            tables = [row["name"] for row in cursor.fetchall()]
            return tables
        finally:
            conn.close()

    def describe_schema(self, table_name: str) -> Dict[str, Any]:
        """
        Tool 2: Returns the schema (column names, types, constraints, foreign keys) for a given table.
        """
        if not re.match(r"^[a-zA-Z0-9_]+$", table_name):
            raise ValueError(f"Invalid table name: {table_name}")

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT sql FROM sqlite_master 
                WHERE type='table' AND name = ?;
            """, (table_name,))
            table_row = cursor.fetchone()
            if not table_row:
                raise ValueError(f"Table '{table_name}' does not exist.")

            create_sql = table_row["sql"]

            cursor.execute(f"PRAGMA table_info({table_name});")
            columns_info = cursor.fetchall()

            cursor.execute(f"PRAGMA foreign_key_list({table_name});")
            fk_info = cursor.fetchall()

            columns = [
                {
                    "cid": col["cid"],
                    "name": col["name"],
                    "type": col["type"],
                    "notnull": bool(col["notnull"]),
                    "default_value": col["dflt_value"],
                    "pk": bool(col["pk"]),
                }
                for col in columns_info
            ]

            foreign_keys = [
                {
                    "from_column": fk["from"],
                    "to_table": fk["table"],
                    "to_column": fk["to"],
                }
                for fk in fk_info
            ]

            return {
                "table_name": table_name,
                "create_sql": create_sql,
                "columns": columns,
                "foreign_keys": foreign_keys,
            }
        finally:
            conn.close()

    def get_full_schema_context(self) -> str:
        """
        Convenience method to assemble complete schema context for all tables.
        Uses list_tables() and describe_schema() to avoid hardcoding.
        """
        tables = self.list_tables()
        schema_lines = []
        for table in tables:
            desc = self.describe_schema(table)
            schema_lines.append(f"Table: {table}")
            cols_str = ", ".join(
                [f"{c['name']} ({c['type']}{' PK' if c['pk'] else ''})" for c in desc["columns"]]
            )
            schema_lines.append(f"  Columns: {cols_str}")
            if desc["foreign_keys"]:
                fks_str = ", ".join(
                    [f"{fk['from_column']} -> {fk['to_table']}({fk['to_column']})" for fk in desc["foreign_keys"]]
                )
                schema_lines.append(f"  Foreign Keys: {fks_str}")
            schema_lines.append("")
        return "\n".join(schema_lines).strip()

    def _strip_comments_and_normalize(self, sql: str) -> str:
        """Strip SQL comments and leading/trailing whitespace."""
        # Strip single line comments --
        sql = re.sub(r"--[^\n]*", "", sql)
        # Strip multi-line comments /* ... */
        sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
        return sql.strip()

    def _validate_sql_security(self, sql: str) -> None:
        """
        Strictly enforce read-only SELECT queries.
        Rejects non-SELECT statements, multiple statements, and destructive commands.
        """
        if not sql or not sql.strip():
            raise SecurityViolationError("SQL query cannot be empty.")

        cleaned = self._strip_comments_and_normalize(sql)
        cleaned_no_semicolon = cleaned.rstrip(";")

        # Check for multiple statements separated by semicolons outside quotes
        # Split by semicolon ignoring quotes
        in_single_quote = False
        in_double_quote = False
        statement_count = 1
        for ch in cleaned_no_semicolon:
            if ch == "'" and not in_double_quote:
                in_single_quote = not in_single_quote
            elif ch == '"' and not in_single_quote:
                in_double_quote = not in_double_quote
            elif ch == ';' and not in_single_quote and not in_double_quote:
                statement_count += 1

        if statement_count > 1:
            raise SecurityViolationError("Multiple SQL statements in a single query are strictly forbidden.")

        forbidden_keywords = {
            "DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "CREATE", 
            "TRUNCATE", "REPLACE", "ATTACH", "DETACH", "PRAGMA", 
            "EXEC", "EXECUTE", "VACUUM", "GRANT", "REVOKE"
        }

        # Check with sqlparse if installed
        if HAS_SQLPARSE:
            parsed = sqlparse.parse(cleaned_no_semicolon)
            if len(parsed) == 0:
                raise SecurityViolationError("No executable SQL statements found.")
            if len(parsed) > 1:
                raise SecurityViolationError("Multiple SQL statements in a single query are strictly forbidden.")

            stmt: Statement = parsed[0]
            stmt_type = stmt.get_type()

            if stmt_type != "SELECT":
                tokens = [t for t in stmt.tokens if not t.is_whitespace]
                if tokens and tokens[0].value.upper() == "WITH":
                    has_select = any(
                        t.value.upper() == "SELECT" for t in stmt.flatten() if t.ttype in (Keyword, DML)
                    )
                    if not has_select:
                        raise SecurityViolationError(f"Prohibited SQL statement type: {stmt_type}. Only SELECT queries are permitted.")
                else:
                    raise SecurityViolationError(f"Prohibited SQL statement type: {stmt_type}. Only SELECT queries are permitted.")

            for token in stmt.flatten():
                token_val = token.value.strip().upper()
                if token_val in forbidden_keywords:
                    raise SecurityViolationError(
                        f"Forbidden keyword '{token_val}' detected. Query rejected for security reasons."
                    )
        else:
            # Fallback pure regex check
            words = re.findall(r"\b[A-Za-z_]+\b", cleaned_no_semicolon)
            if not words:
                raise SecurityViolationError("No executable SQL statements found.")

            first_word = words[0].upper()
            if first_word not in ("SELECT", "WITH"):
                raise SecurityViolationError(f"Prohibited SQL statement: must start with SELECT. Found '{first_word}'.")

            for word in words:
                if word.upper() in forbidden_keywords:
                    raise SecurityViolationError(
                        f"Forbidden keyword '{word.upper()}' detected. Query rejected for security reasons."
                    )

    def execute_query(self, sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Tool 3: Executes a read-only SQL query and returns the results as a list of dictionaries.
        Strictly enforces read-only access and rejects any non-SELECT statements.
        """
        # Security validation
        self._validate_sql_security(sql)

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)

            rows = cursor.fetchall()
            results = [dict(row) for row in rows]
            return results
        finally:
            conn.close()
