# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 CEOX Planejamento e Otimização
"""What can be loaded: a table column, a table without geometry or the
result of a SQL query. Plain dicts, so they travel to background tasks."""

from . import sql
from .i18n import tr

NAME_FILTER_MAX = 60


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


def layer_name(name, where=None):
    """The name shown in the Layers panel: the table name plus the filter,
    cut short, so that loads of one table with different filters can be
    told apart. The whole filter goes to the tooltip (describe)."""
    text = " ".join(sql.clean_filter(where).split())
    if not text:
        return name
    if len(text) > NAME_FILTER_MAX:
        text = text[: NAME_FILTER_MAX - 1].rstrip() + "…"
    return f"{name} [{text}]"


def describe(origin):
    """Plain text for the layer tooltip: what was loaded, from where."""
    source = origin["source"]
    lines = [label(source) if source["kind"] == "table" else source["sql"]]
    where = sql.clean_filter(origin.get("where"))
    if where:
        lines.append(f"WHERE {where}")
    if origin.get("limit"):
        lines.append(f"LIMIT {origin['limit']}")
    lines.append(tr("Redshift connection: {}").format(origin["connection"]))
    return "\n".join(lines)


def from_row(row):
    """A row of db.list_tables()."""
    return table(*row)
