# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 CEOX Planejamento e Otimização
"""Tables without geometry, SQL sources, previews, the SQL window and the
column nodes of the Browser. Run through tests/run_qgis.py."""

import os
import tempfile

from qgis.core import Qgis, QgsCoordinateReferenceSystem, QgsVectorLayer

from redshift_spatial import browser, compat, connections, db, dialog, loader, sources
from redshift_spatial.controller import Controller

from helpers import FakeRedshift, hex_wkb

CONN = dict(connections.DEFAULTS, name="cluster", host="h", database="d", list_all_tables=True)


def run_load(fake, source, **options):
    original = db.connect
    db.connect = fake.connect
    try:
        opts = {"where": "", "limit": 0, "path": os.path.join(tempfile.mkdtemp(), "out.gpkg"),
                "fallback_crs": QgsCoordinateReferenceSystem("EPSG:3857")}
        opts.update(options)
        task = loader.LoadTask({}, source, opts, lambda *a: None)
        ok = task.run()
    finally:
        db.connect = original
    return task, ok


def layer_of(result):
    fam, path, name, count = result
    layer = QgsVectorLayer(f"{path}|layername={name}", fam, "ogr")
    assert layer.isValid(), path
    return layer


class SyncController(Controller):
    """Runs queries synchronously against a fake and records loads."""

    def __init__(self, fake):
        super().__init__(None)
        self.fake = fake
        self.loads = []
        self.queries = []

    def params(self, conn, parent=None):
        return {}

    def run_query(self, conn, query, label, on_done, parent=None):
        self.queries.append(query)
        original = db.connect
        db.connect = self.fake.connect
        try:
            task = loader.QueryTask({}, query, label, lambda *a: None)
            ok = task.run()
        finally:
            db.connect = original
        on_done(task, ok)
        return task

    def load(self, conn, source, options, parent=None):
        self.loads.append((source, options))


# loading -----------------------------------------------------------------------------


def test_table_without_geometry_becomes_a_plain_table():
    fake = FakeRedshift([("code", "integer"), ("label", "character varying(50)")],
                        [(1, "a"), (2, "b"), (3, None)])
    task, ok = run_load(fake, sources.table("analytics", "lookup"), where="code > 0")
    assert ok, task.error
    (result,) = task.results
    assert result[0] == "table" and result[3] == 3
    layer = layer_of(result)
    assert layer.wkbType() == compat.NO_GEOMETRY
    assert [f["label"] for f in layer.getFeatures()] == ["a", "b", None]
    queries = [q for q, _ in fake.queries]
    assert not any(q.startswith("SELECT ST_SRID") for q in queries)
    data = [q for q in queries if q.startswith("DECLARE")][0]
    assert "ST_AsBinary" not in data and data.endswith('FROM "analytics"."lookup" WHERE (code > 0)')


def test_query_with_geometry_column():
    description = [("id", 23), ("name", 1043), ("doc", 4000), ("g", 3000)]
    rows = [(1, "x", '{"a": 1}', hex_wkb("POINT(1 2)")), (2, "y", None, hex_wkb("POINT(3 4)"))]
    fake = FakeRedshift([], rows, description=description)
    sql_text = "SELECT p.id, p.name, p.doc, p.g FROM analytics.parcels p;"
    task, ok = run_load(fake, sources.query(sql_text, "g", "my query"), limit=10)
    assert ok, task.error
    (result,) = task.results
    layer = layer_of(result)
    assert result[2] == "my query" and layer.featureCount() == 2
    assert [f.name() for f in layer.fields()][-3:] == ["id", "name", "doc"]
    assert layer.crs().authid() == "EPSG:4326"
    data = [q for q, _ in fake.queries if q.startswith("DECLARE")][0]
    assert '"id", "name", "doc", ST_AsBinary("g") FROM (SELECT p.id, p.name, p.doc, p.g FROM analytics.parcels p) AS q' in data
    assert data.endswith("LIMIT 10")


