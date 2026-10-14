# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 CEOX Planejamento e Otimização
import ast
import pathlib
import string

from redshift_spatial import i18n

PLUGIN = pathlib.Path(__file__).resolve().parent.parent / "redshift_spatial"


def texts_in_code():
    found = set()
    for path in PLUGIN.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "tr":
                (arg,) = node.args
                assert isinstance(arg, ast.Constant), f"{path.name}:{node.lineno}: tr() needs a literal"
                found.add(arg.value)
    return found


def fields(text):
    return [f for _, f, _, _ in string.Formatter().parse(text) if f is not None]


def test_every_text_has_a_portuguese_translation():
    code = texts_in_code()
    assert code - i18n.PT_BR.keys() == set()
    assert i18n.PT_BR.keys() - code == set()


def test_translations_keep_the_placeholders():
    for source, target in i18n.PT_BR.items():
        assert fields(source) == fields(target), source


def test_tr_follows_the_language():
    try:
        i18n.set_language("pt")
        assert i18n.tr("Add Layer with Filter…") == "Adicionar Camada com Filtro…"
        assert i18n.tr("not translated") == "not translated"
        i18n.set_language("en")
        assert i18n.tr("Add Layer with Filter…") == "Add Layer with Filter…"
    finally:
        i18n.set_language(None)
