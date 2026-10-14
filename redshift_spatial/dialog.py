# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 CEOX Planejamento e Otimização
"""Dialogs: saved connections, load options and the "Add Redshift layer" window."""

from qgis.core import QgsCoordinateReferenceSystem
from qgis.gui import QgsAuthConfigSelect, QgsFileWidget, QgsProjectionSelectionWidget
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import connections, db
from .controller import icon, tr

SSL_MODES = ["require", "verify-ca", "verify-full", "prefer", "allow", "disable"]


class WaitCursor:
    def __enter__(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)

    def __exit__(self, *exc):
        QApplication.restoreOverrideCursor()


class ConnectionDialog(QDialog):
    def __init__(self, controller, parent=None, conn=None):
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle(tr("Redshift Spatial Connection"))
        self.setWindowIcon(icon())
        self.original_name = conn["name"] if conn else None
        conn = conn or dict(connections.DEFAULTS, name="")

        self.name = QLineEdit(conn["name"])
        self.host = QLineEdit(conn["host"])
        self.host.setPlaceholderText("my-cluster.abc123.us-east-1.redshift.amazonaws.com")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(int(conn["port"]))
        self.database = QLineEdit(conn["database"])
        self.sslmode = QComboBox()
        self.sslmode.addItems(SSL_MODES)
        self.sslmode.setCurrentText(conn["sslmode"])
        self.username = QLineEdit(conn["username"])
        self.username.setPlaceholderText(tr("used when no authentication is selected"))
        self.auth = QgsAuthConfigSelect(self, "postgres")
        self.auth.setConfigId(conn["authcfg"])

        form = QFormLayout()
        form.addRow(tr("Name"), self.name)
        form.addRow(tr("Host"), self.host)
        form.addRow(tr("Port"), self.port)
        form.addRow(tr("Database"), self.database)
        form.addRow(tr("SSL mode"), self.sslmode)
        form.addRow(tr("Username"), self.username)
        form.addRow(tr("Authentication"), self.auth)

        test = QPushButton(tr("Test Connection"))
        test.clicked.connect(self.test)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.addButton(test, QDialogButtonBox.ActionRole)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(
            QLabel(tr("Passwords are kept only in the QGIS authentication database."))
        )
        layout.addWidget(buttons)

    def data(self):
        return {
            "name": self.name.text().strip(),
            "host": self.host.text().strip(),
            "port": self.port.value(),
            "database": self.database.text().strip(),
            "sslmode": self.sslmode.currentText(),
            "username": self.username.text().strip(),
            "authcfg": self.auth.configId(),
        }

    def test(self):
        params = self.controller.params(self.data(), self)
        if params is None:
            return
        try:
            with WaitCursor():
                version = db.server_version(params)
        except Exception as e:
            QMessageBox.critical(self, tr("Connection failed"), str(e))
            return
        QMessageBox.information(self, tr("Connection succeeded"), version)

    def save(self):
        data = self.data()
        if not data["name"] or "/" in data["name"] or "\\" in data["name"]:
            QMessageBox.warning(self, tr("Invalid name"), tr("Enter a name without slashes."))
            return
        if not data["host"] or not data["database"]:
            QMessageBox.warning(self, tr("Missing data"), tr("Host and database are required."))
            return
        if self.original_name and self.original_name != data["name"]:
            connections.remove(self.original_name)
        connections.save(data["name"], data)
        self.accept()


def new_connection(controller, parent=None):
    """Returns the saved name, or None."""
    dlg = ConnectionDialog(controller, parent)
    return dlg.data()["name"] if dlg.exec_() else None


def edit_connection(controller, name, parent=None):
    dlg = ConnectionDialog(controller, parent, connections.load(name))
    return dlg.data()["name"] if dlg.exec_() else None


def remove_connection(name, parent=None):
    answer = QMessageBox.question(parent, tr("Remove"), tr("Remove connection {}?").format(name))
    if answer == QMessageBox.Yes:
        connections.remove(name)
        return True
    return False


