# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 CEOX Planejamento e Otimização
"""Shared by the dialog and the Browser panel: credentials for the session,
starting loads and adding the finished layers to the project."""

import os
import tempfile

from qgis.core import Qgis, QgsApplication, QgsMessageLog, QgsProject, QgsVectorLayer
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QInputDialog, QLineEdit, QMessageBox

from . import connections
from .loader import LoadTask

LOG_TAG = "Redshift Spatial"
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
                    parent, title, tr("Password for {}:").format(username), QLineEdit.Password
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
            path = os.path.join(tempfile.mkdtemp(prefix="redshift_spatial_"), f"{source[1]}.gpkg")
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
        self.message(tr("Loading {}.{}…").format(source[0], source[1]), Qgis.Info)

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
        if answer != QMessageBox.Yes:
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
                Qgis.Warning,
            )
            return free

    def task_finished(self, task, ok):
        if task in self.tasks:
            self.tasks.remove(task)
        for msg in task.messages:
            QgsMessageLog.logMessage(msg, LOG_TAG, Qgis.Warning)
        if task.invalid:
            QgsMessageLog.logMessage(
                f"{task.invalid} rows with invalid geometry were skipped.", LOG_TAG, Qgis.Warning
            )
        schema, table = task.source[0], task.source[1]
        if not ok:
            if task.error is not None:
                QgsMessageLog.logMessage(str(task.error), LOG_TAG, Qgis.Critical)
                self.message(tr("{}.{}: {}").format(schema, table, task.error), Qgis.Critical)
            else:
                self.message(tr("{}.{}: canceled.").format(schema, table), Qgis.Warning)
            return
        if not task.results:
            self.message(tr("{}.{}: no rows with geometry.").format(schema, table), Qgis.Warning)
            return
        many = len(task.results) > 1
        for fam, path, layer_name, count in task.results:
            name = f"{table} ({fam})" if many else table
            layer = QgsVectorLayer(f"{path}|layername={layer_name}", name, "ogr")
            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)
            QgsMessageLog.logMessage(f"{name}: {count} features in {path}", LOG_TAG, Qgis.Info)
        total = sum(r[3] for r in task.results)
        level = Qgis.Warning if task.messages or task.invalid else Qgis.Success
        self.message(tr("{}.{}: {} features loaded.").format(schema, table, total), level)

    def message(self, text, level):
        if self.iface is not None:
            self.iface.messageBar().pushMessage(LOG_TAG, text, level=level, duration=8)