def test_query_without_geometry():
    fake = FakeRedshift([], [(10, 2.5)], description=[("n", 20), ("avg", 1700)])
    task, ok = run_load(fake, sources.query("SELECT COUNT(*) n, AVG(x) avg FROM t", None, "stats"))
    assert ok, task.error
    f = next(layer_of(task.results[0]).getFeatures())
    assert f["n"] == 10 and f["avg"] == 2.5


def test_query_error_is_reported():
    fake = FakeRedshift([], [], description=[("a", 23)], fail_on="LIMIT 0",
                        error=RuntimeError('relation "nope" does not exist'))
    task, ok = run_load(fake, sources.query("SELECT a FROM nope"))
    assert not ok and "does not exist" in str(task.error)


# queries and listings -------------------------------------------------------------------


def test_query_task_returns_headers_and_rows():
    fake = FakeRedshift([("a", "integer"), ("b", "text")], [(1, "x"), (2, "y"), (3, "z")])
    ctl = SyncController(fake)
    seen = {}
    ctl.run_query(CONN, 'SELECT * FROM "s"."t" LIMIT 2', "t", lambda t, ok: seen.update(ok=ok, t=t))
    assert seen["ok"] and seen["t"].headers == ["a", "b"] and seen["t"].rows == [(1, "x"), (2, "y")]


def test_query_task_cancel_reaches_the_server():
    fake = FakeRedshift([], [])
    task = loader.QueryTask({}, "SELECT 1", "x", lambda *a: None)
    task._conn = fake.connect({})
    task.cancel()
    assert fake.canceled == 1 and task.isCanceled()


def test_list_tables_merges_spatial_and_plain():
    fake = FakeRedshift([], [], spatial=[("b", "parcels", "shape", "geometry")],
                        plain=[("a", "lookup"), ("b", "codes")])
    original = db.connect
    db.connect = fake.connect
    try:
        only_spatial = db.list_tables({}, include_plain=False)
        everything = db.list_tables({}, include_plain=True)
    finally:
        db.connect = original
    assert only_spatial == [("b", "parcels", "shape", "geometry")]
    assert everything == [("a", "lookup", None, None), ("b", "codes", None, None),
                          ("b", "parcels", "shape", "geometry")]


# dialogs ---------------------------------------------------------------------------------


def test_display_summarizes_geometry_and_long_text():
    assert dialog.display(None) == "NULL"
    assert dialog.display(hex_wkb("POINT(1 2)")).startswith("<WKB/binary, ")
    assert dialog.display("x" * 500).endswith("…") and len(dialog.display("x" * 500)) == dialog.CELL_CHARS + 1
    assert dialog.display(3.5) == "3.5"


def test_preview_dialog_shows_first_rows():
    fake = FakeRedshift([("id", "integer"), ("shape", "geometry")],
                        [(i, hex_wkb(f"POINT({i} {i})")) for i in range(150)])
    ctl = SyncController(fake)
    dlg = dialog.PreviewDialog(ctl, CONN, sources.table("analytics", "parcels", "shape"))
    assert ctl.queries == ['SELECT * FROM "analytics"."parcels" LIMIT 100']
    assert dlg.table.rowCount() == 100 and dlg.table.columnCount() == 2
    assert dlg.table.item(0, 1).text().startswith("<WKB/binary")


def test_sql_dialog_runs_guesses_geometry_and_loads():
    rows = [(1, "a", hex_wkb("POINT(0 0)")), (2, "b", hex_wkb("POINT(1 1)"))]
    fake = FakeRedshift([], rows, description=[("id", 23), ("name", 1043), ("geom", 3000)])
    ctl = SyncController(fake)
    original = connections.names, connections.load
    connections.names = lambda: ["cluster"]
    connections.load = lambda name: dict(CONN, name=name)
    try:
        dlg = dialog.SqlDialog(ctl, "cluster")
        dlg.editor.setPlainText("SELECT id, name, geom FROM analytics.parcels;")
        dlg.execute()
        assert ctl.queries[-1] == "SELECT * FROM (SELECT id, name, geom FROM analytics.parcels) AS q LIMIT 200"
        assert dlg.table.rowCount() == 2
        assert dlg.geometry.currentText() == "geom"
        dlg.layer_name.setText("parcels north")
        dlg.load()
        source, options = ctl.loads[-1]
        assert source == sources.query("SELECT id, name, geom FROM analytics.parcels", "geom", "parcels north")
        dlg.geometry.setCurrentText(dialog.SqlDialog.NO_GEOMETRY)
        dlg.load()
        assert ctl.loads[-1][0]["column"] is None
    finally:
        connections.names, connections.load = original


