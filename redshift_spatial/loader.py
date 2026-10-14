# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 CEOX Planejamento e Otimização
"""Background loading: Redshift -> GeoPackage, one layer per geometry family."""

import os
from contextlib import closing
from datetime import timezone

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransformContext,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsTask,
    QgsVectorFileWriter,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QDate, QDateTime, QMetaType, Qt, QTime, QVariant

from . import db, sql

# QGIS 3.38 deprecated QgsField(name, QVariant.Type) in favour of QMetaType.
if Qgis.QGIS_VERSION_INT >= 33800:
    FIELD_TYPES = {
        "string": QMetaType.QString,
        "int": QMetaType.Int,
        "int64": QMetaType.LongLong,
        "double": QMetaType.Double,
        "bool": QMetaType.Bool,
        "date": QMetaType.QDate,
        "datetime": QMetaType.QDateTime,
    }
else:
    FIELD_TYPES = {
        "string": QVariant.String,
        "int": QVariant.Int,
        "int64": QVariant.LongLong,
        "double": QVariant.Double,
        "bool": QVariant.Bool,
        "date": QVariant.Date,
        "datetime": QVariant.DateTime,
    }


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
        spec = Qt.LocalTime
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
            spec = Qt.UTC
        return QDateTime(
            QDate(value.year, value.month, value.day),
            QTime(value.hour, value.minute, value.second, value.microsecond // 1000),
            spec,
        )
    return str(value)


def family(wkb_type):
    if QgsWkbTypes.flatType(wkb_type) == QgsWkbTypes.GeometryCollection:
        return "collection"
    return {
        QgsWkbTypes.PointGeometry: "point",
        QgsWkbTypes.LineGeometry: "line",
        QgsWkbTypes.PolygonGeometry: "polygon",
    }.get(QgsWkbTypes.geometryType(wkb_type), "collection")


class FeatureSink:
    """Writes rows of (attributes..., wkb) into GeoPackage layers.

    A QGIS layer holds a single geometry type, so each family (point, line,
    polygon, collection) gets its own file; the first family uses the path as
    given, the next ones get a _<family> suffix. Single geometries are
    promoted to multi so POLYGON and MULTIPOLYGON share a layer.
    """

    def __init__(self, path, layer_name, fields, kinds, crs):
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
        opts.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile
        opts.layerOptions = [
            f"FID={self.free_name('fid')}",
            f"GEOMETRY_NAME={self.free_name('geom')}",
        ]
        writer = QgsVectorFileWriter.create(
            path, self.fields, wkb_type, self.crs, QgsCoordinateTransformContext(), opts
        )
        if writer.hasError() != QgsVectorFileWriter.NoError:
            raise RuntimeError(writer.errorMessage())
        self._writers[fam] = writer
        self._counts[fam] = 0
        self._paths[fam] = path
        return writer

    def add(self, attributes, wkb):
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
    to the project by the callback, which QGIS runs on the main thread."""

    def __init__(self, params, source, options, on_finished):
        schema, table, column, data_type = source
        super().__init__(f"Redshift: {schema}.{table}", QgsTask.CanCancel)
        self.params = params
        self.source = source
        self.options = options  # where, limit, path, fallback_crs
        self.on_finished = on_finished
        self.results = []
        self.messages = []
        self.error = None
        self.invalid = 0

    def run(self):
        schema, table, column, data_type = self.source
        where = self.options.get("where")
        limit = self.options.get("limit") or None
        geom_expr = sql.geometry_expression(column, data_type)
        sink = None
        try:
            with closing(db.connect(self.params)) as conn, conn.cursor() as cur:
                cur.execute(sql.LIST_COLUMNS, (schema, table))
                selects, kinds, names = [], [], []
                for name, col_type in cur.fetchall():
                    if name == column:
                        continue
                    attr = sql.attribute_column(name, col_type)
                    if attr is None:
                        self.messages.append(f"Skipped column {name} ({col_type}).")
                        continue
                    selects.append(attr[0])
                    kinds.append(attr[1])
                    names.append(name)
                fields = QgsFields()
                for name, kind in zip(sql.unique_names(names), kinds):
                    fields.append(QgsField(name, FIELD_TYPES[kind]))

                cur.execute(sql.srid_query(schema, table, geom_expr, where))
                srids = cur.fetchall()
                crs = self.options["fallback_crs"]
                if srids and srids[0][0]:
                    found = QgsCoordinateReferenceSystem(f"EPSG:{srids[0][0]}")
                    if found.isValid():
                        crs = found
                    else:
                        self.messages.append(
                            f"SRID {srids[0][0]} is unknown to QGIS; using {crs.authid()}."
                        )
                elif srids:
                    self.messages.append(f"SRID 0 (undefined); using {crs.authid()}.")
                if len(srids) > 1:
                    self.messages.append(
                        f"Sample has {len(srids)} SRIDs; all rows were written as {crs.authid()}."
                    )

                cur.execute(sql.count_query(schema, table, geom_expr, where))
                total = cur.fetchone()[0]
                if limit:
                    total = min(total, int(limit))

                sink = FeatureSink(self.options["path"], table, fields, kinds, crs)
                cur.execute(
                    sql.declare_cursor(
                        sql.data_query(schema, table, selects, geom_expr, where, limit)
                    )
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
                        sink.add(row[:-1], row[-1])
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
