# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 CEOX Planejamento e Otimização
"""Dialogs: saved connections, load options, the "Add layer" window, row
previews and the SQL window."""

from decimal import Decimal

from qgis.core import QgsCoordinateReferenceSystem
from qgis.gui import QgsAuthConfigSelect, QgsFileWidget, QgsProjectionSelectionWidget
from qgis.PyQt.QtGui import QCursor, QFontDatabase, QKeySequence
from qgis.PyQt.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import compat, connections, db, sources, sql
from .compat import QAction
from .controller import icon, tr

SSL_MODES = ["require", "verify-ca", "verify-full", "prefer", "allow", "disable"]
CELL_CHARS = 200


class WaitCursor:
    def __enter__(self):
        QApplication.setOverrideCursor(QCursor(compat.WAIT_CURSOR))

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
        self.list_all = QCheckBox(tr("Also list tables without geometry"))
        self.list_all.setChecked(bool(conn.get("list_all_tables")))

        form = QFormLayout()
        form.addRow(tr("Name"), self.name)
        form.addRow(tr("Host"), self.host)
        form.addRow(tr("Port"), self.port)
        form.addRow(tr("Database"), self.database)
        form.addRow(tr("SSL mode"), self.sslmode)
        form.addRow(tr("Username"), self.username)
        form.addRow(tr("Authentication"), self.auth)
        form.addRow("", self.list_all)

        test = QPushButton(tr("Test Connection"))
        test.clicked.connect(self.test)
        buttons = QDialogButtonBox(compat.SAVE | compat.CANCEL)
        buttons.addButton(test, compat.ACTION_ROLE)
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
            "list_all_tables": self.list_all.isChecked(),
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
    return dlg.data()["name"] if dlg.exec() else None


def edit_connection(controller, name, parent=None):
    dlg = ConnectionDialog(controller, parent, connections.load(name))
    return dlg.data()["name"] if dlg.exec() else None


def remove_connection(name, parent=None):
    answer = QMessageBox.question(parent, tr("Remove"), tr("Remove connection {}?").format(name))
    if answer == compat.YES:
        connections.remove(name)
        return True
    return False


class OptionsForm(QWidget):
    """Filter, limit, fallback CRS and output file of a load."""

    def __init__(self, parent=None, with_crs=True):
        super().__init__(parent)
        self.where = QLineEdit()
        self.where.setPlaceholderText(tr("optional SQL filter, e.g. region = 'north'"))
        self.limit = QSpinBox()
        self.limit.setRange(0, 2_000_000_000)
        self.limit.setSpecialValueText(tr("No limit"))
        self.crs = QgsProjectionSelectionWidget()
        self.crs.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
        self.output = QgsFileWidget()
        self.output.setStorageMode(compat.SAVE_FILE)
        self.output.setFilter("GeoPackage (*.gpkg)")
        self.output.lineEdit().setPlaceholderText(tr("temporary file"))

        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        form.addRow(tr("Filter (WHERE)"), self.where)
        form.addRow(tr("Row limit"), self.limit)
        if with_crs:
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

    def __init__(self, source, parent=None, where=""):
        super().__init__(parent)
        self.setWindowTitle(tr("Add {}").format(sources.label(source)))
        self.setWindowIcon(icon())
        self.form = OptionsForm(with_crs=bool(source["column"]))
        self.form.where.setText(where or "")
        buttons = QDialogButtonBox(compat.CANCEL)
        buttons.addButton(tr("Add Layer"), compat.ACCEPT_ROLE)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        detail = f" ({source['column']})" if source["column"] else tr(" (no geometry)")
        layout.addWidget(QLabel(sources.label(source) + detail))
        layout.addWidget(self.form)
        layout.addWidget(buttons)
        self.resize(520, self.sizeHint().height())


# results ------------------------------------------------------------------------


