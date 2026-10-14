# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 CEOX Planejamento e Otimização
"""Saved Redshift connections, stored in the QGIS profile settings.

Passwords are never stored here: either an authentication configuration of
the QGIS auth database (encrypted) is referenced, or the password is asked
for when needed.
"""

from qgis.core import QgsApplication, QgsAuthMethodConfig, QgsSettings

GROUP = "redshift_spatial/connections"
DEFAULTS = {
    "host": "",
    "port": 5439,
    "database": "dev",
    "sslmode": "require",
    "username": "",
    "authcfg": "",
    "list_all_tables": False,
}


def names():
    s = QgsSettings()
    s.beginGroup(GROUP)
    result = s.childGroups()
    s.endGroup()
    return sorted(result, key=str.lower)


def load(name):
    s = QgsSettings()
    data = {"name": name}
    for key, default in DEFAULTS.items():
        value = s.value(f"{GROUP}/{name}/{key}", default)
        if key == "port":
            data[key] = int(value)
        elif isinstance(default, bool):
            data[key] = str(value).lower() in ("true", "1")
        else:
            data[key] = str(value or "")
    return data


def save(name, data):
    s = QgsSettings()
    for key in DEFAULTS:
        s.setValue(f"{GROUP}/{name}/{key}", data.get(key, DEFAULTS[key]))


def remove(name):
    s = QgsSettings()
    s.remove(f"{GROUP}/{name}")


def credentials(conn):
    """(username, password) from the auth configuration; password is None
    when it has to be asked for."""
    username, password = conn.get("username") or "", None
    authcfg = conn.get("authcfg")
    if authcfg:
        cfg = QgsAuthMethodConfig()
        if QgsApplication.authManager().loadAuthenticationConfig(authcfg, cfg, True):
            username = cfg.config("username") or username
            password = cfg.config("password") or None
    return username, password


def params(conn, username, password):
    return {
        "host": conn["host"],
        "port": int(conn["port"]),
        "dbname": conn["database"],
        "user": username,
        "password": password,
        "sslmode": conn["sslmode"],
    }
