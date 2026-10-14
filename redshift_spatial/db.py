# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 CEOX Planejamento e Otimização
"""Thin psycopg2 layer. Redshift speaks the PostgreSQL wire protocol, so the
psycopg2 bundled with QGIS is enough; PostGIS is never needed."""

from contextlib import closing

import psycopg2

from . import sql


def connect(params):
    """params: host, port, dbname, user, password, sslmode."""
    return psycopg2.connect(
        connect_timeout=15, application_name="qgis-redshift-spatial", **params
    )


def server_version(params):
    with closing(connect(params)) as conn, conn.cursor() as cur:
        cur.execute("SELECT version()")
        return cur.fetchone()[0]


def list_spatial_columns(params):
    """[(schema, table, column, data_type)] for every geometry/geography column."""
    with closing(connect(params)) as conn, conn.cursor() as cur:
        cur.execute(sql.LIST_SPATIAL_COLUMNS)
        return cur.fetchall()


def list_tables(params, include_plain=False):
    """Every loadable source, sorted by schema and table:
    (schema, table, column, data_type) for each spatial column, plus
    (schema, table, None, None) for tables without geometry if asked."""
    with closing(connect(params)) as conn, conn.cursor() as cur:
        cur.execute(sql.LIST_SPATIAL_COLUMNS)
        rows = [tuple(r) for r in cur.fetchall()]
        if include_plain:
            cur.execute(sql.LIST_PLAIN_TABLES)
            rows += [(schema, table, None, None) for schema, table in cur.fetchall()]
    return sorted(rows, key=lambda r: (r[0], r[1], r[2] or ""))


def list_columns(params, schema, table):
    """[(column, data_type)] in table order."""
    with closing(connect(params)) as conn, conn.cursor() as cur:
        cur.execute(sql.LIST_COLUMNS, (schema, table))
        return [tuple(r) for r in cur.fetchall()]
