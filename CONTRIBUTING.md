# Contributing

Thanks for helping! Issues and pull requests are welcome.

## Before opening a pull request

1. Run the tests (see *Development* in the README):

       uvx pytest
       docker run --rm -v "$PWD:/plugin" -w /plugin qgis/qgis:release-3_28 python3 tests/run_qgis.py

2. Add a test for the bug or the behaviour you change. `tests/helpers.py`
   has a fake Redshift, so most cases need no cluster.
3. Keep the plugin working on the minimum QGIS version in `metadata.txt`.
4. Do not commit credentials, endpoints, real table names or data from your
   own clusters. CI runs a secret scan.
5. Write commit messages in English.

## License

By contributing you agree that your contribution is licensed under the
GNU General Public License v2.0 or later, the license of this project.