def test_sql_dialog_reports_errors():
    fake = FakeRedshift([], [], fail_on="LIMIT 200", error=RuntimeError('syntax error at or near "SELEC"'))
    ctl = SyncController(fake)
    original = connections.names, connections.load
    connections.names = lambda: ["cluster"]
    connections.load = lambda name: dict(CONN, name=name)
    try:
        dlg = dialog.SqlDialog(ctl, "cluster")
        dlg.editor.setPlainText("SELEC 1")
        dlg.execute()
        assert "syntax error" in dlg.status.text()
        assert dlg.run_button.isEnabled()
    finally:
        connections.names, connections.load = original


def test_guess_geometry_column():
    rows = [(1, None, hex_wkb("POINT(0 0)")), (2, None, None)]
    assert dialog.guess_geometry_column(["id", "x", "g"], rows) == "g"
    assert dialog.guess_geometry_column(["id"], [(1,)]) is None


def test_connection_dialog_has_list_all_option():
    dlg = dialog.ConnectionDialog(Controller(None), conn=dict(CONN))
    assert dlg.data()["list_all_tables"] is True
    dlg.list_all.setChecked(False)
    assert dlg.data()["list_all_tables"] is False


# browser ----------------------------------------------------------------------------------


def test_browser_lists_plain_tables_and_columns():
    ctl = Controller(None)
    ctl.params = lambda conn, parent=None: {}
    original = (connections.names, connections.load, db.list_tables, db.list_columns)
    connections.names = lambda: ["cluster"]
    connections.load = lambda name: dict(CONN, name=name)
    db.list_tables = lambda params, include_plain=False: [
        ("analytics", "lookup", None, None), ("analytics", "parcels", "shape", "geometry")
    ] if include_plain else [("analytics", "parcels", "shape", "geometry")]
    db.list_columns = lambda params, schema, table: [("id", "integer"), ("label", "character varying(50)"),
                                                      ("shape", "geometry"), ("ts", "timestamp with time zone")]
    try:
        root = browser.RedshiftSpatialItemProvider(ctl).createDataItem("", None)
        (conn_item,) = root.createChildren()
        (schema_item,) = conn_item.createChildren()
        tables = schema_item.createChildren()
        assert [t.name() for t in tables] == ["lookup", "parcels"]
        lookup, parcels = tables
        assert lookup.source["column"] is None and parcels.source["column"] == "shape"
        columns = parcels.createChildren()
        assert [c.name() for c in columns] == ["id", "label", "shape", "ts"]
        assert columns[2].toolTip() == "shape: geometry"
        assert all(c.state() == Qgis.BrowserItemState.Populated for c in columns)
        assert "Preview Rows…" in [a.text() for a in lookup.actions(None)]
    finally:
        connections.names, connections.load, db.list_tables, db.list_columns = original


