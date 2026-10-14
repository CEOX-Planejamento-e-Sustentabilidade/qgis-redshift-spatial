# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 CEOX Planejamento e Otimização
"""Browser panel entry: Redshift Spatial > connection > schema > table > column.

QGIS can only drag a layer onto the map when a native data provider exists,
and Redshift has none, so tables load by double click or context menu.
Items are flagged Fast so that they populate on the main thread: listing a
connection may need to ask for a password.
"""

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsDataCollectionItem,
    QgsDataItem,
    QgsDataItemProvider,
    QgsDataProvider,
    QgsErrorItem,
)

from . import connections, db, sources, sql
from .compat import QAction
from .controller import icon, tr
from .dialog import (
    LoadOptionsDialog,
    SqlDialog,
    WaitCursor,
    edit_connection,
    new_connection,
    open_preview,
    remove_connection,
)

PROVIDER_KEY = "redshift_spatial"
ROOT_PATH = "redshift_spatial:"
FAST = Qgis.BrowserItemCapability.Fast
# Qgis.DataItemProviderCapability arrived in QGIS 3.36.
DATABASES = getattr(getattr(Qgis, "DataItemProviderCapability", None), "Databases", QgsDataProvider.Database)

FIELD_ICONS = {
    "string": "/mIconFieldText.svg",
    "int": "/mIconFieldInteger.svg",
    "int64": "/mIconFieldInteger.svg",
    "double": "/mIconFieldFloat.svg",
    "bool": "/mIconFieldBool.svg",
    "date": "/mIconFieldDate.svg",
    "datetime": "/mIconFieldDateTime.svg",
}


def _fast(item):
    item.setCapabilitiesV2(item.capabilities2() | FAST)


def _theme_icon(name):
    return QgsApplication.getThemeIcon(name)


def field_icon(data_type):
    if sql.base_type(data_type) in sql.SPATIAL_TYPES:
        return _theme_icon("/mIconFieldGeometry.svg")
    attr = sql.attribute_column("x", data_type)
    return _theme_icon(FIELD_ICONS.get(attr[1] if attr else "string", "/mIconFieldText.svg"))


class RedshiftSpatialItemProvider(QgsDataItemProvider):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller

    def name(self):
        return "Redshift Spatial"

    def dataProviderKey(self):
        return PROVIDER_KEY

    def capabilities(self):
        return DATABASES

    def createDataItem(self, path, parent):
        if not path:
            return RootItem(parent, self.controller)
        return None


class RootItem(QgsDataCollectionItem):
    def __init__(self, parent, controller):
        super().__init__(parent, "Redshift Spatial", ROOT_PATH, PROVIDER_KEY)
        self.controller = controller
        self.setIcon(icon())
        _fast(self)

    def createChildren(self):
        return [ConnectionItem(self, name, self.controller) for name in connections.names()]

    def actions(self, parent):
        new = QAction(_theme_icon("/mActionAdd.svg"), tr("New Connection…"), parent)
        new.triggered.connect(self.new_connection)
        return [new]

    def new_connection(self):
        if new_connection(self.controller, self.controller.parent_window()):
            self.refresh()


class ConnectionItem(QgsDataCollectionItem):
    def __init__(self, parent, name, controller):
        super().__init__(parent, name, f"{ROOT_PATH}/{name}", PROVIDER_KEY)
        self.controller = controller
        self.setIcon(_theme_icon("/mIconConnect.svg"))
        _fast(self)

    def createChildren(self):
        conn = connections.load(self.name())
        params = self.controller.params(conn)
        if params is None:
            return []
        try:
            with WaitCursor():
                rows = db.list_tables(params, conn["list_all_tables"])
        except Exception as e:
            return [QgsErrorItem(self, str(e).strip(), f"{self.path()}/error")]
        schemas = {}
        for row in rows:
            schemas.setdefault(row[0], []).append(row)
        return [SchemaItem(self, schema, tables, self.controller) for schema, tables in schemas.items()]

    def actions(self, parent):
        run_sql = QAction(_theme_icon("/mActionRunSql.svg"), tr("Execute SQL…"), parent)
        run_sql.triggered.connect(self.open_sql)
        refresh = QAction(_theme_icon("/mActionRefresh.svg"), tr("Refresh"), parent)
        refresh.triggered.connect(self.refresh)
        edit = QAction(tr("Edit Connection…"), parent)
        edit.triggered.connect(self.edit)
        remove = QAction(_theme_icon("/mActionDeleteSelected.svg"), tr("Remove Connection"), parent)
        remove.triggered.connect(self.remove)
        return [run_sql, refresh, edit, remove]

    def open_sql(self):
        SqlDialog(self.controller, self.name(), self.controller.parent_window()).show()

    def edit(self):
        if edit_connection(self.controller, self.name(), self.controller.parent_window()):
            self.parent().refresh()

    def remove(self):
        if remove_connection(self.name(), self.controller.parent_window()):
            self.parent().refresh()


