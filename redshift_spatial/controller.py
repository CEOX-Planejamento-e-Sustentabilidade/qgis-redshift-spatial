# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 CEOX Planejamento e Otimização
"""Shared by the dialog and the Browser panel: credentials for the session,
starting loads and adding the finished layers to the project."""

import json
import os
import tempfile
import uuid

from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureRequest,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsLayerTreeLayer,
    QgsMessageLog,
    QgsProject,
    QgsRectangle,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QInputDialog, QMessageBox
from qgis.PyQt.QtXml import QDomDocument

from . import compat, connections, sources, sql
from .compat import QAction
from .i18n import tr
from .loader import FeatureSink, LoadTask, QueryTask

LOG_TAG = "Redshift Spatial"
# Marks the layers a load created, so a preview can filter them later.
SOURCE_PROPERTY = "redshift_spatial/source"
# How a layer was loaded (connection, source, filter, limit), so that it can
# be edited and loaded again in place. JSON; saved with the project.
ORIGIN_PROPERTY = "redshift_spatial/origin"
# the name the plugin gave the layer, to tell a rename by the user
AUTO_NAME_PROPERTY = "redshift_spatial/auto_name"
FAMILIES = ("point", "line", "polygon", "collection")
ICON_PATH = os.path.join(os.path.dirname(__file__), "icon.svg")



def icon():
    return QIcon(ICON_PATH)


def output_files(path):
    """Every file a load into path may write (see loader.FeatureSink)."""
    stem, ext = os.path.splitext(path)
    return [path] + [f"{stem}_{fam}{ext}" for fam in FAMILIES]


