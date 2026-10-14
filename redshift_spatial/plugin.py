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
        self.action = None
        self.dialog = None
        self.provider = None
        self.menu = tr("&Redshift Spatial")

    def initGui(self):
        self.action = QAction(icon(), tr("Add Redshift Spatial Layer…"), self.iface.mainWindow())
        self.action.triggered.connect(self.show_dialog)
        self.iface.addPluginToDatabaseMenu(self.menu, self.action)
        self.iface.addDatabaseToolBarIcon(self.action)
        self.provider = RedshiftSpatialItemProvider(self.controller)
        QgsApplication.dataItemProviderRegistry().addProvider(self.provider)

    def unload(self):
        if self.provider is not None:
            QgsApplication.dataItemProviderRegistry().removeProvider(self.provider)
            self.provider = None
        self.iface.removePluginDatabaseMenu(self.menu, self.action)
        self.iface.removeDatabaseToolBarIcon(self.action)
        if self.dialog is not None:
            self.dialog.close()
            self.dialog = None

    def show_dialog(self):
        from .dialog import LoadLayerDialog

        if self.dialog is None:
            self.dialog = LoadLayerDialog(self.controller, self.iface.mainWindow())
        self.dialog.refresh_connections()
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
