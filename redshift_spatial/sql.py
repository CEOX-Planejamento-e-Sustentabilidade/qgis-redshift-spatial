# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 CEOX Planejamento e Otimização
"""SQL and type helpers for Amazon Redshift.

No QGIS imports here, so this module can be unit tested with plain pytest.
"""

# Single-node clusters reject FETCH above 1000 rows; multi-node clusters
# accept more, but 1000 works everywhere.
FETCH_SIZE = 1000
CURSOR_NAME = "qgis_redshift_spatial"
SPATIAL_TYPES = ("geometry", "geography")
SRID_SAMPLE = 10000

PREVIEW_ROWS = 100
SQL_PREVIEW_ROWS = 200

# Leader-node catalogs and temporary schemas are not user data.
_USER_SCHEMAS = (
    "table_schema NOT IN ('information_schema', 'catalog_history') "
    "AND LEFT(table_schema, 3) <> 'pg_'"
)

# SVV_COLUMNS also covers late-binding views (WITH NO SCHEMA BINDING), whose
# columns are missing from pg_attribute / information_schema.
LIST_SPATIAL_COLUMNS = f"""
SELECT table_schema, table_name, column_name, LOWER(data_type)
FROM svv_columns
WHERE LOWER(data_type) IN ('geometry', 'geography')
  AND {_USER_SCHEMAS}
ORDER BY 1, 2, 3
"""

LIST_PLAIN_TABLES = f"""
SELECT table_schema, table_name
FROM svv_columns
WHERE {_USER_SCHEMAS}
GROUP BY 1, 2
HAVING SUM(CASE WHEN LOWER(data_type) IN ('geometry', 'geography') THEN 1 ELSE 0 END) = 0
ORDER BY 1, 2
"""

LIST_COLUMNS = """
SELECT column_name, LOWER(data_type)
FROM svv_columns
WHERE table_schema = %s AND table_name = %s
ORDER BY ordinal_position
"""

# PostgreSQL type OIDs that Redshift reports in cursor.description. Anything
# else (GEOMETRY, SUPER, VARBYTE...) reaches psycopg2 as text.
_OID_KINDS = {
    16: "bool",
    20: "int64",
    21: "int",
    23: "int",
    25: "string",
    700: "double",
    701: "double",
    1042: "string",
    1043: "string",
    1082: "date",
    1114: "datetime",
    1184: "datetime",
    1700: "double",
}

_KINDS = {
    "character varying": "string",
    "varchar": "string",
    "character": "string",
    "char": "string",
    "bpchar": "string",
    "text": "string",
    "smallint": "int",
    "integer": "int",
    "bigint": "int64",
    "numeric": "double",
    "decimal": "double",
    "real": "double",
    "double precision": "double",
    "boolean": "bool",
    "date": "date",
    "timestamp without time zone": "datetime",
    "timestamp with time zone": "datetime",
}


def quote_ident(name):
    return '"' + name.replace('"', '""') + '"'


def table_ref(schema, table):
    return f"{quote_ident(schema)}.{quote_ident(table)}"


def base_type(data_type):
    """'character varying(256)' -> 'character varying'."""
    return data_type.split("(")[0].strip().lower()


def attribute_column(name, data_type):
    """Return (select expression, kind) for an attribute column, or None when
    the column cannot become a QGIS field (spatial, varbyte, hllsketch...)."""
    base = base_type(data_type)
    col = quote_ident(name)
    if base in SPATIAL_TYPES:
        return None
    if base in _KINDS:
        return col, _KINDS[base]
    if base == "super":
        return f"JSON_SERIALIZE({col})", "string"
    if base.startswith(("time", "interval")):
        return f"CAST({col} AS VARCHAR)", "string"
    return None


def unique_names(names):
    """Field names unique ignoring case, as GeoPackage requires. Redshift can
    return "Area" and "area" when enable_case_sensitive_identifier is on."""
    seen, result = set(), []
    for name in names:
        candidate, n = name, 2
        while candidate.lower() in seen:
            candidate = f"{name}_{n}"
            n += 1
        seen.add(candidate.lower())
        result.append(candidate)
    return result


def geometry_expression(column, data_type):
    col = quote_ident(column)
    if base_type(data_type) == "geography":
        return f"CAST({col} AS GEOMETRY)"
    return col


def kind_for_oid(oid):
    return _OID_KINDS.get(oid, "string")


def clean_query(text):
    """User SQL without the trailing semicolon. It is always wrapped as a
    subquery, so only a SELECT (or WITH ... SELECT) can run."""
    query = (text or "").strip().rstrip(";").strip()
    if not query:
        raise ValueError("The query is empty.")
    return query


def query_from(text):
    return f"({clean_query(text)}) AS q"


def describe_query(text):
    return f"SELECT * FROM {query_from(text)} LIMIT 0"


def preview_query(from_clause, limit=PREVIEW_ROWS):
    return f"SELECT * FROM {from_clause} LIMIT {int(limit)}"


def _where(geom_expr, where):
    """' WHERE ...' or ''."""
    parts = []
    if geom_expr:
        parts.append(f"{geom_expr} IS NOT NULL")
    if where and where.strip():
        parts.append(f"({where.strip()})")
    return " WHERE " + " AND ".join(parts) if parts else ""


def srid_query(from_clause, geom_expr, where=None, sample=SRID_SAMPLE):
    return (
        "SELECT ST_SRID(g), COUNT(*) FROM ("
        f"SELECT {geom_expr} AS g FROM {from_clause}{_where(geom_expr, where)} LIMIT {int(sample)}"
        ") s GROUP BY 1 ORDER BY 2 DESC"
    )


def count_query(from_clause, geom_expr=None, where=None):
    return f"SELECT COUNT(*) FROM {from_clause}{_where(geom_expr, where)}"


def data_query(from_clause, select_exprs, geom_expr=None, where=None, limit=None):
    """Attributes, then ST_AsBinary(geometry) last when there is a geometry."""
    cols = list(select_exprs)
    if geom_expr:
        cols.append(f"ST_AsBinary({geom_expr})")
    sql = f"SELECT {', '.join(cols) or '1'} FROM {from_clause}{_where(geom_expr, where)}"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return sql


def looks_like_wkb(value):
    """Display helper: GEOMETRY and VARBYTE arrive as long hex strings."""
    return (
        isinstance(value, str)
        and len(value) >= 18
        and len(value) % 2 == 0
        and value[:2] in ("00", "01")
        and all(c in "0123456789abcdefABCDEF" for c in value[:64])
    )


def declare_cursor(query):
    # Hand-written DECLARE: psycopg2 named cursors send "WITHOUT HOLD",
    # which Redshift rejects.
    return f"DECLARE {CURSOR_NAME} CURSOR FOR {query}"


def fetch_cursor():
    return f"FETCH FORWARD {FETCH_SIZE} FROM {CURSOR_NAME}"


def wkb_bytes(value):
    """Redshift sends VARBYTE as hex text, which psycopg2 does not decode."""
    if value is None:
        return None
    if isinstance(value, str):
        return bytes.fromhex(value[2:] if value.startswith("\\x") else value)
    return bytes(value)
