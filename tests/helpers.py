# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 CEOX Planejamento e Otimização
"""Shared helpers for the QGIS tests: WKB builders and a fake Redshift."""

from qgis.core import QgsGeometry


def hex_wkb(wkt):
    """WKB as hex text, the way Redshift sends ST_AsBinary over psycopg2."""
    return bytes(QgsGeometry.fromWkt(wkt).asWkb()).hex()


class FakeRedshift:
    """Answers the queries LoadTask sends, by their first words.

    columns: [(name, data_type)] as SVV_COLUMNS returns them
    srids:   [(srid, count)] for the SRID sample
    rows:    data rows, attributes in column order and WKB last
    fail_on: substring of a query that raises `error`
    """

    def __init__(self, columns, rows, srids=((4326, 1),), fail_on=None, error=None):
        self.columns = list(columns)
        self.rows = list(rows)
        self.srids = list(srids)
        self.fail_on = fail_on
        self.error = error or RuntimeError("boom")
        self.queries = []
        self.closed = 0

    def connect(self, params):
        return _Connection(self)


class _Connection:
    def __init__(self, db):
        self.db = db

    def cursor(self):
        return _Cursor(self.db)

    def close(self):
        self.db.closed += 1


class _Cursor:
    def __init__(self, db):
        self.db = db
        self.result = []
        self.pending = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, query, params=None):
        q = " ".join(query.split())
        self.db.queries.append((q, params))
        if self.db.fail_on and self.db.fail_on in q:
            raise self.db.error
        if q.startswith("SELECT column_name"):
            self.result = list(self.db.columns)
        elif q.startswith("SELECT ST_SRID"):
            self.result = list(self.db.srids)
        elif q.startswith("SELECT COUNT"):
            self.result = [(len(self.db.rows),)]
        elif q.startswith("DECLARE"):
            self.pending = list(self.db.rows)
            self.result = []
        elif q.startswith("FETCH FORWARD"):
            n = int(q.split()[2])
            self.result, self.pending = self.pending[:n], self.pending[n:]
        else:
            raise AssertionError(f"unexpected query: {q}")

    def fetchall(self):
        return self.result

    def fetchone(self):
        return self.result[0]
