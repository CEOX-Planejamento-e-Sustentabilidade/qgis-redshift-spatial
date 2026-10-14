# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 CEOX Planejamento e Otimização
"""Background loading: Redshift -> GeoPackage, one layer per geometry family."""

import os
from contextlib import closing
from datetime import timezone

from qgis.core import (
    QgsCoordinateTransformContext,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsTask,
    QgsVectorFileWriter,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QDate, QDateTime, QTime

from . import compat, db, sources, sql
from .i18n import tr

FIELD_TYPES = compat.FIELD_TYPES


def convert(value, kind):
    if value is None:
        return None
    if kind == "double":
        return float(value)
    if kind in ("int", "int64"):
        return int(value)
    if kind == "bool":
        return bool(value)
    if kind == "date":
        return QDate(value.year, value.month, value.day)
    if kind == "datetime":
        spec = compat.LOCAL_TIME
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
            spec = compat.UTC
        return QDateTime(
            QDate(value.year, value.month, value.day),
            QTime(value.hour, value.minute, value.second, value.microsecond // 1000),
            spec,
        )
    return str(value)


def family(wkb_type):
    if QgsWkbTypes.flatType(wkb_type) == compat.GEOMETRY_COLLECTION:
        return "collection"
    return {
        compat.POINT_GEOMETRY: "point",
        compat.LINE_GEOMETRY: "line",
        compat.POLYGON_GEOMETRY: "polygon",
    }.get(QgsWkbTypes.geometryType(wkb_type), "collection")


class FeatureSink:
    """Writes rows of (attributes..., wkb) into GeoPackage layers.

    A QGIS layer holds a single geometry type, so each family (point, line,
    polygon, collection) gets its own file; the first family uses the path as
    given, the next ones get a _<family> suffix. Single geometries are
    promoted to multi so POLYGON and MULTIPOLYGON share a layer.

    With geometry=False every row goes to one table without geometry
    (family "table") and the wkb argument is ignored.
    """

    def __init__(self, path, layer_name, fields, kinds, crs, geometry=True):
        self.geometry = geometry
        self.path = path
        self.layer_name = layer_name
        self.fields = fields
        self.kinds = kinds
        self.crs = crs
        self._writers = {}
        self._counts = {}
        self._paths = {}
        self.invalid = 0

    def free_name(self, name):
        """GeoPackage key ("fid") or geometry ("geom") column name that no
        source column uses. With the defaults, a source column called fid
        becomes the key and fails on repeated or NULL values, and one called
        geom cannot be created at all."""
        taken = {f.name().lower() for f in self.fields}
        while name in taken:
            name = f"gpkg_{name}"
        return name

    def _writer(self, fam, wkb_type):
        if fam in self._writers:
            return self._writers[fam]
        path = self.path
        if self._paths:
            stem, ext = os.path.splitext(self.path)
            path = f"{stem}_{fam}{ext}"
        opts = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName = "GPKG"
        opts.layerName = self.layer_name
        opts.fileEncoding = "UTF-8"
        opts.actionOnExistingFile = compat.CREATE_OR_OVERWRITE_FILE
        opts.layerOptions = [
            f"FID={self.free_name('fid')}",
            f"GEOMETRY_NAME={self.free_name('geom')}",
        ]
        writer = QgsVectorFileWriter.create(
            path, self.fields, wkb_type, self.crs, QgsCoordinateTransformContext(), opts
        )
        if writer.hasError() != compat.NO_ERROR:
            raise RuntimeError(writer.errorMessage())
        self._writers[fam] = writer
        self._counts[fam] = 0
        self._paths[fam] = path
        return writer

    def add(self, attributes, wkb=None):
        if not self.geometry:
            writer = self._writer("table", compat.NO_GEOMETRY)
            feature = QgsFeature(self.fields)
            feature.setAttributes([convert(v, k) for v, k in zip(attributes, self.kinds)])
            if not writer.addFeature(feature):
                raise RuntimeError(writer.errorMessage())
            self._counts["table"] += 1
            return
        data = sql.wkb_bytes(wkb)
        geom = QgsGeometry()
        if data:
            geom.fromWkb(data)
        if geom.isNull():
            self.invalid += 1
            return
        fam = family(geom.wkbType())
        if fam != "collection":
            geom.convertToMultiType()
        writer = self._writer(fam, geom.wkbType())
        feature = QgsFeature(self.fields)
        feature.setAttributes(
            [convert(v, k) for v, k in zip(attributes, self.kinds)]
        )
        feature.setGeometry(geom)
        if not writer.addFeature(feature):
            raise RuntimeError(writer.errorMessage())
        self._counts[fam] += 1

    def close(self):
        """Flush every file; return [(family, path, layer_name, count)]."""
        result = [
            (fam, self._paths[fam], self.layer_name, self._counts[fam])
            for fam in self._writers
        ]
        for fam in list(self._writers):
            del self._writers[fam]
        return result


class LoadTask(QgsTask):
    """Runs off the main thread. It touches no widget; the layers are added
    to the project by the callback, which QGIS runs on the main thread.

    source: see sources.py (a table column, a table without geometry or a
    SQL query)."""

    def __init__(self, params, source, options, on_finished):
        super().__init__(f"Redshift: {sources.label(source)}", compat.CAN_CANCEL)
        self.params = params
        self.source = source
        self.label = sources.label(source)
        self.options = options  # where, limit, path, fallback_crs
        self.on_finished = on_finished
        self.results = []
        self.messages = []
        self.error = None
        self.invalid = 0

    def _attributes(self, cur):
        """(select expressions, kinds, QgsFields) of every non-geometry column."""
        src = self.source
        selects, kinds, names = [], [], []
        if src["kind"] == "table":
            cur.execute(sql.LIST_COLUMNS, (src["schema"], src["table"]))
            for name, col_type in cur.fetchall():
                if name == src["column"]:
                    continue
                attr = sql.attribute_column(name, col_type)
                if attr is None:
                    self.messages.append(tr("Skipped column {} ({}).").format(name, col_type))
                    continue
                selects.append(attr[0])
                kinds.append(attr[1])
                names.append(name)
        else:
            # Types come from the result description; unknown ones (SUPER,
            # other geometries...) arrive as text and are kept as strings.
            cur.execute(sql.describe_query(src["sql"]))
            for column in cur.description:
                name, oid = column[0], column[1]
                if name == src["column"]:
                    continue
                selects.append(sql.quote_ident(name))
                kinds.append(sql.kind_for_oid(oid))
                names.append(name)
        fields = QgsFields()
        for name, kind in zip(sql.unique_names(names), kinds):
            fields.append(QgsField(name, FIELD_TYPES[kind]))
        return selects, kinds, fields

    def _crs(self, cur, from_clause, geom_expr, where):
        cur.execute(sql.srid_query(from_clause, geom_expr, where))
        srids = cur.fetchall()
        crs = self.options["fallback_crs"]
        if srids and srids[0][0]:
            found = QgsCoordinateReferenceSystem(f"EPSG:{srids[0][0]}")
            if found.isValid():
                crs = found
            else:
                self.messages.append(tr("SRID {} is unknown to QGIS; using {}.").format(srids[0][0], crs.authid()))
        elif srids:
            self.messages.append(tr("SRID 0 (undefined); using {}.").format(crs.authid()))
        if len(srids) > 1:
            self.messages.append(
                tr("Sample has {} SRIDs; all rows were written as {}.").format(len(srids), crs.authid())
            )
        return crs

    def run(self):
        src = self.source
        where = self.options.get("where")
        limit = self.options.get("limit") or None
        sink = None
        try:
            if src["kind"] == "table":
                from_clause = sql.table_ref(src["schema"], src["table"])
            else:
                from_clause = sql.query_from(src["sql"])
            geom_expr = (
                sql.geometry_expression(src["column"], src["data_type"]) if src["column"] else None
            )
            with closing(db.connect(self.params)) as conn, conn.cursor() as cur:
                selects, kinds, fields = self._attributes(cur)
                if geom_expr:
                    crs = self._crs(cur, from_clause, geom_expr, where)
                else:
                    crs = QgsCoordinateReferenceSystem()

                cur.execute(sql.count_query(from_clause, geom_expr, where))
                total = cur.fetchone()[0]
                if limit:
                    total = min(total, int(limit))

                sink = FeatureSink(
                    self.options["path"], src["name"], fields, kinds, crs, geometry=bool(geom_expr)
                )
                cur.execute(
                    sql.declare_cursor(sql.data_query(from_clause, selects, geom_expr, where, limit))
                )
                done = 0
                while True:
                    if self.isCanceled():
                        return False
                    cur.execute(sql.fetch_cursor())
                    rows = cur.fetchall()
                    if not rows:
                        break
                    for row in rows:
                        if geom_expr:
                            sink.add(row[:-1], row[-1])
                        else:
                            sink.add(row)
                    done += len(rows)
                    if total:
                        self.setProgress(100.0 * done / total)
            return True
        except Exception as e:  # reported to the user by the callback
            self.error = e
            return False
        finally:
            if sink is not None:
                self.results = sink.close()
                self.invalid = sink.invalid

    def finished(self, result):
        self.on_finished(self, result)


class QueryTask(QgsTask):
    """Runs a small SELECT (a preview) off the main thread and keeps the
    header and rows for the callback. cancel() also cancels the statement
    on the server."""

    def __init__(self, params, query, label, on_finished, count_query=None):
        super().__init__(f"Redshift: {label}", compat.CAN_CANCEL)
        self.params = params
        self.query = query
        self.count_query = count_query
        self.on_finished = on_finished
        self.headers = []
        self.rows = []
        self.total = None  # rows matching, when count_query is given
        self.error = None
        self._conn = None

    def run(self):
        try:
            self._conn = db.connect(self.params)
            with closing(self._conn), self._conn.cursor() as cur:
                if self.query:
                    cur.execute(self.query)
                    self.headers = [d[0] for d in cur.description or []]
                    self.rows = cur.fetchall()
                if self.count_query and not self.isCanceled():
                    try:
                        cur.execute(self.count_query)
                        self.total = int(cur.fetchone()[0])
                    except Exception:  # noqa: BLE001 - the rows are still useful
                        if not self.query:
                            raise
            return True
        except Exception as e:
            if not self.isCanceled():
                self.error = e
            return False
        finally:
            self._conn = None

    def cancel(self):
        conn = self._conn
        if conn is not None:
            try:
                conn.cancel()
            except Exception:  # noqa: BLE001 - best effort
                pass
        super().cancel()

    def finished(self, result):
        self.on_finished(self, result)
