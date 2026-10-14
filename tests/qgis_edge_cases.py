# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 CEOX Planejamento e Otimização
"""Edge cases: odd column names, geometries and values, and the whole
LoadTask against a fake Redshift. Run through tests/run_qgis.py."""

import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsField,
    QgsFields,
    QgsProject,
    QgsVectorLayer,
    QgsWkbTypes,
)

from redshift_spatial import compat, db, loader, sources
from redshift_spatial.controller import Controller

from helpers import FakeRedshift, hex_wkb

CRS = QgsCoordinateReferenceSystem("EPSG:4326")


def tmp_gpkg(name="out.gpkg"):
    return os.path.join(tempfile.mkdtemp(), name)


def sink_with(columns, path=None, layer="t"):
    fields = QgsFields()
    for name, kind in columns:
        fields.append(QgsField(name, loader.FIELD_TYPES[kind]))
    return loader.FeatureSink(path or tmp_gpkg(), layer, fields, [k for _, k in columns], CRS)


def open_layer(result):
    fam, path, layer_name, count = result
    layer = QgsVectorLayer(f"{path}|layername={layer_name}", fam, "ogr")
    assert layer.isValid(), path
    return layer


# --- names --------------------------------------------------------------------


def test_attribute_named_geom_does_not_clash_with_geometry_column():
    """GeoPackage names its geometry column "geom" by default."""
    sink = sink_with([("geom", "string"), ("fid", "int")])
    sink.add(["text in geom", 1], hex_wkb("POINT(1 2)"))
    (result,) = sink.close()
    f = next(open_layer(result).getFeatures())
    assert f["geom"] == "text in geom" and f["fid"] == 1
    assert f.geometry().asWkt() == "MultiPoint ((1 2))"


def test_odd_column_names_survive():
    names = ["order", "Área", "with space", 'quo"te', "emoji_🌎", "x" * 60]
    sink = sink_with([(n, "string") for n in names])
    sink.add(names, hex_wkb("POINT(0 0)"))
    (result,) = sink.close()
    layer = open_layer(result)
    assert [f.name() for f in layer.fields() if f.name() in names] == names
    f = next(layer.getFeatures())
    assert [f[n] for n in names] == names


def test_odd_path_and_layer_name():
    path = os.path.join(tempfile.mkdtemp(), "pasta com espaço", "ação.gpkg")
    os.makedirs(os.path.dirname(path))
    sink = sink_with([("a", "int")], path=path, layer="my-table.v2")
    sink.add([1], hex_wkb("POINT(0 0)"))
    (result,) = sink.close()
    assert open_layer(result).featureCount() == 1


# --- geometries -----------------------------------------------------------------


def test_every_family_gets_its_own_file():
    sink = sink_with([("a", "int")])
    for wkt in (
        "POINT(0 0)",
        "MULTIPOINT((0 0),(1 1))",
        "LINESTRING(0 0,1 1)",
        "MULTILINESTRING((0 0,1 1))",
        "POLYGON((0 0,1 0,1 1,0 0))",
        "GEOMETRYCOLLECTION(POINT(0 0),LINESTRING(0 0,1 1))",
    ):
        sink.add([1], hex_wkb(wkt))
    results = {r[0]: r for r in sink.close()}
    assert {fam: r[3] for fam, r in results.items()} == {"point": 2, "line": 2, "polygon": 1, "collection": 1}
    assert QgsWkbTypes.flatType(open_layer(results["line"]).wkbType()) == compat.MULTI_LINE_STRING
    assert QgsWkbTypes.flatType(open_layer(results["collection"]).wkbType()) == compat.GEOMETRY_COLLECTION


def test_z_and_2d_mixed_in_one_family():
    """The first geometry decides the layer type; later ones are coerced."""
    for first, second in (("POLYGON Z((0 0 5,1 0 5,1 1 5,0 0 5))", "POLYGON((0 0,1 0,1 1,0 0))"),
                          ("POLYGON((0 0,1 0,1 1,0 0))", "POLYGON Z((0 0 5,1 0 5,1 1 5,0 0 5))")):
        sink = sink_with([("a", "int")])
        sink.add([1], hex_wkb(first))
        sink.add([2], hex_wkb(second))
        (result,) = sink.close()
        assert result[3] == 2
        assert open_layer(result).featureCount() == 2