def test_closing_dialogs_after_the_task_was_deleted():
    """QGIS deletes a finished task's C++ object; closing the preview or the
    SQL window afterwards must not raise."""
    from qgis.PyQt import sip

    task = loader.QueryTask({}, "SELECT 1", "x", lambda *a: None)
    sip.delete(task)
    dialog.cancel_task(task)  # no RuntimeError
    dialog.cancel_task(None)

    fake = FakeRedshift([("id", "integer")], [(1,)])
    ctl = SyncController(fake)
    preview = dialog.PreviewDialog(ctl, CONN, sources.table("s", "t"))
    assert preview.task is None  # cleared when the result arrived
    stale = loader.QueryTask({}, "SELECT 1", "x", lambda *a: None)
    sip.delete(stale)
    preview.task = stale
    preview.reject()

    original = connections.names, connections.load
    connections.names = lambda: ["cluster"]
    connections.load = lambda name: dict(CONN, name=name)
    try:
        window = dialog.SqlDialog(ctl, "cluster")
        window.editor.setPlainText("SELECT 1")
        window.execute()
        assert window.task is None and not window.cancel_button.isEnabled()
        window.task = stale
        window.reject()
    finally:
        connections.names, connections.load = original


# filters and records ------------------------------------------------------------------


def ewkb_hex(wkt, srid):
    """EWKB with an embedded SRID, the way Redshift prints GEOMETRY."""
    import struct

    from qgis.core import QgsGeometry

    iso = bytes(QgsGeometry.fromWkt(wkt).asWkb())
    (kind,) = struct.unpack("<I", iso[1:5])
    return (iso[:1] + struct.pack("<II", kind | 0x20000000, srid) + iso[5:]).hex()


def test_results_table_sorts_numbers_and_filters():
    table = dialog.ResultsTable()
    table.set_result(["id", "name"], [(10, "beta"), (9, "alpha"), (100, "Gamma")])
    assert [table.item(r, 0).text() for r in range(3)] == ["10", "9", "100"]  # server order kept
    table.sortItems(0, compat.ASCENDING)
    assert [table.raw_row(table.item(r, 0))[0] for r in range(3)] == [9, 10, 100]  # numeric, not text
    assert table.apply_filter("GAM") == 1
    assert table.apply_filter("a", column=1) == 3
    assert table.apply_filter("1", column=0) == 2
    assert table.apply_filter("") == 3

    bar = dialog.FilterBar(table)
    bar.set_columns(["id", "name"])
    bar.column.setCurrentText("name")
    bar.text.setText("alp")
    assert sum(not table.isRowHidden(r) for r in range(3)) == 1


def test_preview_where_and_limit_rerun_on_the_server():
    fake = FakeRedshift([("id", "integer")], [(i,) for i in range(5)])
    ctl = SyncController(fake)
    dlg = dialog.PreviewDialog(ctl, CONN, sources.table("s", "t"))
    dlg.where.setText("id > 2")
    dlg.limit.setValue(3)
    dlg.run()
    assert ctl.queries[-1] == 'SELECT * FROM "s"."t" WHERE (id > 2) LIMIT 3'
    assert dlg.task is None and dlg.status.text() == "3 rows."


def test_show_record_puts_the_row_on_the_map():
    from qgis.core import QgsProject

    ctl = Controller(None)
    headers = ["id", "name", "shape"]
    layer, fid = ctl.show_record("s.parcels", headers, (1, "a", ewkb_hex("POLYGON((0 0,1 0,1 1,0 0))", 4674)), "shape")
    assert layer.crs().authid() == "EPSG:4674" and layer.featureCount() == 1
    assert layer.selectedFeatureIds() == [fid]
    assert [f.name() for f in layer.fields()] == ["id", "name"]
    f = layer.getFeature(fid)
    assert f["name"] == "a" and f.geometry().area() == 0.5
    again, _ = ctl.show_record("s.parcels", headers, (2, "b", ewkb_hex("POLYGON((0 0,2 0,2 2,0 0))", 4674)), "shape")
    assert again.id() == layer.id() and layer.featureCount() == 2
    assert ctl.show_record("s.parcels", headers, (3, "c", None), "shape") is None
    assert ctl.show_record("s.parcels", headers, (3, "c", "not a geometry"), "shape") is None
    assert ctl.show_record("s.parcels", headers, (3, "c", None), "missing") is None
    QgsProject.instance().removeAllMapLayers()


