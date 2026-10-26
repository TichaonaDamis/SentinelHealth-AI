"""Helpers for raw-SQL Alembic migrations (asyncpg runs one statement per call)."""

from __future__ import annotations


def split_sql(script: str) -> list[str]:
    """Split a SQL script on top-level semicolons, keeping ``$$``-quoted bodies and comments intact."""
    statements, buf, in_dollar, i = [], [], False, 0
    while i < len(script):
        if script.startswith("$$", i):
            in_dollar = not in_dollar
            buf.append("$$")
            i += 2
            continue
        ch = script[i]
        if ch == "-" and script.startswith("--", i) and not in_dollar:
            end = script.find("\n", i)
            i = len(script) if end == -1 else end
            continue
        if ch == ";" and not in_dollar:
            stmt = "".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
        else:
            buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def execute_script(op, script: str) -> None:
    for stmt in split_sql(script):
        op.execute(stmt)
