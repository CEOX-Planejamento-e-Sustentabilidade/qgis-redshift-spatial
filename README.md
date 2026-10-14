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

- **Browser panel entry "Redshift Spatial"**: connection > schema > table >
  columns. Double click a table to add it; right click for *Add Layer with
  Filter…* and *Preview Rows…*. (Dragging onto the map needs a native data
  provider, which Redshift lacks.)
- **Execute SQL…** (Browser connection menu or *Database → Redshift
  Spatial*): run any `SELECT`, see the first rows and add the result as a
  layer, picking the geometry column, or as a table without geometry.
  Queries always run wrapped as a subquery, so they cannot change data.
- **Preview Rows…** shows how many rows match ("Showing 100 of 12,345"),
  with a `WHERE` filter that runs on the whole table, a
  quick filter over the rows shown (all columns or one), sortable columns,
  and **double click on a row (or select several and click *Show Selected on
  Map*) to see them on the map** (a temporary
  "(records)" layer, the row selected and zoomed to; *Clear Records* empties
  it). *Add Layer…* saves only the selected rows (no new query) or loads
  every row matching the preview's WHERE; it asks when rows are selected. The same
  works in the SQL window.
- **Edit Redshift Query…** (right click a loaded layer in the Layers panel)
  reopens the query in the SQL window, or the filter and limit of a table
  load. Loading again replaces the layer in place, keeping its position,
  name and style. The query is saved with the project.
- **Tables without geometry** (optional, per connection: *Also list tables
  without geometry*) load as attribute tables, e.g. to join with a layer.
- Saved connections; passwords live only in the QGIS authentication database
  (or are asked for once per session).
- Spatial columns are discovered from `SVV_COLUMNS` (late-binding views
  included).
- Optional `WHERE` filter and row limit; the load options count the rows
  that will be loaded before you confirm. A filtered table is named after
  its filter (`vw_sema_car [codigo_municipio = '5106752']`, cut short when
  long); the layer tooltip shows the whole filter, limit and connection.
  The name follows the filter when the query is edited, unless you
  renamed the layer.
- CRS from `ST_SRID`; a fallback CRS for SRID 0.
- Runs as a background task with progress and cancel.
- One layer per geometry family; single geometries are promoted to multi, so
  `POLYGON` and `MULTIPOLYGON` share a layer.
- Read only: the plugin never writes to Redshift.
- Interface in English or Portuguese (Brazil), following the language of
  QGIS. Texts live in `redshift_spatial/i18n.py`.

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
`latest` (QGIS 4, Qt6). Qt5/Qt6 differences live in `redshift_spatial/compat.py`.

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