def test_m_values_are_kept_or_coerced():
    sink = sink_with([("a", "int")])
    sink.add([1], hex_wkb("POINT M(1 2 3)"))
    sink.add([2], hex_wkb("POINT(4 5)"))
    (result,) = sink.close()
    assert open_layer(result).featureCount() == 2


def test_empty_and_broken_wkb():
    sink = sink_with([("a", "int")])
    sink.add([1], hex_wkb("POLYGON((0 0,1 0,1 1,0 0))"))
    sink.add([2], hex_wkb("POLYGON EMPTY"))
    sink.add([3], "00ff")
    sink.add([4], "")
    sink.add([5], None)
    results = sink.close()
    assert sink.invalid >= 3
    assert sum(r[3] for r in results) + sink.invalid == 5


def test_large_polygon_roundtrip():
    """Redshift allows ~1 MB per geometry, far beyond the 65 535-char
    VARCHAR limit that rules out WKT for large polygons."""
    import math

    n = 50_000
    ring = [(math.cos(2 * math.pi * i / n), math.sin(2 * math.pi * i / n)) for i in range(n)]
    wkt = "POLYGON((" + ",".join(f"{x:.9f} {y:.9f}" for x, y in ring + ring[:1]) + "))"
    sink = sink_with([("a", "int")])
    sink.add([1], hex_wkb(wkt))
    (result,) = sink.close()
    f = next(open_layer(result).getFeatures())
    assert f.geometry().constGet().nCoordinates() == n + 1


# --- values ---------------------------------------------------------------------


def test_values_at_the_edges():
    cols = [("txt", "string"), ("big", "int64"), ("num", "double"), ("ok", "bool"),
            ("d", "date"), ("ts", "datetime"), ("tstz", "datetime")]
    long_text = "ção 🌎 \"quotes\" 'single'\nnew line\t" * 500
    values = [long_text, 9223372036854775807, Decimal("123456789012345.6789"), False,
              date(1, 1, 1), datetime(2026, 2, 28, 23, 59, 59, 999000),
              datetime(2026, 10, 14, 9, 0, tzinfo=timezone(timedelta(hours=-3)))]
    sink = sink_with(cols)
    sink.add(values, hex_wkb("POINT(0 0)"))
    sink.add([None] * len(cols), hex_wkb("POINT(1 1)"))
    (result,) = sink.close()
    feats = sorted(open_layer(result).getFeatures(), key=lambda f: f.geometry().asPoint().x())
    f, empty = feats
    assert f["txt"] == long_text
    assert f["big"] == 9223372036854775807
    assert abs(f["num"] - 123456789012345.6789) < 1
    assert f["ok"] is False or f["ok"] == 0
    assert f["d"].toString("yyyy-MM-dd") == "0001-01-01"
    assert f["ts"].toString("yyyy-MM-dd HH:mm:ss.zzz") == "2026-02-28 23:59:59.999"
    assert f["tstz"].toUTC().toString("yyyy-MM-dd HH:mm") == "2026-10-14 12:00"
    assert all(empty[name] is None or str(empty[name]) == "NULL" for name, _ in cols)


# --- LoadTask against a fake Redshift ------------------------------------------------


COLUMNS = [
    ("id", "bigint"),
    ("fid", "integer"),
    ("geom", "character varying(20)"),
    ("doc", "super"),
    ("raw", "varbyte(64)"),
    ("t", "time without time zone"),
    ("shape", "geometry"),
]


def run_task(fake, source=None, **options):
    source = source or sources.table("analytics", "parcels", "shape", "geometry")
    original = db.connect
    db.connect = fake.connect
    try:
        opts = {"where": "", "limit": 0, "path": tmp_gpkg("parcels.gpkg"),
                "fallback_crs": QgsCoordinateReferenceSystem("EPSG:3857")}
        opts.update(options)
        task = loader.LoadTask({}, source, opts, lambda *a: None)
        cancel = opts.pop("cancel_before", False)
        if cancel:
            task.cancel()
        ok = task.run()
    finally:
        db.connect = original
    return task, ok


def rows(n, start=0):
    return [(i, i % 3, "g", '{"k": 1}', "12:00:00", hex_wkb(f"POINT({i} {i})")) for i in range(start, start + n)]


