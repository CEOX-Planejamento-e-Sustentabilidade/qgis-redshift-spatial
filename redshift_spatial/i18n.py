# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 CEOX Planejamento e Otimização
"""Interface texts. The source texts are English; when QGIS runs in
Portuguese they come from PT_BR. A plain dict instead of Qt .ts/.qm files,
so no Qt tools are needed to build the plugin. Texts with {} are filled by
str.format after translation."""

PT_BR = {
    # menus and Browser panel
    "&Redshift Spatial": "&Redshift Spatial",
    "Add Redshift Spatial Layer…": "Adicionar Camada Redshift Spatial…",
    "Add Redshift Spatial Layer": "Adicionar Camada Redshift Spatial",
    "Execute SQL…": "Executar SQL…",
    "New Connection…": "Nova Conexão…",
    "Edit Connection…": "Editar Conexão…",
    "Remove Connection": "Remover Conexão",
    "Refresh": "Atualizar",
    "Add Layer": "Adicionar Camada",
    "Add Layer with Filter…": "Adicionar Camada com Filtro…",
    "Preview Rows…": "Pré-visualização…",
    "Preview Rows": "Pré-visualização",
    "Edit Redshift Query…": "Editar Consulta Redshift…",
    "no geometry": "sem geometria",
    # connection
    "Redshift Spatial Connection": "Conexão Redshift Spatial",
    "Name": "Nome",
    "Host": "Host",
    "Port": "Porta",
    "Database": "Banco de dados",
    "SSL mode": "Modo SSL",
    "Username": "Usuário",
    "Username:": "Usuário:",
    "Authentication": "Autenticação",
    "used when no authentication is selected": "usado quando nenhuma autenticação é selecionada",
    "Also list tables without geometry": "Listar também tabelas sem geometria",
    "Passwords are kept only in the QGIS authentication database.":
        "As senhas ficam só no banco de autenticação do QGIS.",
    "Test Connection": "Testar Conexão",
    "Connection succeeded": "Conexão bem-sucedida",
    "Connection failed": "Falha na conexão",
    "Invalid name": "Nome inválido",
    "Enter a name without slashes.": "Digite um nome sem barras.",
    "Missing data": "Dados faltando",
    "Host and database are required.": "Host e banco de dados são obrigatórios.",
    "Remove": "Remover",
    "Remove connection {}?": "Remover a conexão {}?",
    "Password for {}:": "Senha de {}:",
    "Connection {} no longer exists.": "A conexão {} não existe mais.",
    "No connection": "Nenhuma conexão",
    "Create a connection first.": "Crie uma conexão primeiro.",
    "Redshift connection: {}": "Conexão Redshift: {}",
    # load options
    "Add {}": "Adicionar {}",
    "Edit {}": "Editar {}",
    "Filter (WHERE)": "Filtro (WHERE)",
    "optional SQL filter, e.g. region = 'north'": "filtro SQL opcional, ex.: regiao = 'norte'",
    "Row limit": "Limite de linhas",
    "No limit": "Sem limite",
    "CRS when SRID is 0": "SRC quando o SRID é 0",
    "Save to": "Salvar em",
    "temporary file": "arquivo temporário",
    "Counting rows…": "Contando linhas…",
    "{} rows will be loaded.": "{} linhas serão carregadas.",
    "{} of {} matching rows will be loaded (row limit).":
        "{} de {} linhas do filtro serão carregadas (limite de linhas).",
    "Replace the current layer (same place in the Layers panel, same style)":
        "Substituir a camada atual (mesmo lugar no painel Camadas, mesmo estilo)",
    # loading
    "Loading {}…": "Carregando {}…",
    "{}: {} rows loaded.": "{}: {} linhas carregadas.",
    "{}: no rows.": "{}: nenhuma linha.",
    "{}: canceled.": "{}: cancelado.",
    "{}: {}": "{}: {}",
    "File exists": "Arquivo já existe",
    "{} already exists. Replace it?\nLayers using it will be removed from the project.":
        "{} já existe. Substituir?\nAs camadas que usam o arquivo serão removidas do projeto.",
    "{} is still in use; writing to {}.": "{} ainda está em uso; gravando em {}.",
    "{} was not loaded by Redshift Spatial.": "{} não foi carregada pelo Redshift Spatial.",
    "Skipped column {} ({}).": "Coluna {} ({}) ignorada.",
    "SRID {} is unknown to QGIS; using {}.": "SRID {} desconhecido no QGIS; usando {}.",
    "SRID 0 (undefined); using {}.": "SRID 0 (indefinido); usando {}.",
    "Sample has {} SRIDs; all rows were written as {}.":
        "A amostra tem {} SRIDs; todas as linhas foram gravadas como {}.",
    # preview
    "Preview {}": "Pré-visualização de {}",
    "WHERE": "WHERE",
    "SQL filter on the whole table, e.g. region = 'north'": "Filtro SQL na tabela inteira, ex.: regiao = 'norte'",
    "Apply": "Aplicar",
    "Also filter this table's layers on the map": "Filtrar também as camadas desta tabela no mapa",
    "Rows": "Linhas",
    "Filter shown rows…": "Filtrar linhas exibidas…",
    "All columns": "Todas as colunas",
    "{} rows.": "{} linhas.",
    "Showing {} of {} matching rows.": "Exibindo {} de {} linhas do filtro.",
    "All {} matching rows shown.": "Todas as {} linhas do filtro exibidas.",
    "{} rows match the filter.": "{} linhas atendem ao filtro.",
    " Map: {} layer(s) filtered.": " Mapa: {} camada(s) filtrada(s).",
    " Map: filter removed from {} layer(s).": " Mapa: filtro removido de {} camada(s).",
    " Map: {} layer(s) did not accept this filter (use simple SQL).":
        " Mapa: {} camada(s) não aceitaram este filtro (use SQL simples).",
    "Query failed: {}": "A consulta falhou: {}",
    "Canceled.": "Cancelado.",
    "<WKB/binary, {} bytes>": "<WKB/binário, {} bytes>",
    "Double-click a row to show it on the map, or select several rows and click 'Show Selected on Map'.":
        "Clique duas vezes numa linha para vê-la no mapa, ou selecione várias e clique em "
        "'Mostrar Selecionadas no Mapa'.",
    "Double-click a row to show it on the map, or select several rows:":
        "Clique duas vezes numa linha para vê-la no mapa, ou selecione várias:",
    "Show Selected on Map": "Mostrar Selecionadas no Mapa",
    "Select rows with Ctrl/Shift+click or Ctrl+A": "Selecione linhas com Ctrl/Shift+clique ou Ctrl+A",
    "Select one or more rows first.": "Selecione uma ou mais linhas primeiro.",
    "This table has no geometry.": "Esta tabela não tem geometria.",
    "Clear Records": "Limpar Registros",
    "Empty the temporary \"(records)\" layer of this table":
        "Esvaziar a camada temporária \"(registros)\" desta tabela",
    "{} (records)": "{} (registros)",
    "{} record(s) removed from the map.": "{} registro(s) removido(s) do mapa.",
    "Add Layer ({} selected)…": "Adicionar Camada ({} selecionadas)…",
    "Add Layer (all matching)…": "Adicionar Camada (todas do filtro)…",
    "With rows selected: only those rows, or every row matching the WHERE":
        "Com linhas selecionadas: só essas linhas, ou todas as que atendem ao WHERE",
    "{} row(s) are selected. What should the new layer contain?":
        "{} linha(s) selecionada(s). O que a nova camada deve conter?",
    "Only the {} selected": "Só as {} selecionadas",
    "All {} matching rows": "Todas as {} linhas do filtro",
    "All matching rows": "Todas as linhas do filtro",
    "{}: {} selected row(s) saved.": "{}: {} linha(s) selecionada(s) salva(s).",
    "{} row(s) without geometry were not saved.": "{} linha(s) sem geometria não foram salvas.",
    "{} row(s) without geometry in {} were skipped.": "{} linha(s) sem geometria em {} foram ignoradas.",
    # SQL window
    "Redshift Spatial — SQL": "Redshift Spatial — SQL",
    "Redshift Spatial — Edit {}": "Redshift Spatial — Editar {}",
    "Connection": "Conexão",
    "Only SELECT queries; the first {} rows are shown.": "Só consultas SELECT; as primeiras {} linhas são exibidas.",
    "Execute": "Executar",
    "Running…": "Executando…",
    "Cancel": "Cancelar",
    "Geometry column": "Coluna de geometria",
    "(no geometry)": "(sem geometria)",
    " (no geometry)": " (sem geometria)",
    "Layer name": "Nome da camada",
    "Column {} is not in the result.": "A coluna {} não está no resultado.",
    "Empty query": "Consulta vazia",
    "Write a SELECT first.": "Escreva um SELECT primeiro.",
    "Choose the geometry column first.": "Escolha a coluna de geometria primeiro.",
    # Add layer window
    "New": "Nova",
    "Edit": "Editar",
    "Connect": "Conectar",
    "Filter tables…": "Filtrar tabelas…",
    "SQL…": "SQL…",
    "Table": "Tabela",
    "Column": "Coluna",
    "Type": "Tipo",
    "No tables": "Nenhuma tabela",
    "No table is visible to this user.": "Nenhuma tabela visível para este usuário.",
    "Choose a table": "Escolha uma tabela",
    "Select a table in the list.": "Selecione uma tabela na lista.",
}

TRANSLATIONS = {"pt": PT_BR}
_language = None


def language():
    """The two-letter language of the QGIS interface, read once."""
    global _language
    if _language is None:
        try:
            from qgis.core import QgsApplication

            _language = (QgsApplication.locale() or "en")[:2].lower()
        except Exception:
            _language = "en"
    return _language


def set_language(code):
    """Force a language (tests); None reads it from QGIS again."""
    global _language
    _language = code


def tr(text):
    return TRANSLATIONS.get(language(), {}).get(text, text)