def test_double_click_in_preview_and_sql_window():
    from qgis.core import QgsProject

    rows = [(1, ewkb_hex("POINT(5 6)", 4326)), (2, ewkb_hex("POINT(7 8)", 4326))]
    fake = FakeRedshift([("id", "integer"), ("shape", "geometry")], rows,
                        description=[("id", 23), ("shape", 3000)])
    ctl = SyncController(fake)
    preview = dialog.PreviewDialog(ctl, CONN, sources.table("s", "pts", "shape"))
    preview.show_on_map(preview.table.item(1, 0))
    (layer,) = QgsProject.instance().mapLayersByName("s.pts (records)")
    assert next(layer.getFeatures()).geometry().asWkt() == "Point (7 8)"

    plain = dialog.PreviewDialog(ctl, CONN, sources.table("s", "lookup"))
    plain.show_on_map(plain.table.item(0, 0))
    assert "no geometry" in plain.status.text()

    original = connections.names, connections.load
    connections.names = lambda: ["cluster"]
    connections.load = lambda name: dict(CONN, name=name)
    try:
        window = dialog.SqlDialog(ctl, "cluster")
        window.editor.setPlainText("SELECT id, shape FROM s.pts")
        window.execute()
        window.layer_name.setText("my pts")
        window.show_on_map(window.table.item(0, 0))
        assert QgsProject.instance().mapLayersByName("my pts (records)")
        window.geometry.setCurrentText(dialog.SqlDialog.NO_GEOMETRY)
        window.show_on_map(window.table.item(0, 0))
        assert "geometry column" in window.status.text()
    finally:
        connections.names, connections.load = original
        QgsProject.instance().removeAllMapLayers()


def test_preview_filter_also_filters_the_tables_layers_on_the_map():
    from qgis.core import QgsProject

    rows = [(i, f"code-{i}", hex_wkb(f"POINT({i} {i})")) for i in range(6)]
    fake = FakeRedshift([("id", "integer"), ("code", "character varying(20)"), ("shape", "geometry")], rows)
    source = sources.table("s", "parcels", "shape")
    task, ok = run_load(fake, source)
    ctl = SyncController(fake)
    Controller.task_finished(ctl, task, ok)
    (layer,) = ctl.layers_for("s.parcels")
    assert layer.featureCount() == 6

    dlg = dialog.PreviewDialog(ctl, CONN, source)
    dlg.where.setText("code = 'code-3'")
    dlg.run()
    assert layer.subsetString() == "code = 'code-3'" and layer.featureCount() == 1
    assert "1 layer(s) filtered" in dlg.status.text()

    dlg.where.setText("code ~ '^code-3$'")  # POSIX regex: valid in Redshift, not in SQLite
    dlg.run()
    assert "did not accept" in dlg.status.text()
    assert layer.subsetString() == "code = 'code-3'" and layer.featureCount() == 1  # previous kept

    dlg.where.setText("")
    dlg.run()
    assert layer.subsetString() == "" and layer.featureCount() == 6

    dlg.filter_map.setChecked(False)
    dlg.where.setText("id = 1")
    dlg.run()
    assert layer.subsetString() == ""
    QgsProject.instance().removeAllMapLayers()


def test_preview_error_clears_the_old_rows():
    fake = FakeRedshift([("id", "integer")], [(i,) for i in range(5)])
    ctl = SyncController(fake)
    dlg = dialog.PreviewDialog(ctl, CONN, sources.table("s", "t"))
    assert dlg.table.rowCount() == 5
    fake.fail_on = "WHERE"
    fake.error = RuntimeError('column "MT-1" does not exist')
    dlg.where.setText('codigo = "MT-1"')
    dlg.run()
    assert dlg.table.rowCount() == 0
    assert dlg.status.text().startswith("Query failed:") and "does not exist" in dlg.status.text()
    fake.fail_on = None
    dlg.where.setText("WHERE id = 2")
    dlg.run()
    assert ctl.queries[-1] == 'SELECT * FROM "s"."t" WHERE (id = 2) LIMIT 100'


