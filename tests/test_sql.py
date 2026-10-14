# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 CEOX Planejamento e Otimização
from redshift_spatial import sources, sql

T = sql.table_ref("s", "t")


def test_quote_ident_escapes_double_quotes():
    assert sql.quote_ident('we"ird') == '"we""ird"'
    assert sql.table_ref("analytics", "parcels") == '"analytics"."parcels"'


def test_quote_ident_odd_names():
    assert sql.quote_ident("order") == '"order"'
    assert sql.quote_ident("Área com espaço") == '"Área com espaço"'
    assert sql.quote_ident('a""b') == '"a""""b"'
    assert sql.quote_ident("emoji_🌎") == '"emoji_🌎"'
    assert sql.table_ref('my"schema', "t.v2") == '"my""schema"."t.v2"'


def test_unique_names_ignores_case():
    assert sql.unique_names(["Area", "area", "AREA", "area_2"]) == ["Area", "area_2", "AREA_3", "area_2_2"]
    assert sql.unique_names(["a", "b"]) == ["a", "b"]
    assert sql.unique_names([]) == []


def test_base_type_is_case_and_space_tolerant():
    assert sql.base_type(" CHARACTER VARYING(10) ") == "character varying"
    assert sql.attribute_column("x", "NUMERIC(38,10)") == ('"x"', "double")
    assert sql.attribute_column("x", "GEOMETRY") is None
    assert sql.attribute_column("x", "hllsketch") is None
    assert sql.attribute_column("x", "interval year to month") == ('CAST("x" AS VARCHAR)', "string")


def test_filter_is_parenthesized_so_or_cannot_escape():
    q = sql.count_query(T, '"g"', "a = 1 OR b = 2")
    assert q.endswith('WHERE "g" IS NOT NULL AND (a = 1 OR b = 2)')


def test_limit_is_forced_to_int():
    assert sql.data_query(T, [], '"g"', None, "7").endswith("LIMIT 7")


def test_wkb_bytes_uppercase_hex_and_bytearray():
    assert sql.wkb_bytes("0A0B") == b"\x0a\x0b"
    assert sql.wkb_bytes(bytearray(b"\x01\x02")) == b"\x01\x02"
    assert sql.wkb_bytes("") == b""


def test_attribute_column_maps_types():
    assert sql.attribute_column("name", "character varying(256)") == ('"name"', "string")
    assert sql.attribute_column("area", "numeric(18,4)") == ('"area"', "double")
    assert sql.attribute_column("id", "bigint") == ('"id"', "int64")
    assert sql.attribute_column("ok", "boolean") == ('"ok"', "bool")
    assert sql.attribute_column("d", "date") == ('"d"', "date")
    assert sql.attribute_column("ts", "timestamp with time zone") == ('"ts"', "datetime")


def test_attribute_column_casts_or_skips_the_rest():
    assert sql.attribute_column("doc", "super") == ('JSON_SERIALIZE("doc")', "string")
    assert sql.attribute_column("t", "time without time zone") == ('CAST("t" AS VARCHAR)', "string")
    assert sql.attribute_column("geom", "geometry") is None
    assert sql.attribute_column("geog", "geography") is None
    assert sql.attribute_column("raw", "varbyte(1024)") is None


def test_geography_is_cast_to_geometry():
    assert sql.geometry_expression("g", "geometry") == '"g"'
    assert sql.geometry_expression("g", "geography") == 'CAST("g" AS GEOMETRY)'


def test_data_query_puts_wkb_last_and_wraps_filter():
    q = sql.data_query(sql.table_ref("analytics", "parcels"), ['"a"', '"b"'], '"geom"', "region = 'north' OR x = 1", 10)
    assert q == (
        'SELECT "a", "b", ST_AsBinary("geom") FROM "analytics"."parcels" '
        "WHERE \"geom\" IS NOT NULL AND (region = 'north' OR x = 1) LIMIT 10"
    )