class SchemaItem(QgsDataCollectionItem):
    def __init__(self, parent, schema, rows, controller):
        super().__init__(parent, schema, f"{parent.path()}/{schema}", PROVIDER_KEY)
        self.rows = rows
        self.controller = controller
        self.setIcon(_theme_icon("/mIconDbSchema.svg"))
        _fast(self)

    def createChildren(self):
        return [TableItem(self, row, self.controller) for row in self.rows]


class TableItem(QgsDataCollectionItem):
    """A spatial column of a table (one item per column when a table has
    several) or a table without geometry. Expands into its columns."""

    def __init__(self, parent, row, controller):
        schema, table, column, data_type = row
        name = table if self._single_item(parent, table) else f"{table} ({column})"
        super().__init__(parent, name, f"{parent.path()}/{table}/{column or ''}", PROVIDER_KEY)
        self.source = sources.from_row(row)
        self.controller = controller
        if column:
            self.setIcon(_theme_icon("/mIconGeometryCollectionLayer.svg"))
            self.setToolTip(f"{schema}.{table}\n{column} ({data_type})")
        else:
            self.setIcon(_theme_icon("/mIconTableLayer.svg"))
            self.setToolTip(f"{schema}.{table}\n" + tr("no geometry"))
        _fast(self)

    @staticmethod
    def _single_item(parent, table):
        return sum(1 for r in parent.rows if r[1] == table) == 1

    def connection(self):
        return connections.load(self.parent().parent().name())

    def createChildren(self):
        params = self.controller.params(self.connection())
        if params is None:
            return []
        try:
            with WaitCursor():
                columns = db.list_columns(params, self.source["schema"], self.source["table"])
        except Exception as e:
            return [QgsErrorItem(self, str(e).strip(), f"{self.path()}/error")]
        return [ColumnItem(self, name, data_type) for name, data_type in columns]

    def handleDoubleClick(self):
        self.add_layer()
        return True

    def actions(self, parent):
        add = QAction(_theme_icon("/mActionAddLayer.svg"), tr("Add Layer"), parent)
        add.triggered.connect(self.add_layer)
        add_filtered = QAction(tr("Add Layer with Filter…"), parent)
        add_filtered.triggered.connect(self.add_layer_with_filter)
        preview = QAction(_theme_icon("/mActionOpenTable.svg"), tr("Preview Rows…"), parent)
        preview.triggered.connect(self.preview)
        return [add, add_filtered, preview]

    def add_layer(self):
        options = {"where": "", "limit": 0, "path": "", "fallback_crs": QgsCoordinateReferenceSystem("EPSG:4326")}
        self.controller.load(self.connection(), self.source, options)

    def add_layer_with_filter(self):
        dlg = LoadOptionsDialog(self.source, self.controller.parent_window(),
                                controller=self.controller, conn=self.connection())
        if dlg.exec():
            self.controller.load(self.connection(), self.source, dlg.form.options())

    def preview(self):
        open_preview(self.controller, self.connection(), self.source, self.controller.parent_window())


class ColumnItem(QgsDataItem):
    def __init__(self, parent, name, data_type):
        super().__init__(Qgis.BrowserItemType.Field, parent, name, f"{parent.path()}/{name}", PROVIDER_KEY)
        self.data_type = data_type
        self.setIcon(field_icon(data_type))
        self.setToolTip(f"{name}: {data_type}")
        self.setState(Qgis.BrowserItemState.Populated)
