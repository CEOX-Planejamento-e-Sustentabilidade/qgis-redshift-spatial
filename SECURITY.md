# Security policy

## Reporting a vulnerability

Please do **not** open a public issue for security problems. Use GitHub's
[private vulnerability reporting](../../security/advisories/new) instead, and
include the plugin version, the QGIS version and the steps to reproduce.

We aim to acknowledge reports within 5 business days.

## Scope and design

- The plugin is read only: it issues `SELECT`, `DECLARE` and `FETCH`
  statements and never writes to Redshift.
- Passwords are never written to the QGIS settings. They are kept in the
  QGIS authentication database (encrypted with the master password) or asked
  for once per session and held in memory.
- The optional `WHERE` filter is sent to Redshift as typed, with the
  privileges of the connecting user. Use a read-only database user.
- Never paste connection strings, endpoints or credentials into issues or
  logs you share.
