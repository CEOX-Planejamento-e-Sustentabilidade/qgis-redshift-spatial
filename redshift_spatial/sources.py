# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 CEOX Planejamento e Otimização
"""What can be loaded: a table column, a table without geometry or the
result of a SQL query. Plain dicts, so they travel to background tasks."""


def table(schema, table, column=None, data_type=None):
    return {
        "kind": "table",
        "schema": schema,
        "table": table,
        "column": column,
        "data_type": data_type or ("geometry" if column else None),
        "name": table,
    }


def query(sql, column=None, name="query"):
    return {
        "kind": "query",
        "sql": sql,
        "column": column,
        "data_type": "geometry" if column else None,
        "name": name or "query",
    }


def label(source):
    if source["kind"] == "table":
        return f"{source['schema']}.{source['table']}"
    return source["name"]


def from_row(row):
    """A row of db.list_tables()."""
    return table(*row)