def test_task_end_to_end_with_batches_and_odd_columns():
    fake = FakeRedshift(COLUMNS, rows(2500))
    task, ok = run_task(fake, where="id > 0")
    assert ok, task.error
    (result,) = task.results
    assert result[3] == 2500
    layer = open_layer(result)
    assert [f.name() for f in layer.fields()][-5:] == ["id", "fid", "geom", "doc", "t"]
    assert layer.crs().authid() == "EPSG:4326"
    assert any("raw" in m for m in task.messages)
    data = [q for q, _ in fake.queries if q.startswith("DECLARE")][0]
    assert 'JSON_SERIALIZE("doc")' in data and 'CAST("t" AS VARCHAR)' in data
    assert '"raw"' not in data and "AND (id > 0)" in data
    fetches = [q for q, _ in fake.queries if q.startswith("FETCH")]
    assert len(fetches) == 4 and all("FORWARD 1000" in q for q in fetches)
    assert fake.closed == 1


def test_task_srid_zero_uses_fallback():
    task, ok = run_task(FakeRedshift(COLUMNS, rows(3), srids=[(0, 3)]),
                        fallback_crs=QgsCoordinateReferenceSystem("EPSG:32633"))
    assert ok
    assert open_layer(task.results[0]).crs().authid() == "EPSG:32633"
    assert any("SRID 0" in m for m in task.messages)


def test_task_unknown_and_mixed_srids_are_reported():
    task, ok = run_task(FakeRedshift(COLUMNS, rows(3), srids=[(999999, 2), (4326, 1)]))
    assert ok
    assert any("999999" in m for m in task.messages)
    assert any("2 SRIDs" in m for m in task.messages)


def test_task_without_rows_creates_nothing():
    task, ok = run_task(FakeRedshift(COLUMNS, [], srids=[]))
    assert ok and task.results == []
    assert not any("SRID" in m for m in task.messages)


def test_task_case_insensitive_duplicate_columns():
    cols = [("Area", "numeric(10,2)"), ("area", "numeric(10,2)"), ("g", "geometry")]
    fake = FakeRedshift(cols, [(Decimal("1.5"), Decimal("2.5"), hex_wkb("POINT(0 0)"))])
    task, ok = run_task(fake, source=sources.table("public", "t", "g", "geometry"))
    assert ok, task.error
    f = next(open_layer(task.results[0]).getFeatures())
    assert f["Area"] == 1.5 and f["area_2"] == 2.5


def test_task_limit_and_geography():
    cols = [("id", "bigint"), ("g", "geography")]
    fake = FakeRedshift(cols, [(1, hex_wkb("POINT(1 1)"))], srids=[(4326, 1)])
    task, ok = run_task(fake, source=sources.table("public", "pts", "g", "geography"), limit=5)
    assert ok
    data = [q for q, _ in fake.queries if q.startswith("DECLARE")][0]
    assert 'ST_AsBinary(CAST("g" AS GEOMETRY))' in data and data.endswith("LIMIT 5")


def test_task_canceled_before_start():
    task, ok = run_task(FakeRedshift(COLUMNS, rows(10)), cancel_before=True)
    assert not ok and task.error is None


def test_task_database_error_is_reported_and_connection_closed():
    fake = FakeRedshift(COLUMNS, rows(10), fail_on="DECLARE", error=RuntimeError('syntax error at or near "nope"'))
    task, ok = run_task(fake, where="nope nope")
    assert not ok and "syntax error" in str(task.error)
    assert fake.closed == 1


def test_controller_adds_one_layer_per_family():
    fake = FakeRedshift(COLUMNS, rows(2) + [(9, 0, "g", "{}", "00:00:00", hex_wkb("LINESTRING(0 0,1 1)"))])
    task, ok = run_task(fake)
    before = len(QgsProject.instance().mapLayers())
    Controller(None).task_finished(task, ok)
    names = sorted(layer.name() for layer in QgsProject.instance().mapLayers().values())
    assert len(QgsProject.instance().mapLayers()) == before + 2
    assert "parcels (point)" in names and "parcels (line)" in names
    QgsProject.instance().removeAllMapLayers()


def test_controller_reports_failures_without_iface():
    task, ok = run_task(FakeRedshift(COLUMNS, rows(1), fail_on="DECLARE"))
    Controller(None).task_finished(task, ok)
    task, ok = run_task(FakeRedshift(COLUMNS, []))
    Controller(None).task_finished(task, ok)
