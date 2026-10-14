# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 CEOX Planejamento e Otimização
"""Shared by the dialog and the Browser panel: credentials for the session,
starting loads and adding the finished layers to the project."""

import os
import tempfile

from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureRequest,
    QgsField,
    QgsGeometry,
    QgsMessageLog,
    QgsProject,
    QgsRectangle,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QInputDialog, QMessageBox

from . import compat, connections, sources, sql
from .loader import LoadTask, QueryTask

LOG_TAG = "Redshift Spatial"
# Marks the layers a load created, so a preview can filter them later.
SOURCE_PROPERTY = "redshift_spatial/source"
FAMILIES = ("point", "line", "polygon", "collection")
ICON_PATH = os.path.join(os.path.dirname(__file__), "icon.svg")


def tr(text):
    return QCoreApplication.translate("RedshiftSpatial", text)


def icon():
    return QIcon(ICON_PATH)


def output_files(path):
    """Every file a load into path may write (see loader.FeatureSink)."""
    stem, ext = os.path.splitext(path)
    return [path] + [f"{stem}_{fam}{ext}" for fam in FAMILIES]


def free_path(path):
    stem, ext = os.path.splitext(path)
    n = 2
    while any(os.path.exists(p) for p in output_files(f"{stem}_{n}{ext}")):
        n += 1
    return f"{stem}_{n}{ext}"


