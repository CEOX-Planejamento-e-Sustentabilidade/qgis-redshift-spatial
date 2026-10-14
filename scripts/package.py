# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 CEOX Planejamento e Otimização
"""Build dist/redshift_spatial-<version>.zip, installable via
Plugins > Manage and Install Plugins > Install from ZIP."""

import configparser
import pathlib
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "redshift_spatial"


def main():
    meta = configparser.ConfigParser()
    meta.read(PLUGIN / "metadata.txt", encoding="utf-8")
    version = meta["general"]["version"]
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    target = dist / f"redshift_spatial-{version}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(PLUGIN.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                zf.write(path, path.relative_to(ROOT).as_posix())
    print(target)


if __name__ == "__main__":
    main()