def origin_of(layer):
    """The ORIGIN_PROPERTY of a layer as a dict, or None."""
    try:
        origin = json.loads(layer.customProperty(ORIGIN_PROPERTY) or "")
    except (TypeError, ValueError):
        return None
    return origin if isinstance(origin, dict) and "source" in origin else None


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
        self.edit_action = None

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
    def load(self, conn, source, options, parent=None, replace=None):
        """options: where, limit, path ('' = temporary), fallback_crs.
        replace: the load id of layers this load replaces once it succeeds
        (see edit_layer)."""
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
        crs = options.get("fallback_crs")
        task.origin = {
            "connection": conn["name"],
            "source": source,
            "where": options.get("where") or "",
            "limit": options.get("limit") or 0,
            "crs": crs.authid() if crs is not None and crs.isValid() else "",
            "load_id": replace or uuid.uuid4().hex,
        }
        task.replace = replace
        self.message(tr("Loading {}…").format(sources.label(source)), compat.INFO)
        self._start(task)

    def _start(self, task):
        self.tasks.append(task)
        QgsApplication.taskManager().addTask(task)

    def run_query(self, conn, query, label, on_done, parent=None, count_query=None):
        """Run a small SELECT in the background; on_done(task, ok) gets the
        headers and rows. Returns the task (to cancel it) or None."""
        params = self.params(conn, parent or self.parent_window())
        if params is None:
            return None
        for text in (query, count_query):
            if text:
                QgsMessageLog.logMessage(f"{label}: {text}", LOG_TAG, compat.INFO)

        def done(task, ok):
            if task in self.tasks:
                self.tasks.remove(task)
            on_done(task, ok)

        task = QueryTask(params, query, label, done, count_query)
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
        origin = getattr(task, "origin", None)
        layers = []
        for fam, path, layer_name, count in task.results:
            name = f"{base} ({fam})" if many else base
            if origin is not None and task.source["kind"] == "table":
                name = sources.layer_name(name, origin["where"])
            layer = QgsVectorLayer(f"{path}|layername={layer_name}", name, "ogr")
            if layer.isValid():
                layer.setCustomProperty(SOURCE_PROPERTY, label)
                if origin is not None:
                    layer.setCustomProperty(ORIGIN_PROPERTY, json.dumps(origin))
                    layer.setCustomProperty(AUTO_NAME_PROPERTY, name)
                    compat.set_abstract(layer, sources.describe(origin))
                layers.append(layer)
            QgsMessageLog.logMessage(f"{name}: {count} features in {path}", LOG_TAG, compat.INFO)
        self._add_layers(layers, self.layers_of_load(getattr(task, "replace", None)))
        total = sum(r[3] for r in task.results)
        level = compat.WARNING if task.messages or task.invalid else compat.SUCCESS
        self.message(tr("{}: {} rows loaded.").format(label, total), level)

    def _add_layers(self, layers, old):
        """Add the new layers; when they replace old ones, put them where the
        old ones were in the Layers panel, keep the style and any name the
        user gave them (same geometry type), then remove the old ones. A
        name the plugin gave follows the new filter."""
        project = QgsProject.instance()
        if not old:
            for layer in layers:
                project.addMapLayer(layer)
            return
        group, index = project.layerTreeRoot(), 0
        node = group.findLayer(old[0].id())
        if node is not None:
            group = node.parent()
            index = next(
                i for i, child in enumerate(group.children())
                if isinstance(child, QgsLayerTreeLayer) and child.layerId() == old[0].id()
            )
        by_type = {layer.geometryType(): layer for layer in old}
        for offset, layer in enumerate(layers):
            previous = by_type.get(layer.geometryType())
            if previous is not None:
                copy_style(previous, layer)
                if previous.name() != previous.customProperty(AUTO_NAME_PROPERTY):
                    layer.setName(previous.name())
            project.addMapLayer(layer, False)
            group.insertLayer(index + offset, layer)
        project.removeMapLayers([layer.id() for layer in old])

    def layers_of_load(self, load_id):
        if not load_id:
            return []
        return [
            layer for layer in QgsProject.instance().mapLayers().values()
            if (origin_of(layer) or {}).get("load_id") == load_id
        ]

    # editing a loaded layer ---------------------------------------------------
    def install_layer_action(self):
        """"Edit Redshift Query…" in the Layers panel context menu of the
        layers this plugin loaded (also those of a project opened later)."""
        if self.iface is None:
            return
        self.edit_action = QAction(icon(), tr("Edit Redshift Query…"), self.iface.mainWindow())
        self.edit_action.triggered.connect(self.edit_current_layer)
        self.iface.addCustomActionForLayerType(self.edit_action, "", compat.VECTOR_LAYER, False)
        QgsProject.instance().layersAdded.connect(self.register_layers)
        self.register_layers(QgsProject.instance().mapLayers().values())

    def remove_layer_action(self):
        if self.edit_action is None:
            return
        try:
            QgsProject.instance().layersAdded.disconnect(self.register_layers)
        except TypeError:
            pass
        self.iface.removeCustomActionForLayerType(self.edit_action)
        self.edit_action = None

    def register_layers(self, layers):
        for layer in layers:
            if origin_of(layer) is not None:
                self.iface.addCustomActionForLayer(self.edit_action, layer)

    def edit_current_layer(self):
        layer = self.iface.layerTreeView().currentLayer()
        if layer is not None:
            self.edit_layer(layer)

    def edit_layer(self, layer, parent=None):
        """Open the query (SQL window) or the load options (table) a layer
        came from; loading again replaces the layer in place. Returns the
        dialog, or None."""
        origin = origin_of(layer)
        if origin is None:
            self.message(tr("{} was not loaded by Redshift Spatial.").format(layer.name()), compat.WARNING)
            return None
        if origin["connection"] not in connections.names():
            self.message(tr("Connection {} no longer exists.").format(origin["connection"]), compat.WARNING)
            return None
        from .dialog import edit_origin  # the dialogs import this module

        return edit_origin(self, origin, parent or self.parent_window())

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

    def save_rows(self, label, headers, rows, geometry_column=None, path=None):
        """Write rows already fetched (e.g. the selected preview rows) to a
        GeoPackage and add it to the project, without querying Redshift
        again. Column types are inferred from the values. Returns the layers
        added."""
        geometry_index = headers.index(geometry_column) if geometry_column in headers else None
        attr_index = [i for i in range(len(headers)) if i != geometry_index]
        kinds = [sql.infer_kind([row[i] for row in rows]) for i in attr_index]
        fields = QgsFields()
        for name, kind in zip(sql.unique_names([headers[i] for i in attr_index]), kinds):
            fields.append(QgsField(name, compat.FIELD_TYPES[kind]))
        crs = QgsCoordinateReferenceSystem()
        geometries = []
        for row in rows:
            geom = None
            if geometry_index is not None:
                geom, row_crs = self._row_geometry(row[geometry_index])
                if geom is not None and not crs.isValid():
                    crs = row_crs
            geometries.append(geom)
        base = f"{label} (selected)"
        if not path:
            path = os.path.join(
                tempfile.mkdtemp(prefix="redshift_spatial_"), f"{sql.safe_file_name(base)}.gpkg"
            )
        sink = FeatureSink(path, sql.safe_file_name(base), fields, kinds, crs,
                           geometry=geometry_index is not None)
        skipped = 0
        try:
            for row, geom in zip(rows, geometries):
                attributes = [row[i] for i in attr_index]
                if geometry_index is None:
                    sink.add(attributes)
                elif geom is None:
                    skipped += 1
                else:
                    sink.add(attributes, bytes(geom.asWkb()))
        finally:
            results = sink.close()
        if skipped:
            self.message(tr("{} row(s) without geometry were not saved.").format(skipped), compat.WARNING)
        added = []
        for fam, out, layer_name, count in results:
            name = base if len(results) == 1 else f"{base} ({fam})"
            layer = QgsVectorLayer(f"{out}|layername={layer_name}", name, "ogr")
            if layer.isValid():
                layer.setCustomProperty(SOURCE_PROPERTY, label)
                QgsProject.instance().addMapLayer(layer)
                added.append(layer)
            QgsMessageLog.logMessage(f"{name}: {count} rows in {out}", LOG_TAG, compat.INFO)
        total = sum(r[3] for r in results)
        self.message(tr("{}: {} selected row(s) saved.").format(label, total), compat.SUCCESS)
        return added

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


def copy_style(source, target):
    """Symbology and labels of one layer onto another."""
    doc = QDomDocument()
    categories = compat.STYLE_SYMBOLOGY | compat.STYLE_LABELING
    source.exportNamedStyle(doc, categories=categories)
    target.importNamedStyle(doc, categories=categories)
