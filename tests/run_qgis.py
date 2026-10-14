# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 CEOX Planejamento e Otimização
"""Runs every test_* function of tests/qgis_*.py inside the QGIS Python,
offscreen, without a database.

Windows:  "C:\\Program Files\\QGIS 3.44.12\\bin\\python-qgis-ltr.bat" tests\\run_qgis.py
Docker:   docker run --rm -v "$PWD:/plugin" -w /plugin qgis/qgis:release-3_28 python3 tests/run_qgis.py

Optional argument: a substring to select tests by name.
"""

import importlib
import os
import pathlib
import sys
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
TESTS = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(TESTS.parent), str(TESTS)]

from qgis.core import Qgis, QgsApplication  # noqa: E402

app = QgsApplication([], True)
app.initQgis()


def main():
    selected = sys.argv[1] if len(sys.argv) > 1 else ""
    print(f"QGIS {Qgis.QGIS_VERSION}")
    passed = failed = 0
    for path in sorted(TESTS.glob("qgis_*.py")):
        module = importlib.import_module(path.stem)
        for name, fn in vars(module).items():
            if not name.startswith("test_") or not callable(fn) or selected not in name:
                continue
            try:
                fn()
                passed += 1
                print(f"ok   {path.stem}.{name}")
            except Exception:  # noqa: BLE001
                failed += 1
                print(f"FAIL {path.stem}.{name}")
                traceback.print_exc()
    print(f"{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    code = main()
    app.exitQgis()
    sys.exit(code)
