# -*- coding: utf-8 -*-
"""Layout dos arquivos de dados abertos do CNPJ.

Mapeamento herdado do projeto `CNPJ` de 2024 do autor, conferido contra os
arquivos da competencia 2026-09. Os arquivos vem em latin-1, separados por
ponto e virgula, com todo campo entre aspas, e sem linha de cabecalho.
"""

EMPRESAS = (
    "cnpj_basico", "razao_social", "natureza_juridica",
    "qualificacao_responsavel", "capital_social", "porte", "ente_federativo",
)

ESTABELECIMENTOS = (
    "cnpj_basico", "cnpj_ordem", "cnpj_dv", "identificador_matriz_filial",
    "nome_fantasia", "situacao_cadastral", "data_situacao_cadastral",
    "motivo_situacao_cadastral", "nome_cidade_exterior", "pais",
    "data_inicio_atividade", "cnae_fiscal_principal", "cnae_fiscal_secundaria",
    "tipo_logradouro", "logradouro", "numero", "complemento", "bairro", "cep",
    "uf", "municipio", "ddd1", "telefone1", "ddd2", "telefone2", "ddd_fax",
    "fax", "email", "situacao_especial", "data_situacao_especial",
)

# Natureza juridica 213-5, empresario individual. A razao social dele e o nome
# da pessoa, as vezes com CPF junto: dado de pessoa fisica, fora da base. E
# nenhum empresario individual cabe num ICP de 200 a 5.000 colaboradores.
EMPRESARIO_INDIVIDUAL = "2135"

SITUACAO_ATIVA = "02"

PORTE = {"00": "nao informado", "01": "micro empresa",
         "03": "empresa de pequeno porte", "05": "demais"}
