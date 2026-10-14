# Redshift Spatial (QGIS plugin)

Load `GEOMETRY` and `GEOGRAPHY` columns from Amazon Redshift into QGIS.

## Why

QGIS reads database layers through its PostgreSQL provider, which requires
PostGIS. Redshift speaks the PostgreSQL protocol but has no PostGIS (and no
`CREATE EXTENSION`), so the provider connects and then fails with
"PostGIS support is not available" / "Could not retrieve table". A native
Redshift provider was proposed upstream
([QGIS#53018](https://github.com/qgis/QGIS/pull/53018),
[QEP#272](https://github.com/qgis/QGIS-Enhancement-Proposals/issues/272))
but never merged.

This plugin sidesteps the provider: it queries Redshift with the `psycopg2`
bundled in QGIS, reads geometries as WKB (`ST_AsBinary`) and writes them to a
GeoPackage that QGIS opens natively.

## Features

- **Browser panel entry "Redshift Spatial"**: connection > schema > table.
  Double click a table to add it, or right click for *Add Layer with
  Filter…*. (Dragging onto the map needs a native data provider, which
  Redshift lacks.)
- Saved connections; passwords live only in the QGIS authentication database
  (or are asked for once per session).
- Lists every geometry/geography column visible to the user, from
  `SVV_COLUMNS` (late-binding views included).
- Optional `WHERE` filter and row limit.
- CRS from `ST_SRID`; a fallback CRS for SRID 0.
- Runs as a background task with progress and cancel.
- One layer per geometry family; single geometries are promoted to multi, so
  `POLYGON` and `MULTIPOLYGON` share a layer.
- Read only: the plugin never writes to Redshift.

## Install

    python scripts/package.py

then *Plugins → Manage and Install Plugins → Install from ZIP* with
`dist/redshift_spatial-<version>.zip`. The plugin appears in the Browser
panel and under *Database → Redshift Spatial*.

The icon is original artwork, not the AWS Redshift logo, which AWS licenses
for architecture diagrams only.

## Redshift specifics handled

| Issue | Handling |
|---|---|
| No PostGIS catalog (`geometry_columns`, `spatial_ref_sys`) | discovery via `SVV_COLUMNS`, SRID via `ST_SRID` |
| `VARBYTE` arrives as hex text | decoded client side |
| psycopg2 named cursors send `WITHOUT HOLD`, rejected by Redshift | explicit `DECLARE` / `FETCH` |
| Single-node clusters cap `FETCH` at 1000 rows | fetch size 1000 |
| `ST_AsText` of large polygons exceeds the `VARCHAR` limit | WKB instead of WKT |

## Limitations

- Data is copied into a GeoPackage at load time; it is not a live layer.
- Columns of type `VARBYTE` and `HLLSKETCH` are skipped; `SUPER` is loaded as
  JSON text.
- If a table mixes SRIDs, every row is written with the most common one.

## Development

    uvx pytest                    # SQL helpers, no QGIS needed

    # smoke and edge-case tests inside QGIS, offscreen, no database
    "C:\Program Files\QGIS 3.44.12\bin\python-qgis-ltr.bat" tests\run_qgis.py
un_qgis.py
    docker run --rm -v "$PWD:/plugin" -w /plugin qgis/qgis:release-3_28 python3 tests/run_qgis.py

`tests/helpers.py` has a fake Redshift that answers the plugin's queries, so
the whole load (columns, SRID, cursor batches, errors, cancel) runs without a
cluster. CI runs both suites on QGIS 3.28 (minimum), 3.40 (LTR), 3.44 and
`latest`.

Before a release, check by hand against a real cluster: connect, list tables,
load with and without a filter, cancel a load, reload into the same file.

## License

Copyright (C) 2026 CEOX Planejamento e Otimização.

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 2 of the License, or (at your option) any later
version. See [LICENSE](LICENSE).

Security issues: see [SECURITY.md](SECURITY.md). Contributions:
[CONTRIBUTING.md](CONTRIBUTING.md).