def test_preview_ignores_results_of_superseded_queries():
    """Two runs in a row (Enter + Apply): only the latest may fill the grid."""
    fake = FakeRedshift([("id", "integer")], [(i,) for i in range(5)])
    ctl = SyncController(fake)
    pending = []

    def deferred(conn, query, label, on_done, parent=None):
        task = loader.QueryTask({}, query, label, lambda *a: None)
        pending.append((task, on_done, query))
        return task

    dlg = dialog.PreviewDialog(ctl, CONN, sources.table("s", "t"))
    ctl.run_query = deferred
    dlg.where.setText("id = 1")
    dlg.run()
    dlg.where.setText("id = 2")
    dlg.run()
    (old, old_done, _), (new, new_done, new_query) = pending
    new.headers, new.rows = ["id"], [(2,)]
    new_done(new, True)
    old_done(old, False)  # the canceled first query reports last
    assert dlg.table.rowCount() == 1 and dlg.table.raw_row(dlg.table.item(0, 0)) == (2,)
    assert new_query.endswith("WHERE (id = 2) LIMIT 100")


def test_preview_from_the_add_layer_window_uses_its_filter():
    fake = FakeRedshift([("id", "integer")], [(1,)])
    ctl = SyncController(fake)
    dlg = dialog.PreviewDialog(ctl, CONN, sources.table("s", "t"), where="id = 1")
    assert dlg.where.text() == "id = 1"
    assert ctl.queries[-1] == 'SELECT * FROM "s"."t" WHERE (id = 1) LIMIT 100'


def test_preview_window_is_reused_per_table():
    fake = FakeRedshift([("id", "integer")], [(i,) for i in range(3)])
    ctl = SyncController(fake)
    first = dialog.open_preview(ctl, CONN, sources.table("s", "t"))
    again = dialog.open_preview(ctl, CONN, sources.table("s", "t"))
    assert again is first and len(ctl.queries) == 1
    first.reject()
    assert not first.isVisible()
    reopened = dialog.open_preview(ctl, CONN, sources.table("s", "t"), where="id = 1")
    assert reopened is first and reopened.isVisible()
    assert ctl.queries[-1].endswith("WHERE (id = 1) LIMIT 100")
    other = dialog.open_preview(ctl, CONN, sources.table("s", "u"))
    assert other is not first
    for dlg in (first, other):
        dlg.reject()


def test_close_button_closes_the_preview():
    from qgis.PyQt.QtWidgets import QDialogButtonBox

    fake = FakeRedshift([("id", "integer")], [(1,)])
    dlg = dialog.open_preview(SyncController(fake), CONN, sources.table("s", "t"))
    assert dlg.isVisible()
    (box,) = dlg.findChildren(QDialogButtonBox)
    (close,) = [b for b in box.buttons() if box.buttonRole(b) == compat.REJECT_ROLE]
    close.click()
    assert not dlg.isVisible()


def test_show_selected_rows_on_the_map():
    from qgis.core import QgsProject
    from qgis.PyQt.QtCore import QItemSelectionModel

    rows = [(1, ewkb_hex("POINT(1 1)", 4326)), (2, ewkb_hex("POINT(2 2)", 4326)),
            (3, None), (4, ewkb_hex("LINESTRING(0 0,5 5)", 4326))]
    fake = FakeRedshift([("id", "integer"), ("shape", "geometry")], rows)
    ctl = SyncController(fake)
    dlg = dialog.open_preview(ctl, CONN, sources.table("s", "multi", "shape"))
    dlg.show_selected_on_map()
    assert "Select one or more rows" in dlg.status.text()

    dlg.table.selectAll()
    dlg.filter.text.setText("")  # nothing hidden
    assert [r[0] for r in dlg.table.selected_rows()] == [1, 2, 3, 4]
    dlg.show_selected_on_map()
    layers = QgsProject.instance().mapLayersByName("s.multi (records)")
    points = [l for l in layers if l.geometryType() == compat.POINT_GEOMETRY]
    lines = [l for l in layers if l.geometryType() == compat.LINE_GEOMETRY]
    assert points[0].featureCount() == 2 and len(points[0].selectedFeatureIds()) == 2
    assert lines[0].featureCount() == 1

    # a quick filter hides rows: hidden rows are not shown on the map
    dlg.table.clearSelection()
    dlg.filter.column.setCurrentText("id")
    dlg.filter.text.setText("2")
    dlg.table.selectAll()
    assert [r[0] for r in dlg.table.selected_rows()] == [2]

    shown = ctl.show_records("s.multi", ["id", "shape"], [rows[2]], "shape")
    assert shown == []
    dlg.reject()
    QgsProject.instance().removeAllMapLayers()


