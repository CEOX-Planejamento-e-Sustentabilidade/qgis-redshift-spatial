# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 CEOX Planejamento e Otimização
"""Browser panel entry: Redshift Spatial > connection > schema > table.

QGIS can only drag a layer onto the map when a native data provider exists,
and Redshift has none, so tables load by double click or context menu.
Items are flagged Fast so that they populate on the main thread: listing a
connection may need to ask for a password.
"""

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsDataCollectionItem,
    QgsDataItem,
    QgsDataItemProvider,
    QgsDataProvider,
    QgsErrorItem,
)

from . import connections, db
from .compat import QAction
from .controller import icon, tr
from .dialog import LoadOptionsDialog, WaitCursor, edit_connection, new_connection, remove_connection

PROVIDER_KEY = "redshift_spatial"
ROOT_PATH = "redshift_spatial:"
FAST = Qgis.BrowserItemCapability.Fast
# Qgis.DataItemProviderCapability arrived in QGIS 3.36.
DATABASES = getattr(getattr(Qgis, "DataItemProviderCapability", None), "Databases", QgsDataProvider.Database)


def _fast(item):
    item.setCapabilitiesV2(item.capabilities2() | FAST)


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
        new = QAction(QgsApplication.getThemeIcon("/mActionAdd.svg"), tr("New Connection…"), parent)
        new.triggered.connect(self.new_connection)
        return [new]

    def new_connection(self):
        if new_connection(self.controller, self.controller.parent_window()):
            self.refresh()


class ConnectionItem(QgsDataCollectionItem):
    def __init__(self, parent, name, controller):
        super().__init__(parent, name, f"{ROOT_PATH}/{name}", PROVIDER_KEY)
        self.controller = controller
        self.setIcon(QgsApplication.getThemeIcon("/mIconConnect.svg"))
        _fast(self)

    def createChildren(self):
        conn = connections.load(self.name())
        params = self.controller.params(conn)
        if params is None:
            return []
        try:
            with WaitCursor():
                rows = db.list_spatial_columns(params)
        except Exception as e:
            return [QgsErrorItem(self, str(e).strip(), f"{self.path()}/error")]
        schemas = {}
        for row in rows:
            schemas.setdefault(row[0], []).append(row)
        return [SchemaItem(self, schema, tables, self.controller) for schema, tables in schemas.items()]

    def actions(self, parent):
        refresh = QAction(QgsApplication.getThemeIcon("/mActionRefresh.svg"), tr("Refresh"), parent)
        refresh.triggered.connect(self.refresh)
        edit = QAction(tr("Edit Connection…"), parent)
        edit.triggered.connect(self.edit)
        remove = QAction(QgsApplication.getThemeIcon("/mActionDeleteSelected.svg"), tr("Remove Connection"), parent)
        remove.triggered.connect(self.remove)
        return [refresh, edit, remove]

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
        self.setIcon(QgsApplication.getThemeIcon("/mIconDbSchema.svg"))
        _fast(self)

    def createChildren(self):
        return [TableItem(self, row, self.controller) for row in self.rows]


class TableItem(QgsDataItem):
    def __init__(self, parent, source, controller):
        schema, table, column, data_type = source
        name = table if self._single_column(parent, table) else f"{table} ({column})"
        super().__init__(Qgis.BrowserItemType.Custom, parent, name, f"{parent.path()}/{table}/{column}", PROVIDER_KEY)
        self.source = tuple(source)
        self.controller = controller
        self.setIcon(QgsApplication.getThemeIcon("/mIconGeometryCollectionLayer.svg"))
        self.setToolTip(f"{schema}.{table}\n{column} ({data_type})")
        self.setState(Qgis.BrowserItemState.Populated)

    @staticmethod
    def _single_column(parent, table):
        return sum(1 for r in parent.rows if r[1] == table) == 1

    def connection(self):
        return connections.load(self.parent().parent().name())

    def handleDoubleClick(self):
        self.add_layer()
        return True

    def actions(self, parent):
        add = QAction(QgsApplication.getThemeIcon("/mActionAddLayer.svg"), tr("Add Layer"), parent)
        add.triggered.connect(self.add_layer)
        add_filtered = QAction(tr("Add Layer with Filter…"), parent)
        add_filtered.triggered.connect(self.add_layer_with_filter)
        return [add, add_filtered]

    def add_layer(self):
        from qgis.core import QgsCoordinateReferenceSystem

        options = {"where": "", "limit": 0, "path": "", "fallback_crs": QgsCoordinateReferenceSystem("EPSG:4326")}
        self.controller.load(self.connection(), self.source, options)

    def add_layer_with_filter(self):
        dlg = LoadOptionsDialog(self.source, self.controller.parent_window())
        if dlg.exec():
            self.controller.load(self.connection(), self.source, dlg.form.options())