def display(value):
    """Short text for a grid cell; geometries and binaries are summarized."""
    if value is None:
        return "NULL"
    if sql.looks_like_wkb(value):
        return tr("<WKB/binary, {} bytes>").format(len(value) // 2)
    text = str(value)
    return text if len(text) <= CELL_CHARS else text[:CELL_CHARS] + "…"


def set_error(label, error):
    label.setStyleSheet("color: #c0392b; font-weight: bold;" if error else "")
    label.setWordWrap(True)


def failure_text(task):
    if task.error is None:
        return tr("Canceled.")
    return tr("Query failed: {}").format(str(task.error).strip())


def cancel_task(task):
    """Cancel a running task. QGIS deletes the C++ side of a task once it
    finishes, so a finished one raises RuntimeError: nothing to cancel."""
    if task is None:
        return
    try:
        if not task.isCanceled():
            task.cancel()
    except RuntimeError:
        pass


class ResultsTable(QTableWidget):
    """Read-only grid of query results: click a header to sort, filter rows
    with apply_filter(); raw_row() gives back the untruncated values."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.headers, self.rows = [], []
        self.setEditTriggers(compat.NO_EDIT_TRIGGERS)
        self.setSelectionBehavior(compat.SELECT_ROWS)
        self.setSelectionMode(compat.EXTENDED_SELECTION)
        self.setContextMenuPolicy(compat.ACTIONS_CONTEXT_MENU)

    def set_result(self, headers, rows):
        self.setSortingEnabled(False)
        self.clear()
        self.headers, self.rows = list(headers), list(rows)
        self.setColumnCount(len(headers))
        self.setRowCount(len(rows))
        self.setHorizontalHeaderLabels(self.headers)
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                item = QTableWidgetItem()
                if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
                    item.setData(compat.DISPLAY_ROLE, float(value) if isinstance(value, Decimal) else value)
                else:
                    item.setText(display(value))
                if value is not None and len(str(value)) > CELL_CHARS and not sql.looks_like_wkb(value):
                    item.setToolTip(str(value)[:2000])
                item.setData(compat.USER_ROLE, r)
                self.setItem(r, c, item)
        self.resizeColumnsToContents()
        for c in range(self.columnCount()):
            self.setColumnWidth(c, min(self.columnWidth(c), 320))
        self.horizontalHeader().setSortIndicator(-1, compat.ASCENDING)  # keep server order
        self.setSortingEnabled(True)

    def raw_row(self, item):
        return self.rows[item.data(compat.USER_ROLE)]

    def selected_rows(self):
        """Raw values of the selected, visible rows, in grid order."""
        rows = sorted({item.row() for item in self.selectedItems()})
        return [self.raw_row(self.item(r, 0)) for r in rows if not self.isRowHidden(r) and self.item(r, 0)]

    def add_map_action(self, callback):
        """"Show selected on map" button and context-menu entry."""
        action = QAction(tr("Show Selected on Map"), self)
        action.triggered.connect(callback)
        self.addAction(action)
        button = QPushButton(tr("Show Selected on Map"))
        button.setAutoDefault(False)
        button.setToolTip(tr("Select rows with Ctrl/Shift+click or Ctrl+A"))
        button.clicked.connect(callback)
        return button

    def apply_filter(self, text, column=-1):
        """Hide rows whose cells (or the given column) do not contain text."""
        text = (text or "").lower()
        shown = 0
        for r in range(self.rowCount()):
            columns = range(self.columnCount()) if column < 0 else [column]
            hit = not text or any(
                self.item(r, c) is not None and text in self.item(r, c).text().lower() for c in columns
            )
            self.setRowHidden(r, not hit)
            shown += hit
        return shown


class FilterBar(QWidget):
    """Quick filter over the rows already shown (no new query)."""

    ALL = tr("All columns")

    def __init__(self, table, parent=None):
        super().__init__(parent)
        self.table = table
        self.text = QLineEdit()
        self.text.setPlaceholderText(tr("Filter shown rows…"))
        self.text.setClearButtonEnabled(True)
        self.column = QComboBox()
        self.column.addItem(self.ALL)
        self.text.textChanged.connect(self.apply)
        self.column.currentIndexChanged.connect(self.apply)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.text, 1)
        layout.addWidget(self.column)

    def set_columns(self, headers):
        current = self.column.currentText()
        self.column.blockSignals(True)
        self.column.clear()
        self.column.addItem(self.ALL)
        self.column.addItems(list(headers))
        if current in headers:
            self.column.setCurrentText(current)
        self.column.blockSignals(False)
        self.apply()

    def apply(self, *args):
        return self.table.apply_filter(self.text.text(), self.column.currentIndex() - 1)


class PreviewDialog(QDialog):
    """First rows of a table, optionally filtered on the server, without
    creating a layer. Double click a row to see it on the map."""

    def __init__(self, controller, conn, source, parent=None, where=""):
        super().__init__(parent)
        self.controller = controller
        self.conn = conn
        self.source = source
        self.serial = 0  # only the latest query may fill the grid
        self.task = None
        self.done = False
        self.map_note = ""
        self.setWindowTitle(tr("Preview {}").format(sources.label(source)))
        self.setWindowIcon(icon())
        self.resize(900, 520)

        self.where = QLineEdit()
        self.where.setPlaceholderText(tr("SQL filter on the whole table, e.g. region = 'north'"))
        self.where.returnPressed.connect(self.run)
        self.where.setText(where or "")
        self.limit = QSpinBox()
        self.limit.setRange(1, 10_000)
        self.limit.setValue(sql.PREVIEW_ROWS)
        apply = QPushButton(tr("Apply"))
        apply.setAutoDefault(False)  # Enter already runs the query via returnPressed
        apply.clicked.connect(self.run)
        self.filter_map = QCheckBox(tr("Also filter this table's layers on the map"))
        self.filter_map.setChecked(True)
        top = QHBoxLayout()
        top.addWidget(QLabel(tr("WHERE")))
        top.addWidget(self.where, 1)
        top.addWidget(QLabel(tr("Rows")))
        top.addWidget(self.limit)
        top.addWidget(apply)

        self.status = QLabel()
        self.table = ResultsTable()
        self.table.itemDoubleClicked.connect(self.show_on_map)
        self.filter = FilterBar(self.table)
        hint = tr("Double-click a row to show it on the map, or select several rows and click "
                  "'Show Selected on Map'.") if source["column"] else ""
        buttons = QDialogButtonBox(compat.CLOSE)
        buttons.rejected.connect(self.reject)
        if source["column"]:
            buttons.addButton(self.table.add_map_action(self.show_selected_on_map), compat.ACTION_ROLE)
            clear = buttons.addButton(tr("Clear Records"), compat.ACTION_ROLE)
            clear.setAutoDefault(False)
            clear.setToolTip(tr("Empty the temporary \"(records)\" layer of this table"))
            clear.clicked.connect(self.clear_records)
        add = buttons.addButton(tr("Add Layer…"), compat.ACTION_ROLE)
        add.setAutoDefault(False)
        add.setToolTip(tr("Load every row that matches the WHERE above, not only the rows shown"))
        add.clicked.connect(self.add_layer)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.filter_map)
        layout.addWidget(self.filter)
        layout.addWidget(self.status)
        layout.addWidget(self.table, 1)
        layout.addWidget(QLabel(hint))
        layout.addWidget(buttons)
        self.run()

    def run(self):
        cancel_task(self.task)
        self.task = None
        self.done = False
        query = sql.preview_query(
            sql.table_ref(self.source["schema"], self.source["table"]), self.limit.value(), self.where.text()
        )
        self.status.setText(tr("Running…"))
        self.map_note = self.filter_on_map()
        self.serial += 1
        serial = self.serial

        def latest_only(task, ok):
            if serial == self.serial:
                self.show_result(task, ok)

        task = self.controller.run_query(self.conn, query, sources.label(self.source), latest_only, self)
        if task is None:
            self.status.setText(tr("Canceled."))
        elif not self.done:  # the result may already be here
            self.task = task

    def show_result(self, task, ok):
        self.done = True
        self.task = None
        if ok:
            self.table.set_result(task.headers, task.rows)
            self.filter.set_columns(task.headers)
            self.status.setText(tr("{} rows.").format(len(task.rows)) + self.map_note)
            set_error(self.status, False)
        else:
            # Never leave the previous rows on screen: they look like an
            # unfiltered result.
            self.table.set_result([], [])
            self.status.setText(failure_text(task))
            set_error(self.status, bool(task.error))

    def filter_on_map(self):
        """Apply the WHERE to the layers loaded from this table; returns a
        note for the status line."""
        if not self.filter_map.isChecked():
            return ""
        where = sql.clean_filter(self.where.text())
        done, failed = self.controller.filter_layers(sources.label(self.source), where)
        note = ""
        if done:
            note += tr(" Map: {} layer(s) filtered.").format(len(done)) if where else tr(" Map: filter removed from {} layer(s).").format(len(done))
        if failed:
            note += tr(" Map: {} layer(s) did not accept this filter (use simple SQL).").format(len(failed))
        return note

    def show_on_map(self, item):
        if not self.source["column"]:
            self.status.setText(tr("This table has no geometry."))
            return
        self.controller.show_record(
            sources.label(self.source), self.table.headers, self.table.raw_row(item), self.source["column"]
        )

    def show_selected_on_map(self):
        rows = self.table.selected_rows()
        if not rows:
            self.status.setText(tr("Select one or more rows first."))
            return
        self.controller.show_records(sources.label(self.source), self.table.headers, rows, self.source["column"])

    def clear_records(self):
        removed = self.controller.clear_records(sources.label(self.source))
        self.status.setText(tr("{} record(s) removed from the map.").format(removed))

    def add_layer(self):
        """Load every row matching the current WHERE, with the usual options."""
        dlg = LoadOptionsDialog(self.source, self, where=sql.clean_filter(self.where.text()))
        if dlg.exec():
            self.controller.load(self.conn, self.source, dlg.form.options(), self)

    def reject(self):
        cancel_task(self.task)
        self.task = None
        super().reject()


def open_preview(controller, conn, source, parent=None, where=None):
    """One preview window per connection and table: opening it again
    brings the existing window back (with the new filter, if one is given)
    instead of stacking identical windows."""
    key = (conn["name"], sources.label(source))
    dlg = controller.previews.get(key)
    try:
        alive = dlg is not None and dlg.isVisible() is not None
    except RuntimeError:  # deleted with its parent window
        alive = False
    if not alive:
        dlg = PreviewDialog(controller, conn, source, parent, where=where or "")
        controller.previews[key] = dlg
    elif where is not None and where != dlg.where.text():
        dlg.where.setText(where)
        dlg.run()
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    return dlg


class SqlDialog(QDialog):
    """Run any SELECT, look at the first rows and load the result as a
    layer (or a table, without geometry). The query always runs wrapped as a
    subquery, so statements that change data cannot run."""

    NO_GEOMETRY = tr("(no geometry)")

    def __init__(self, controller, conn_name=None, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.task = None
        self.setWindowTitle(tr("Redshift Spatial — SQL"))
        self.setWindowIcon(icon())
        self.resize(960, 720)

        self.conn_combo = QComboBox()
        self.conn_combo.addItems(connections.names())
        if conn_name:
            self.conn_combo.setCurrentText(conn_name)

        self.editor = QPlainTextEdit()
        self.editor.setFont(QFontDatabase.systemFont(compat.FIXED_FONT))
        self.editor.setPlaceholderText("SELECT id, name, geom\nFROM analytics.parcels\nWHERE region = 'north'")
        self.run_button = QPushButton(tr("Execute"))
        self.run_button.setShortcut(QKeySequence("Ctrl+Return"))
        self.run_button.setToolTip("Ctrl+Enter")
        self.run_button.clicked.connect(self.execute)
        self.cancel_button = QPushButton(tr("Cancel"))
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel)
        self.status = QLabel(tr("Only SELECT queries; the first {} rows are shown.").format(sql.SQL_PREVIEW_ROWS))
        self.table = ResultsTable()
        self.table.itemDoubleClicked.connect(self.show_on_map)
        self.filter = FilterBar(self.table)

        self.geometry = QComboBox()
        self.geometry.addItem(self.NO_GEOMETRY)
        self.layer_name = QLineEdit("query")
        self.form = OptionsForm()
        load = QPushButton(tr("Add Layer"))
        load.clicked.connect(self.load)

        top = QHBoxLayout()
        top.addWidget(QLabel(tr("Connection")))
        top.addWidget(self.conn_combo, 1)
        top.addWidget(self.run_button)
        top.addWidget(self.cancel_button)

        load_form = QFormLayout()
        load_form.addRow(tr("Geometry column"), self.geometry)
        load_form.addRow(tr("Layer name"), self.layer_name)
        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.addWidget(self.status)
        bottom_layout.addWidget(self.filter)
        bottom_layout.addWidget(self.table, 1)
        map_row = QHBoxLayout()
        map_row.addWidget(QLabel(tr("Double-click a row to show it on the map, or select several rows:")), 1)
        map_row.addWidget(self.table.add_map_action(self.show_selected_on_map))
        clear = QPushButton(tr("Clear Records"))
        clear.setAutoDefault(False)
        clear.clicked.connect(self.clear_records)
        map_row.addWidget(clear)
        bottom_layout.addLayout(map_row)
        bottom_layout.addLayout(load_form)
        bottom_layout.addWidget(self.form)
        bottom_layout.addWidget(load)

        splitter = QSplitter()
        splitter.setOrientation(compat.VERTICAL)
        splitter.addWidget(self.editor)
        splitter.addWidget(bottom)
        splitter.setStretchFactor(1, 2)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(splitter, 1)

    def connection(self):
        name = self.conn_combo.currentText()
        if not name:
            QMessageBox.information(self, tr("No connection"), tr("Create a connection first."))
            return None
        return connections.load(name)

    def query_text(self):
        try:
            return sql.clean_query(self.editor.toPlainText())
        except ValueError:
            QMessageBox.information(self, tr("Empty query"), tr("Write a SELECT first."))
            return None

    def execute(self):
        conn, text = self.connection(), self.query_text()
        if conn is None or text is None:
            return
        preview = sql.preview_query(sql.query_from(text), sql.SQL_PREVIEW_ROWS)
        self.status.setText(tr("Running…"))
        self.run_button.setEnabled(False)
        self.done = False
        task = self.controller.run_query(conn, preview, "SQL", self.show_result, self)
        if task is None:
            self.run_button.setEnabled(True)
            self.status.setText(tr("Canceled."))
        elif not self.done:  # the result may already be here
            self.task = task
            self.cancel_button.setEnabled(True)

    def cancel(self):
        cancel_task(self.task)

    def show_result(self, task, ok):
        self.done = True
        self.task = None
        self.run_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        if not ok:
            self.table.set_result([], [])
            self.status.setText(failure_text(task))
            set_error(self.status, bool(task.error))
            return
        set_error(self.status, False)
        self.table.set_result(task.headers, task.rows)
        self.filter.set_columns(task.headers)
        self.status.setText(tr("{} rows shown (at most {}).").format(len(task.rows), sql.SQL_PREVIEW_ROWS))
        previous = self.geometry.currentText()
        self.geometry.clear()
        self.geometry.addItem(self.NO_GEOMETRY)
        self.geometry.addItems(list(task.headers))
        guess = guess_geometry_column(task.headers, task.rows)
        if previous in task.headers:
            self.geometry.setCurrentText(previous)
        elif guess:
            self.geometry.setCurrentText(guess)

    def show_on_map(self, item):
        column = self.geometry.currentText()
        if column == self.NO_GEOMETRY:
            self.status.setText(tr("Choose the geometry column first."))
            return
        name = self.layer_name.text().strip() or "query"
        self.controller.show_record(name, self.table.headers, self.table.raw_row(item), column)

    def show_selected_on_map(self):
        column = self.geometry.currentText()
        if column == self.NO_GEOMETRY:
            self.status.setText(tr("Choose the geometry column first."))
            return
        rows = self.table.selected_rows()
        if not rows:
            self.status.setText(tr("Select one or more rows first."))
            return
        name = self.layer_name.text().strip() or "query"
        self.controller.show_records(name, self.table.headers, rows, column)

    def clear_records(self):
        removed = self.controller.clear_records(self.layer_name.text().strip() or "query")
        self.status.setText(tr("{} record(s) removed from the map.").format(removed))

    def load(self):
        conn, text = self.connection(), self.query_text()
        if conn is None or text is None:
            return
        column = self.geometry.currentText()
        column = None if column == self.NO_GEOMETRY else column
        name = self.layer_name.text().strip() or "query"
        self.controller.load(conn, sources.query(text, column, name), self.form.options(), self)

    def reject(self):
        self.cancel()
        super().reject()


def guess_geometry_column(headers, rows):
    """First column whose values look like WKB in the preview."""
    for c, name in enumerate(headers):
        values = [row[c] for row in rows if row[c] is not None]
        if values and all(sql.looks_like_wkb(v) for v in values[:20]):
            return name
    return None


# Add layer window -----------------------------------------------------------------


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

        buttons = QDialogButtonBox(compat.CLOSE)
        btn_preview = buttons.addButton(tr("Preview Rows"), compat.ACTION_ROLE)
        btn_preview.clicked.connect(lambda: self.preview(self.tree.currentItem()))
        btn_sql = buttons.addButton(tr("SQL…"), compat.ACTION_ROLE)
        btn_sql.clicked.connect(self.open_sql)
        btn_load = buttons.addButton(tr("Add Layer"), compat.ACCEPT_ROLE)
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
                rows = db.list_tables(params, conn["list_all_tables"])
        except Exception as e:
            QMessageBox.critical(self, tr("Connection failed"), str(e))
            return
        self.tree.clear()
        schemas = {}
        for row in rows:
            schema, table, column, data_type = row
            parent = schemas.get(schema)
            if parent is None:
                parent = schemas[schema] = QTreeWidgetItem(self.tree, [schema])
            item = QTreeWidgetItem(parent, [table, column or "", data_type or tr("no geometry")])
            item.setData(0, compat.USER_ROLE, sources.from_row(row))
        self.tree.expandAll()
        self.tree.resizeColumnToContents(0)
        if not rows:
            QMessageBox.information(self, tr("No tables"), tr("No table is visible to this user."))
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

    def selected_source(self, item):
        source = item.data(0, compat.USER_ROLE) if item else None
        if not source:
            QMessageBox.information(self, tr("Choose a table"), tr("Select a table in the list."))
        return source

    def load(self, item):
        source = self.selected_source(item)
        conn = self.current_connection() if source else None
        if conn is not None:
            self.controller.load(conn, source, self.form.options(), self)

    def preview(self, item):
        source = self.selected_source(item)
        conn = self.current_connection() if source else None
        if conn is not None:
            open_preview(self.controller, conn, source, self, where=self.form.where.text())

    def open_sql(self):
        SqlDialog(self.controller, self.conn_combo.currentText(), self).show()
