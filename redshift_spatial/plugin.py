# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 CEOX Planejamento e Otimização
from qgis.core import QgsApplication

from .browser import RedshiftSpatialItemProvider
from .compat import QAction
from .controller import Controller, icon, tr


class RedshiftSpatialPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.controller = Controller(iface)
        self.actions = []
        self.dialog = None
        self.sql_dialog = None
        self.provider = None
        self.menu = tr("&Redshift Spatial")

    def initGui(self):
        add = QAction(icon(), tr("Add Redshift Spatial Layer…"), self.iface.mainWindow())
        add.triggered.connect(self.show_dialog)
        run_sql = QAction(
            QgsApplication.getThemeIcon("/mActionRunSql.svg"), tr("Execute SQL…"), self.iface.mainWindow()
        )
        run_sql.triggered.connect(self.show_sql)
        self.actions = [add, run_sql]
        for action in self.actions:
            self.iface.addPluginToDatabaseMenu(self.menu, action)
        self.iface.addDatabaseToolBarIcon(add)
        self.provider = RedshiftSpatialItemProvider(self.controller)
        QgsApplication.dataItemProviderRegistry().addProvider(self.provider)
        self.controller.install_layer_action()

    def unload(self):
        self.controller.remove_layer_action()
        if self.provider is not None:
            QgsApplication.dataItemProviderRegistry().removeProvider(self.provider)
            self.provider = None
        for action in self.actions:
            self.iface.removePluginDatabaseMenu(self.menu, action)
        if self.actions:
            self.iface.removeDatabaseToolBarIcon(self.actions[0])
        self.actions = []
        for dlg in (self.dialog, self.sql_dialog):
            if dlg is not None:
                dlg.close()
        self.dialog = self.sql_dialog = None

    def _raise(self, dlg):
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def show_dialog(self):
        from .dialog import LoadLayerDialog

        if self.dialog is None:
            self.dialog = LoadLayerDialog(self.controller, self.iface.mainWindow())
        self.dialog.refresh_connections()
        self._raise(self.dialog)

    def show_sql(self):
        from .dialog import SqlDialog

        if self.sql_dialog is None:
            self.sql_dialog = SqlDialog(self.controller, None, self.iface.mainWindow())
        self._raise(self.sql_dialog)
