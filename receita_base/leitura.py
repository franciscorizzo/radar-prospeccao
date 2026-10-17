# -*- coding: utf-8 -*-
"""Leitura em fluxo dos zips da Receita, com filtro e projecao na leitura.

Nada e descompactado no disco: cada zip e lido linha a linha, e so sai o que o
indice usa. E a correcao do projeto de 2024, que extraia tudo e quebrava em
pedacos, que e o passo que enche o disco.

O que fica de fora, e por que:
  - empresario individual, porque a razao social e nome de pessoa;
  - estabelecimento que nao esta ativo, porque nao e prospect;
  - e-mail, telefone, logradouro, numero e complemento: nao servem a
    priorizacao, e em empresa pequena costumam ser da pessoa, nao da firma;
  - socios, que nem e lido.
"""
from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path
from typing import Iterator

from receita_base import layout


def linhas(caminho_zip: str | Path) -> Iterator[list[str]]:
    """Cada linha de cada arquivo de dentro do zip, ja separada em campos."""
    with zipfile.ZipFile(caminho_zip) as z:
        for info in z.infolist():
            with z.open(info) as bruto:
                texto = io.TextIOWrapper(bruto, encoding="latin-1", newline="")
                yield from csv.reader(texto, delimiter=";", quotechar='"')


def _data(aaaammdd: str) -> str | None:
    """'20051103' vira '2005-11-03'. Data zerada ou torta vira None."""
    if len(aaaammdd) != 8 or not aaaammdd.isdigit() or aaaammdd.startswith("0000"):
        return None
    return f"{aaaammdd[:4]}-{aaaammdd[4:6]}-{aaaammdd[6:]}"


def _numero(texto: str) -> float | None:
    """Capital social vem como '120000000000,00'."""
    try:
        return float(texto.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def empresa(campos: list[str]) -> dict | None:
    """Linha de Empresas vira documento, ou None se fica de fora."""
    if len(campos) < len(layout.EMPRESAS):
        return None
    r = dict(zip(layout.EMPRESAS, campos))
    if r["natureza_juridica"] == layout.EMPRESARIO_INDIVIDUAL:
        return None
    return {
        "cnpj_basico": r["cnpj_basico"],
        "razao_social": " ".join(r["razao_social"].split()),
        "natureza_juridica": r["natureza_juridica"],
        "porte": r["porte"] or "00",
        "capital_social": _numero(r["capital_social"]),
    }


def estabelecimento(campos: list[str], municipios: dict[str, str] | None = None) -> dict | None:
    """Linha de Estabelecimentos vira documento, ou None se fica de fora.

    Nao sabe se a raiz e de empresario individual: essa informacao esta em
    Empresas. Quem chama filtra pela raiz.
    """
    if len(campos) < len(layout.ESTABELECIMENTOS):
        return None
    r = dict(zip(layout.ESTABELECIMENTOS, campos))
    if r["situacao_cadastral"] != layout.SITUACAO_ATIVA:
        return None
    secundarios = [c for c in r["cnae_fiscal_secundaria"].split(",") if c]
    municipios = municipios or {}
    return {
        "cnpj": r["cnpj_basico"] + r["cnpj_ordem"] + r["cnpj_dv"],
        "cnpj_basico": r["cnpj_basico"],
        "matriz": r["identificador_matriz_filial"] == "1",
        "nome_fantasia": " ".join(r["nome_fantasia"].split()) or None,
        "data_inicio_atividade": _data(r["data_inicio_atividade"]),
        "cnae_principal": r["cnae_fiscal_principal"],
        "cnaes_secundarios": secundarios,
        "uf": r["uf"] or None,
        "municipio_codigo": r["municipio"],
        "municipio": municipios.get(r["municipio"]),
        "cep": r["cep"] or None,
    }


def tabela_codigos(caminho_zip: str | Path) -> dict[str, str]:
    """Municipios, CNAEs, naturezas: arquivos de duas colunas, codigo e nome."""
    return {c[0]: c[1] for c in linhas(caminho_zip) if len(c) >= 2}
