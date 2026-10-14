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
