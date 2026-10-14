# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 CEOX Planejamento e Otimização
"""Names that differ between QGIS 3 (Qt5) and QGIS 4 (Qt6), resolved once.

Qt6 drops the unscoped enum members (Qt.UserRole -> Qt.ItemDataRole.UserRole)
and QGIS 3.30+ moves several enums into Qgis.*. Every name below works from
QGIS 3.28 on.
"""

from qgis.core import Qgis, QgsTask, QgsVectorFileWriter, QgsWkbTypes
from qgis.gui import QgsFileWidget
from qgis.PyQt.QtCore import QMetaType, Qt, QVariant
from qgis.PyQt.QtGui import QFontDatabase
from qgis.PyQt.QtWidgets import QDialogButtonBox, QLineEdit, QMessageBox

try:  # Qt5 keeps QAction in QtWidgets, Qt6 moved it to QtGui
    from qgis.PyQt.QtWidgets import QAction
except ImportError:  # pragma: no cover - Qt6
    from qgis.PyQt.QtGui import QAction


def _enum(owner, scope, name):
    group = getattr(owner, scope, None)
    if group is not None and hasattr(group, name):
        return getattr(group, name)
    return getattr(owner, name)


# Qt
USER_ROLE = _enum(Qt, "ItemDataRole", "UserRole")
WAIT_CURSOR = _enum(Qt, "CursorShape", "WaitCursor")
UTC = _enum(Qt, "TimeSpec", "UTC")
LOCAL_TIME = _enum(Qt, "TimeSpec", "LocalTime")
YES = _enum(QMessageBox, "StandardButton", "Yes")
NO = _enum(QMessageBox, "StandardButton", "No")
SAVE = _enum(QDialogButtonBox, "StandardButton", "Save")
CANCEL = _enum(QDialogButtonBox, "StandardButton", "Cancel")
CLOSE = _enum(QDialogButtonBox, "StandardButton", "Close")
ACCEPT_ROLE = _enum(QDialogButtonBox, "ButtonRole", "AcceptRole")
ACTION_ROLE = _enum(QDialogButtonBox, "ButtonRole", "ActionRole")
PASSWORD = _enum(QLineEdit, "EchoMode", "Password")
VERTICAL = _enum(Qt, "Orientation", "Vertical")
FIXED_FONT = _enum(QFontDatabase, "SystemFont", "FixedFont")

# QGIS
SAVE_FILE = _enum(QgsFileWidget, "StorageMode", "SaveFile")
CREATE_OR_OVERWRITE_FILE = _enum(QgsVectorFileWriter, "ActionOnExistingFile", "CreateOrOverwriteFile")
NO_ERROR = _enum(QgsVectorFileWriter, "WriterError", "NoError")
CAN_CANCEL = _enum(QgsTask, "Flag", "CanCancel")
INFO = _enum(Qgis, "MessageLevel", "Info")
WARNING = _enum(Qgis, "MessageLevel", "Warning")
CRITICAL = _enum(Qgis, "MessageLevel", "Critical")
SUCCESS = _enum(Qgis, "MessageLevel", "Success")

_WKB = getattr(Qgis, "WkbType", QgsWkbTypes)
GEOMETRY_COLLECTION = _WKB.GeometryCollection
MULTI_POLYGON = _WKB.MultiPolygon
MULTI_LINE_STRING = _WKB.MultiLineString
NO_GEOMETRY = _WKB.NoGeometry
if hasattr(Qgis, "GeometryType"):
    POINT_GEOMETRY = Qgis.GeometryType.Point
    LINE_GEOMETRY = Qgis.GeometryType.Line
    POLYGON_GEOMETRY = Qgis.GeometryType.Polygon
else:
    POINT_GEOMETRY = QgsWkbTypes.PointGeometry
    LINE_GEOMETRY = QgsWkbTypes.LineGeometry
    POLYGON_GEOMETRY = QgsWkbTypes.PolygonGeometry

# QGIS 3.38 deprecated QgsField(name, QVariant.Type) in favour of QMetaType.
if Qgis.QGIS_VERSION_INT >= 33800:
    _names = {"string": "QString", "int": "Int", "int64": "LongLong", "double": "Double",
              "bool": "Bool", "date": "QDate", "datetime": "QDateTime"}
    FIELD_TYPES = {kind: _enum(QMetaType, "Type", name) for kind, name in _names.items()}
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
