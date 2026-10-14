# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 CEOX Planejamento e Otimização
"""SQL and type helpers for Amazon Redshift.

No QGIS imports here, so this module can be unit tested with plain pytest.
"""

import struct
from datetime import date, datetime
from decimal import Decimal

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


def preview_query(from_clause, limit=PREVIEW_ROWS, where=None):
    return f"SELECT * FROM {from_clause}{_where(None, where)} LIMIT {int(limit)}"


def clean_filter(where):
    """The filter as typed, minus a leading WHERE keyword and a trailing
    semicolon: the plugin writes the WHERE itself."""
    text = (where or "").strip().rstrip(";").strip()
    if text[:6].lower() == "where " or text.lower() == "where":
        text = text[5:].strip()
    return text


def _where(geom_expr, where):
    """' WHERE ...' or ''."""
    parts = []
    if geom_expr:
        parts.append(f"{geom_expr} IS NOT NULL")
    where = clean_filter(where)
    if where:
        parts.append(f"({where})")
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


# EWKB (what Redshift prints for GEOMETRY) flags the type with Z, M and SRID
# bits and may embed the SRID; ISO WKB (what QGIS reads) encodes Z/M as
# +1000/+2000 on the type and carries no SRID.
_EWKB_Z = 0x80000000
_EWKB_M = 0x40000000
_EWKB_SRID = 0x20000000


def ewkb_to_iso(value):
    """(ISO WKB bytes, SRID or 0) from EWKB given as hex text or bytes.
    ISO WKB input passes through unchanged."""
    data = wkb_bytes(value)
    out = bytearray()
    srid = [0]
    end = _convert_geometry(data, 0, out, srid)
    if end != len(data):
        raise ValueError("trailing bytes after the geometry")
    return bytes(out), srid[0]


def _convert_geometry(data, pos, out, srid):
    order = data[pos]
    if order not in (0, 1):
        raise ValueError("not WKB")
    e = "<" if order == 1 else ">"
    (raw,) = struct.unpack_from(e + "I", data, pos + 1)
    pos += 5
    has_z, has_m = bool(raw & _EWKB_Z), bool(raw & _EWKB_M)
    if raw & _EWKB_SRID:
        (found,) = struct.unpack_from(e + "I", data, pos)
        pos += 4
        srid[0] = srid[0] or found
    base = raw & 0x0FFFFFFF
    if base >= 1000:  # already ISO
        has_z = has_z or base // 1000 in (1, 3)
        has_m = has_m or base // 1000 in (2, 3)
        base %= 1000
    point = 8 * (2 + has_z + has_m)
    out += bytes([order]) + struct.pack(e + "I", base + 1000 * has_z + 2000 * has_m)

    def copy(n):
        nonlocal pos
        out.extend(data[pos:pos + n])
        if pos + n > len(data):
            raise ValueError("truncated WKB")
        pos += n

    def count():
        (n,) = struct.unpack_from(e + "I", data, pos)
        copy(4)
        return n

    if base == 1:
        copy(point)
    elif base == 2:
        copy(count() * point)
    elif base == 3:
        for _ in range(count()):
            copy(count() * point)
    elif base in (4, 5, 6, 7):
        for _ in range(count()):
            pos = _convert_geometry(data, pos, out, srid)
    else:
        raise ValueError(f"unsupported WKB type {base}")
    return pos


def infer_kind(values):
    """Field kind for a column known only by its values (rows already
    fetched for a preview): the narrowest kind every non-NULL value fits."""
    values = [v for v in values if v is not None]
    if not values:
        return "string"
    if all(isinstance(v, bool) for v in values):
        return "bool"
    if all(isinstance(v, int) and not isinstance(v, bool) for v in values):
        return "int64"
    if all(isinstance(v, (int, float, Decimal)) and not isinstance(v, bool) for v in values):
        return "double"
    if all(isinstance(v, datetime) for v in values):
        return "datetime"
    if all(isinstance(v, date) and not isinstance(v, datetime) for v in values):
        return "date"
    return "string"


def safe_file_name(name):
    """A label such as "gold.vw_car (selected)" as a file name."""
    cleaned = "".join(c if c.isalnum() or c in "-_" else "_" for c in name).strip("_")
    return cleaned or "layer"
