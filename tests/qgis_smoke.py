# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 CEOX Planejamento e Otimização
"""Smoke tests inside the QGIS Python, without a database or a visible
window. Run through tests/run_qgis.py."""

import os
import tempfile
from datetime import date, datetime, timezone
from decimal import Decimal

from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant

from redshift_spatial import loader
from redshift_spatial.controller import Controller
from redshift_spatial.dialog import ConnectionDialog, LoadLayerDialog, LoadOptionsDialog

from helpers import hex_wkb


def test_sink_splits_families_and_promotes_to_multi():
    fields = QgsFields()
    for name, kind in [("id", "int64"), ("area", "double"), ("d", "date"), ("ts", "datetime")]:
        fields.append(QgsField(name, loader.FIELD_TYPES[kind]))
    kinds = ["int64", "double", "date", "datetime"]
    path = os.path.join(tempfile.mkdtemp(), "parcels.gpkg")
    sink = loader.FeatureSink(path, "parcels", fields, kinds, QgsCoordinateReferenceSystem("EPSG:4326"))

    attrs = [1, Decimal("12.5"), date(2026, 8, 20), datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)]
    sink.add(attrs, hex_wkb("POLYGON((0 0,1 0,1 1,0 0))"))
    sink.add(attrs, "\\x" + hex_wkb("MULTIPOLYGON(((2 2,3 2,3 3,2 2)))"))
    sink.add(attrs, hex_wkb("POINT(5 5)"))
    sink.add(attrs, None)
    results = sink.close()

    assert sink.invalid == 1
    assert [(r[0], r[3]) for r in results] == [("polygon", 2), ("point", 1)]
    poly = QgsVectorLayer(f"{results[0][1]}|layername=parcels", "p", "ogr")
    assert poly.isValid() and poly.featureCount() == 2
    assert QgsWkbTypes.flatType(poly.wkbType()) == QgsWkbTypes.MultiPolygon
    assert poly.crs().authid() == "EPSG:4326"
    f = next(poly.getFeatures())
    assert f["area"] == 12.5 and f["d"].toString("yyyy-MM-dd") == "2026-08-20"
    assert results[1][1].endswith("parcels_point.gpkg")


def test_column_named_fid_does_not_clash_with_geopackage_key():
    """GeoPackage uses "fid" as its primary key; a source column with that
    name and repeated or NULL values must stay an ordinary attribute."""
    fields = QgsFields()
    fields.append(QgsField("fid", loader.FIELD_TYPES["int64"]))
    fields.append(QgsField("gpkg_fid", loader.FIELD_TYPES["string"]))
    path = os.path.join(tempfile.mkdtemp(), "sites.gpkg")
    sink = loader.FeatureSink(path, "sites", fields, ["int64", "string"], QgsCoordinateReferenceSystem("EPSG:4326"))
    for fid in (7, 7, None):
        sink.add([fid, "x"], hex_wkb("POINT(1 1)"))
    (_, out, name, count), = sink.close()
    assert count == 3
    layer = QgsVectorLayer(f"{out}|layername={name}", "s", "ogr")
    assert layer.featureCount() == 3
    assert sorted(f["fid"] or 0 for f in layer.getFeatures()) == [0, 7, 7]


def test_existing_output_is_released_or_renamed():
    """Reloading into a GeoPackage that a project layer still uses must not
    silently show the old content."""
    from qgis.core import QgsProject
    from qgis.PyQt.QtWidgets import QMessageBox

    from redshift_spatial import controller

    fields = QgsFields()
    fields.append(QgsField("id", loader.FIELD_TYPES["int64"]))
    path = os.path.join(tempfile.mkdtemp(), "parcels.gpkg")
    sink = loader.FeatureSink(path, "parcels", fields, ["int64"], QgsCoordinateReferenceSystem("EPSG:4326"))
    sink.add([1], hex_wkb("POINT(1 1)"))
    sink.close()
    layer = QgsVectorLayer(f"{path}|layername=parcels", "old", "ogr")
    QgsProject.instance().addMapLayer(layer)

    original = QMessageBox.question
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    try:
        target = Controller(None).release_output(path)
    finally:
        QMessageBox.question = original

    assert not QgsProject.instance().mapLayersByName("old")
    assert target == path and not os.path.exists(path) or target == controller.free_path(path)
    print(f"     released -> {os.path.basename(target)}")

    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
    try:
        open(path, "w").close()
        assert Controller(None).release_output(path) is None
    finally:
        QMessageBox.question = original


def test_dialogs_build():
    ctl = Controller(None)
    LoadLayerDialog(ctl)
    ConnectionDialog(ctl)
    LoadOptionsDialog(("analytics", "parcels", "shape", "geometry"))


def test_icon_renders():
    from qgis.PyQt.QtSvg import QSvgRenderer

    from redshift_spatial.controller import ICON_PATH, icon

    assert QSvgRenderer(ICON_PATH).isValid()
    assert not icon().isNull()


def test_browser_tree():
    """Root > connection > schema > table, without a database: the
    connection asks for credentials and gets a cancel."""
    from qgis.core import QgsDataItem

    from redshift_spatial import browser, connections

    ctl = Controller(None)
    ctl.params = lambda conn, parent=None: None
    provider = browser.RedshiftSpatialItemProvider(ctl)
    assert provider.name() == "Redshift Spatial"
    root = provider.createDataItem("", None)
    assert root.name() == "Redshift Spatial" and provider.createDataItem("x", None) is None

    original = connections.names
    connections.names = lambda: ["cluster"]
    try:
        conns = root.createChildren()
    finally:
        connections.names = original
    assert [c.name() for c in conns] == ["cluster"]
    assert conns[0].createChildren() == []
    assert [a.text() for a in conns[0].actions(None)][0] == "Refresh"

    rows = [("analytics", "parcels", "shape", "geometry"),
            ("analytics", "pts", "g1", "geometry"), ("analytics", "pts", "g2", "geography")]
    schema = browser.SchemaItem(conns[0], "analytics", rows, ctl)
    tables = schema.createChildren()
    assert [t.name() for t in tables] == ["parcels", "pts (g1)", "pts (g2)"]
    assert tables[0].source == rows[0]
    assert tables[0].path() == "redshift_spatial:/cluster/analytics/parcels/shape"
    assert tables[0].state() == QgsDataItem.Populated
    assert [a.text() for a in tables[0].actions(None)] == ["Add Layer", "Add Layer with Filter…"]


def test_plugin_registers_and_unregisters_browser_provider():
    from redshift_spatial import classFactory

    class FakeIface:
        def __getattr__(self, name):
            return lambda *a, **k: None

    registry = QgsApplication.dataItemProviderRegistry()
    plugin = classFactory(FakeIface())
    plugin.initGui()
    assert registry.provider("Redshift Spatial") is not None
    plugin.unload()
    assert registry.provider("Redshift Spatial") is None


def test_field_types_cover_sql_kinds():
    from redshift_spatial import sql

    assert set(sql._KINDS.values()) <= set(loader.FIELD_TYPES)
    assert QgsField("x", loader.FIELD_TYPES["string"]).type() == QVariant.String