def test_zoom_covers_rows_of_every_geometry_type():
    from qgis.core import QgsProject
    from qgis.gui import QgsMapCanvas

    class Bar:
        def pushMessage(self, *a, **k):
            pass

    class Iface:
        def __init__(self):
            self.canvas = QgsMapCanvas()
            self.canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
            self.canvas.resize(400, 400)

        def mapCanvas(self):
            return self.canvas

        def messageBar(self):
            return Bar()

        def mainWindow(self):
            return None

    ctl = Controller(Iface())
    rows = [(1, ewkb_hex("POINT(-50 -10)", 4326)), (2, ewkb_hex("LINESTRING(10 20,30 40)", 4326))]
    shown = ctl.show_records("s.zoom", ["id", "shape"], rows, "shape")
    assert len(shown) == 2
    extent = ctl.iface.canvas.extent()
    assert extent.xMinimum() <= -50 and extent.xMaximum() >= 30
    assert extent.yMinimum() <= -10 and extent.yMaximum() >= 40
    (layer, fids), = ctl.show_records("s.zoom", ["id", "shape"], rows[:1], "shape")
    assert ctl.iface.canvas.extent().contains(layer.getFeature(fids[0]).geometry().asPoint())
    QgsProject.instance().removeAllMapLayers()


def test_clear_records_empties_only_that_sources_layers():
    from qgis.core import QgsProject

    ctl = Controller(None)
    pts = [(1, ewkb_hex("POINT(1 1)", 4326)), (2, ewkb_hex("LINESTRING(0 0,1 1)", 4326))]
    ctl.show_records("s.a", ["id", "shape"], pts, "shape")
    ctl.show_records("s.b", ["id", "shape"], pts[:1], "shape")
    assert ctl.clear_records("s.a") == 2
    a_layers = QgsProject.instance().mapLayersByName("s.a (records)")
    assert len(a_layers) == 2 and all(l.featureCount() == 0 for l in a_layers)  # layers kept
    (b,) = QgsProject.instance().mapLayersByName("s.b (records)")
    assert b.featureCount() == 1
    ctl.show_records("s.a", ["id", "shape"], pts[:1], "shape")
    assert sum(l.featureCount() for l in a_layers) == 1  # same layer reused after clearing
    assert ctl.clear_records("nothing here") == 0
    QgsProject.instance().removeAllMapLayers()


def test_preview_add_layer_uses_the_current_where():
    fake = FakeRedshift([("id", "integer"), ("shape", "geometry")], [(1, ewkb_hex("POINT(1 1)", 4326))])
    ctl = SyncController(fake)
    dlg = dialog.open_preview(ctl, CONN, sources.table("s", "addlayer", "shape"))
    dlg.where.setText("WHERE id = 1;")
    original = dialog.LoadOptionsDialog.exec
    captured = {}

    def accept(self):
        captured["where"] = self.form.where.text()
        return True

    dialog.LoadOptionsDialog.exec = accept
    try:
        dlg.add_layer()
    finally:
        dialog.LoadOptionsDialog.exec = original
    assert captured["where"] == "id = 1"
    source, options = ctl.loads[-1]
    assert source == sources.table("s", "addlayer", "shape") and options["where"] == "id = 1"

    dlg.clear_records()
    assert "record(s) removed" in dlg.status.text()
    dlg.reject()


