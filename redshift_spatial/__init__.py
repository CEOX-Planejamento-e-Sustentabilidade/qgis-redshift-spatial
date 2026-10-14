# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 CEOX Planejamento e Otimização
def classFactory(iface):
    from .plugin import RedshiftSpatialPlugin

    return RedshiftSpatialPlugin(iface)