class OptionsForm(QWidget):
    """Filter, limit, fallback CRS and output file of a load."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.where = QLineEdit()
        self.where.setPlaceholderText(tr("optional SQL filter, e.g. region = 'north'"))
        self.limit = QSpinBox()
        self.limit.setRange(0, 2_000_000_000)
        self.limit.setSpecialValueText(tr("No limit"))
        self.crs = QgsProjectionSelectionWidget()
        self.crs.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
        self.output = QgsFileWidget()
        self.output.setStorageMode(QgsFileWidget.SaveFile)
        self.output.setFilter("GeoPackage (*.gpkg)")
        self.output.lineEdit().setPlaceholderText(tr("temporary file"))

        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        form.addRow(tr("Filter (WHERE)"), self.where)
        form.addRow(tr("Row limit"), self.limit)
        form.addRow(tr("CRS when SRID is 0"), self.crs)
        form.addRow(tr("Save to"), self.output)

    def options(self):
        return {
            "where": self.where.text(),
            "limit": self.limit.value(),
            "path": self.output.filePath(),
            "fallback_crs": self.crs.crs(),
        }


class LoadOptionsDialog(QDialog):
    """Asked from the Browser panel ("Add Layer with Filter…")."""

    def __init__(self, source, parent=None):
        super().__init__(parent)
        schema, table, column, _ = source
        self.setWindowTitle(tr("Add {}.{}").format(schema, table))
        self.setWindowIcon(icon())
        self.form = OptionsForm()
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        buttons.addButton(tr("Add Layer"), QDialogButtonBox.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"{schema}.{table} ({column})"))
        layout.addWidget(self.form)
        layout.addWidget(buttons)
        self.resize(520, self.sizeHint().height())


class LoadLayerDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle(tr("Add Redshift Spatial Layer"))
        self.setWindowIcon(icon())
        self.resize(640, 560)

        self.conn_combo = QComboBox()
        btn_new = QPushButton(tr("New"))
        btn_edit = QPushButton(tr("Edit"))
        btn_remove = QPushButton(tr("Remove"))
        btn_connect = QPushButton(tr("Connect"))
        btn_new.clicked.connect(self.new_connection)
        btn_edit.clicked.connect(self.edit_connection)
        btn_remove.clicked.connect(self.remove_connection)
        btn_connect.clicked.connect(self.list_tables)
        conn_row = QHBoxLayout()
        conn_row.addWidget(self.conn_combo, 1)
        for b in (btn_connect, btn_new, btn_edit, btn_remove):
            conn_row.addWidget(b)

        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Filter tables…"))
        self.search.textChanged.connect(self.filter_tree)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Table"), tr("Column"), tr("Type")])
        self.tree.itemDoubleClicked.connect(lambda item, _: self.load(item))

        self.form = OptionsForm()

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        btn_load = buttons.addButton(tr("Add Layer"), QDialogButtonBox.AcceptRole)
        btn_load.clicked.connect(lambda: self.load(self.tree.currentItem()))
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(conn_row)
        layout.addWidget(self.search)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.form)
        layout.addWidget(buttons)
        self.refresh_connections()

    # connections -----------------------------------------------------------
    def refresh_connections(self, select=None):
        current = select or self.conn_combo.currentText()
        self.conn_combo.clear()
        self.conn_combo.addItems(connections.names())
        if current:
            self.conn_combo.setCurrentText(current)

    def current_connection(self):
        name = self.conn_combo.currentText()
        if not name:
            QMessageBox.information(self, tr("No connection"), tr("Create a connection first."))
            return None
        return connections.load(name)

    def new_connection(self):
        name = new_connection(self.controller, self)
        if name:
            self.refresh_connections(name)

    def edit_connection(self):
        name = self.conn_combo.currentText()
        if name:
            new_name = edit_connection(self.controller, name, self)
            if new_name:
                self.refresh_connections(new_name)

    def remove_connection(self):
        name = self.conn_combo.currentText()
        if name and remove_connection(name, self):
            self.refresh_connections()

    # tables ----------------------------------------------------------------
    def list_tables(self):
        conn = self.current_connection()
        if conn is None:
            return
        params = self.controller.params(conn, self)
        if params is None:
            return
        try:
            with WaitCursor():
                rows = db.list_spatial_columns(params)
        except Exception as e:
            QMessageBox.critical(self, tr("Connection failed"), str(e))
            return
        self.tree.clear()
        schemas = {}
        for schema, table, column, data_type in rows:
            parent = schemas.get(schema)
            if parent is None:
                parent = schemas[schema] = QTreeWidgetItem(self.tree, [schema])
            item = QTreeWidgetItem(parent, [table, column, data_type])
            item.setData(0, Qt.UserRole, (schema, table, column, data_type))
        self.tree.expandAll()
        self.tree.resizeColumnToContents(0)
        if not rows:
            QMessageBox.information(
                self, tr("No spatial tables"), tr("No GEOMETRY or GEOGRAPHY column is visible to this user.")
            )
        self.filter_tree(self.search.text())

    def filter_tree(self, text):
        text = text.lower()
        for i in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(i)
            visible = 0
            for j in range(parent.childCount()):
                child = parent.child(j)
                hit = not text or text in f"{parent.text(0)}.{child.text(0)}".lower()
                child.setHidden(not hit)
                visible += hit
            parent.setHidden(visible == 0)

    def load(self, item):
        source = item.data(0, Qt.UserRole) if item else None
        if not source:
            QMessageBox.information(self, tr("Choose a table"), tr("Select a table in the list."))
            return
        conn = self.current_connection()
        if conn is not None:
            self.controller.load(conn, source, self.form.options(), self)