def test_save_selected_rows_keeps_types_and_geometry():
    from datetime import date
    from decimal import Decimal

    from qgis.core import QgsProject

    ctl = Controller(None)
    headers = ["id", "area", "day", "name", "shape"]
    rows = [(1, Decimal("2.5"), date(2026, 1, 2), "a", ewkb_hex("POLYGON((0 0,1 0,1 1,0 0))", 4674)),
            (2, Decimal("3.5"), None, None, ewkb_hex("POLYGON((0 0,2 0,2 2,0 0))", 4674)),
            (3, None, None, "no geometry", None)]
    (layer,) = ctl.save_rows("s.parcels", headers, rows, "shape")
    assert layer.name() == "s.parcels (selected)" and layer.featureCount() == 2
    assert layer.crs().authid() == "EPSG:4674"
    assert [f.name() for f in layer.fields()][-4:] == ["id", "area", "day", "name"]
    f = sorted(layer.getFeatures(), key=lambda f: f["id"])[0]
    assert f["id"] == 1 and f["area"] == 2.5 and f["day"].toString("yyyy-MM-dd") == "2026-01-02"
    assert layer.source().endswith("layername=s_parcels__selected")
    assert ctl.layers_for("s.parcels") == [layer]  # the preview's map filter reaches it too

    (table,) = ctl.save_rows("s.lookup", ["code", "label"], [(1, "x"), (2, "y")])
    assert table.featureCount() == 2 and table.wkbType() == compat.NO_GEOMETRY
    QgsProject.instance().removeAllMapLayers()


def test_add_layer_asks_when_rows_are_selected():
    from qgis.core import QgsProject

    rows = [(i, ewkb_hex(f"POINT({i} {i})", 4326)) for i in range(5)]
    fake = FakeRedshift([("id", "integer"), ("shape", "geometry")], rows)
    ctl = SyncController(fake)
    dlg = dialog.open_preview(ctl, CONN, sources.table("s", "scope", "shape"))
    assert dlg.add_button.text() == "Add Layer (all matching)…"
    dlg.table.selectRow(1)
    assert dlg.add_button.text() == "Add Layer (1 selected)…"

    answers = []
    original = dialog.ask_scope
    dialog.ask_scope = lambda parent, n: answers.append(n) or dialog.SELECTED
    try:
        dlg.add_layer()
        assert answers == [1]
        (saved,) = QgsProject.instance().mapLayersByName("s.scope (selected)")
        assert saved.featureCount() == 1 and next(saved.getFeatures())["id"] == 1
        assert not ctl.loads  # nothing queried again

        dialog.ask_scope = lambda parent, n: None  # cancel
        dlg.add_layer()
        assert not ctl.loads

        dialog.ask_scope = lambda parent, n: dialog.ALL
        accept = dialog.LoadOptionsDialog.exec
        dialog.LoadOptionsDialog.exec = lambda self: True
        try:
            dlg.add_layer()
        finally:
            dialog.LoadOptionsDialog.exec = accept
        assert ctl.loads and ctl.loads[-1][0] == sources.table("s", "scope", "shape")
    finally:
        dialog.ask_scope = original
        dlg.reject()
        QgsProject.instance().removeAllMapLayers()


def test_ask_scope_dialog_builds_and_cancel_returns_none():
    from qgis.PyQt.QtWidgets import QMessageBox

    seen = {}
    original = QMessageBox.exec

    def fake_exec(box):
        seen["buttons"] = [b.text() for b in box.buttons()]
        return 0

    QMessageBox.exec = fake_exec
    try:
        assert dialog.ask_scope(None, 3) is None  # closed without a choice
    finally:
        QMessageBox.exec = original
    assert "Only the 3 selected" in seen["buttons"] and "All matching rows" in seen["buttons"]
    assert dialog.scope_label(0) == "Add Layer (all matching)…"
    assert dialog.scope_label(3) == "Add Layer (3 selected)…"