def test_data_query_without_filter_or_limit():
    q = sql.data_query(T, [], '"g"', "  ", 0)
    assert q == 'SELECT ST_AsBinary("g") FROM "s"."t" WHERE "g" IS NOT NULL'


def test_srid_query_samples_rows():
    q = sql.srid_query(T, '"g"', sample=50)
    assert "LIMIT 50" in q and q.startswith("SELECT ST_SRID(g), COUNT(*)")


def test_cursor_avoids_without_hold_and_respects_single_node_limit():
    assert sql.declare_cursor("SELECT 1") == "DECLARE qgis_redshift_spatial CURSOR FOR SELECT 1"
    assert "WITHOUT HOLD" not in sql.declare_cursor("SELECT 1")
    assert sql.FETCH_SIZE <= 1000
    assert sql.fetch_cursor() == "FETCH FORWARD 1000 FROM qgis_redshift_spatial"


def test_wkb_bytes_accepts_hex_text_and_binary():
    assert sql.wkb_bytes("0101") == b"\x01\x01"
    assert sql.wkb_bytes("\\x0101") == b"\x01\x01"
    assert sql.wkb_bytes(memoryview(b"\x01")) == b"\x01"
    assert sql.wkb_bytes(None) is None


def test_data_query_without_geometry():
    q = sql.data_query(T, ['"a"'], None, "a > 1", 5)
    assert q == 'SELECT "a" FROM "s"."t" WHERE (a > 1) LIMIT 5'
    assert sql.data_query(T, ['"a"']) == 'SELECT "a" FROM "s"."t"'
    assert sql.count_query(T) == 'SELECT COUNT(*) FROM "s"."t"'


def test_user_query_is_wrapped_as_subquery():
    assert sql.clean_query("  select 1 ;; ") == "select 1"
    assert sql.query_from("SELECT 1;") == "(SELECT 1) AS q"
    assert sql.describe_query("SELECT a FROM t") == "SELECT * FROM (SELECT a FROM t) AS q LIMIT 0"
    assert sql.preview_query(sql.query_from("SELECT 1"), 20) == "SELECT * FROM (SELECT 1) AS q LIMIT 20"
    q = sql.data_query(sql.query_from("SELECT g FROM t"), [], '"g"', "x = 1", 3)
    assert q == 'SELECT ST_AsBinary("g") FROM (SELECT g FROM t) AS q WHERE "g" IS NOT NULL AND (x = 1) LIMIT 3'


def test_empty_query_is_rejected():
    import pytest

    for text in ("", "   ", ";", None):
        with pytest.raises(ValueError):
            sql.clean_query(text)


def test_kind_for_oid_defaults_to_string():
    assert sql.kind_for_oid(23) == "int"
    assert sql.kind_for_oid(20) == "int64"
    assert sql.kind_for_oid(1700) == "double"
    assert sql.kind_for_oid(1184) == "datetime"
    assert sql.kind_for_oid(3000) == "string"  # GEOMETRY and friends arrive as text


def test_looks_like_wkb():
    assert sql.looks_like_wkb("0101000020E6100000" + "00" * 16)
    assert not sql.looks_like_wkb("hello world, not hex at all")
    assert not sql.looks_like_wkb("0101")
    assert not sql.looks_like_wkb(12345)
    assert not sql.looks_like_wkb("abc")


def test_listing_queries_skip_system_schemas():
    for q in (sql.LIST_SPATIAL_COLUMNS, sql.LIST_PLAIN_TABLES):
        assert "information_schema" in q and "LEFT(table_schema, 3) <> 'pg_'" in q
    assert "HAVING SUM" in sql.LIST_PLAIN_TABLES


def test_sources():
    t = sources.table("s", "t", "g", "geography")
    assert sources.label(t) == "s.t" and t["data_type"] == "geography"
    plain = sources.from_row(("s", "t", None, None))
    assert plain["column"] is None and plain["data_type"] is None
    q = sources.query("SELECT 1", None, "")
    assert q["name"] == "query" and sources.label(q) == "query"