class Controller:
    def __init__(self, iface):
        self.iface = iface
        self.tasks = []  # keep Python references while QGIS runs them
        self.passwords = {}  # session only, never written to disk
        self.record_layers = {}  # (label, geometry type, crs, headers) -> layer id
        self.previews = {}  # (connection, source label) -> PreviewDialog

    def parent_window(self):
        return self.iface.mainWindow() if self.iface is not None else None

    # credentials ------------------------------------------------------------
    def params(self, conn, parent=None):
        """psycopg2 parameters for a connection, asking for whatever is
        missing. Returns None if the user cancels."""
        parent = parent or self.parent_window()
        title = conn["name"] or "Redshift"
        username, password = connections.credentials(conn)
        if not username:
            username, ok = QInputDialog.getText(parent, title, tr("Username:"))
            if not ok or not username:
                return None
        if password is None:
            key = (conn["name"], username)
            password = self.passwords.get(key)
            if password is None:
                password, ok = QInputDialog.getText(
                    parent, title, tr("Password for {}:").format(username), compat.PASSWORD
                )
                if not ok:
                    return None
                self.passwords[key] = password
        return connections.params(conn, username, password)

    # loading ----------------------------------------------------------------
    def load(self, conn, source, options, parent=None):
        """options: where, limit, path ('' = temporary), fallback_crs."""
        parent = parent or self.parent_window()
        params = self.params(conn, parent)
        if params is None:
            return
        options = dict(options)
        path = (options.get("path") or "").strip()
        if not path:
            path = os.path.join(tempfile.mkdtemp(prefix="redshift_spatial_"), f"{source['name']}.gpkg")
        else:
            if not path.lower().endswith(".gpkg"):
                path += ".gpkg"
            path = self.release_output(path, parent)
            if path is None:
                return
        options["path"] = path
        task = LoadTask(params, source, options, self.task_finished)
        self.tasks.append(task)
        QgsApplication.taskManager().addTask(task)
        self.message(tr("Loading {}…").format(sources.label(source)), compat.INFO)

    def run_query(self, conn, query, label, on_done, parent=None):
        """Run a small SELECT in the background; on_done(task, ok) gets the
        headers and rows. Returns the task (to cancel it) or None."""
        params = self.params(conn, parent or self.parent_window())
        if params is None:
            return None
        QgsMessageLog.logMessage(f"{label}: {query}", LOG_TAG, compat.INFO)

        def done(task, ok):
            if task in self.tasks:
                self.tasks.remove(task)
            on_done(task, ok)

        task = QueryTask(params, query, label, done)
        self.tasks.append(task)
        QgsApplication.taskManager().addTask(task)
        return task

    def release_output(self, path, parent=None):
        """Make room for the output files. On Windows a GeoPackage still open
        by a project layer cannot be replaced, and the new layer would show
        the old content, so ask, unload those layers and delete the files.
        If QGIS still holds a file, fall back to a free name next to it.
        Returns the path to write, or None when the user cancels."""
        existing = [p for p in output_files(path) if os.path.exists(p)]
        if not existing:
            return path
        answer = QMessageBox.question(
            parent,
            tr("File exists"),
            tr("{} already exists. Replace it?\nLayers using it will be removed from the project.").format(
                os.path.basename(path)
            ),
        )
        if answer != compat.YES:
            return None
        project = QgsProject.instance()
        normalized = {os.path.normcase(os.path.abspath(p)) for p in existing}
        for layer in list(project.mapLayers().values()):
            source = layer.source().split("|")[0]
            if os.path.normcase(os.path.abspath(source)) in normalized:
                project.removeMapLayer(layer.id())
        try:
            for p in existing:
                for f in (p, p + "-wal", p + "-shm"):
                    if os.path.exists(f):
                        os.remove(f)
            return path
        except OSError:
            free = free_path(path)
            self.message(
                tr("{} is still in use; writing to {}.").format(
                    os.path.basename(path), os.path.basename(free)
                ),
                compat.WARNING,
            )
            return free

    def task_finished(self, task, ok):
        if task in self.tasks:
            self.tasks.remove(task)
        for msg in task.messages:
            QgsMessageLog.logMessage(msg, LOG_TAG, compat.WARNING)
        if task.invalid:
            QgsMessageLog.logMessage(
                f"{task.invalid} rows with invalid geometry were skipped.", LOG_TAG, compat.WARNING
            )
        label, base = task.label, task.source["name"]
        if not ok:
            if task.error is not None:
                QgsMessageLog.logMessage(str(task.error), LOG_TAG, compat.CRITICAL)
                self.message(tr("{}: {}").format(label, task.error), compat.CRITICAL)
            else:
                self.message(tr("{}: canceled.").format(label), compat.WARNING)
            return
        if not task.results:
            self.message(tr("{}: no rows.").format(label), compat.WARNING)
            return
        many = len(task.results) > 1
        for fam, path, layer_name, count in task.results:
            name = f"{base} ({fam})" if many else base
            layer = QgsVectorLayer(f"{path}|layername={layer_name}", name, "ogr")
            if layer.isValid():
                layer.setCustomProperty(SOURCE_PROPERTY, label)
                QgsProject.instance().addMapLayer(layer)
            QgsMessageLog.logMessage(f"{name}: {count} features in {path}", LOG_TAG, compat.INFO)
        total = sum(r[3] for r in task.results)
        level = compat.WARNING if task.messages or task.invalid else compat.SUCCESS
        self.message(tr("{}: {} rows loaded.").format(label, total), level)

    # records ----------------------------------------------------------------
    def show_record(self, label, headers, row, geometry_column):
        """One row; see show_records. Returns (layer, feature id) or None."""
        shown = self.show_records(label, headers, [row], geometry_column)
        if not shown:
            return None
        layer, fids = shown[0]
        return layer, fids[0]

    def show_records(self, label, headers, rows, geometry_column):
        """Put previewed rows on the map, in a temporary "(records)" layer per
        source and geometry type, select them and zoom to them all. The
        preview already holds the geometry (Redshift prints GEOMETRY as EWKB
        hex), so no key and no new query are needed.
        Returns [(layer, [feature ids])]; rows without geometry are skipped."""
        if geometry_column not in headers:
            self.message(tr("Column {} is not in the result.").format(geometry_column), compat.WARNING)
            return []
        index = headers.index(geometry_column)
        added_by_layer, skipped = {}, 0
        for row in rows:
            geom, crs = self._row_geometry(row[index])
            if geom is None:
                skipped += 1
                continue
            layer = self._record_layer(label, headers, index, geom.wkbType(), crs)
            feature = QgsFeature(layer.fields())
            feature.setAttributes([None if v is None else str(v) for i, v in enumerate(row) if i != index])
            feature.setGeometry(geom)
            ok, added = layer.dataProvider().addFeatures([feature])
            if ok and added:
                added_by_layer.setdefault(layer.id(), (layer, []))[1].append(added[0].id())
        if skipped:
            self.message(
                tr("{} row(s) without geometry in {} were skipped.").format(skipped, geometry_column),
                compat.WARNING,
            )
        shown = list(added_by_layer.values())
        for layer, fids in shown:
            layer.updateExtents()
            layer.selectByIds(fids)
        if shown and self.iface is not None:
            self._zoom_to(shown)
        return shown

    @staticmethod
    def _row_geometry(value):
        """(QgsGeometry, CRS) from an EWKB value, or (None, None)."""
        try:
            wkb, srid = sql.ewkb_to_iso(value) if value is not None else (None, 0)
        except Exception:  # noqa: BLE001 - not a geometry
            return None, None
        geom = QgsGeometry()
        if wkb:
            geom.fromWkb(wkb)
        if geom.isNull():
            return None, None
        crs = QgsCoordinateReferenceSystem(f"EPSG:{srid}") if srid else QgsCoordinateReferenceSystem()
        if not crs.isValid():
            crs = QgsCoordinateReferenceSystem("EPSG:4326")
        return geom, crs

    def _zoom_to(self, shown):
        canvas = self.iface.mapCanvas()
        if len(shown) == 1:
            layer, fids = shown[0]
            canvas.zoomToFeatureIds(layer, fids)
        else:  # several layers (geometry types): zoom to the union of extents
            target = canvas.mapSettings().destinationCrs()
            extent = QgsRectangle()
            extent.setMinimal()
            for layer, fids in shown:
                transform = QgsCoordinateTransform(layer.crs(), target, QgsProject.instance())
                for f in layer.getFeatures(QgsFeatureRequest().setFilterFids(fids)):
                    extent.combineExtentWith(transform.transformBoundingBox(f.geometry().boundingBox()))
            if not extent.isEmpty():
                canvas.setExtent(extent.buffered(max(extent.width(), extent.height()) * 0.05 or 0.001))
                canvas.refresh()
        for layer, fids in shown:
            canvas.flashFeatureIds(layer, fids)

    def clear_records(self, label):
        """Empty the "(records)" layers of a source, keeping the layers and
        their style. Returns how many features were removed."""
        removed = 0
        for key, layer_id in list(self.record_layers.items()):
            layer = QgsProject.instance().mapLayer(layer_id)
            if key[0] != label or layer is None:
                continue
            removed += layer.featureCount()
            layer.dataProvider().truncate()
            layer.updateExtents()
            layer.triggerRepaint()
        return removed

    def _record_layer(self, label, headers, geometry_index, wkb_type, crs):
        type_name = QgsWkbTypes.displayString(wkb_type)
        key = (label, type_name, crs.authid(), tuple(headers))
        layer = QgsProject.instance().mapLayer(self.record_layers.get(key, ""))
        if layer is not None:
            return layer
        layer = QgsVectorLayer(f"{type_name}?crs={crs.authid()}", tr("{} (records)").format(label), "memory")
        names = sql.unique_names([h for i, h in enumerate(headers) if i != geometry_index])
        layer.dataProvider().addAttributes([QgsField(n, compat.FIELD_TYPES["string"]) for n in names])
        layer.updateFields()
        QgsProject.instance().addMapLayer(layer)
        self.record_layers[key] = layer.id()
        return layer

    def layers_for(self, label):
        """Layers in the project that a load of this source created."""
        return [
            layer for layer in QgsProject.instance().mapLayers().values()
            if layer.customProperty(SOURCE_PROPERTY) == label
        ]

    def filter_layers(self, label, where):
        """Apply a WHERE (empty = no filter) to this source's layers, as the
        layer's own "Filter…" would. The layers are GeoPackages, so the
        expression must also be valid SQLite; simple comparisons are.
        Returns (filtered layers, layers that rejected the expression)."""
        done, failed = [], []
        layers = self.layers_for(label)
        if not layers:
            QgsMessageLog.logMessage(
                f"{label}: no layer on the map was loaded from this table (reload it to filter it).",
                LOG_TAG, compat.INFO,
            )
        for layer in layers:
            previous = layer.subsetString()
            # The OGR provider accepts any text; an expression SQLite cannot
            # run only shows up as an unknown feature count (-1).
            if layer.setSubsetString((where or "").strip()) and layer.featureCount() >= 0:
                done.append(layer)
            else:
                layer.setSubsetString(previous)
                failed.append(layer)
            layer.triggerRepaint()
        return done, failed

    def message(self, text, level):
        if self.iface is not None:
            self.iface.messageBar().pushMessage(LOG_TAG, text, level=level, duration=8)
