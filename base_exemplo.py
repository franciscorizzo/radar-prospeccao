# -*- coding: utf-8 -*-
"""Leitura das abas da base de exemplo (ficticia). So leitura: nada aqui decide nada.

A base fica em dados-exemplo/base-exemplo.xlsx, gerada por dados-exemplo/gerar.py.
Para usar outra base no mesmo formato, aponte RADAR_BASE para o arquivo.

As abas tem linhas de enfeite antes do cabecalho. Por isso a procura pelo
cabecalho, em vez de pular linha fixa.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import openpyxl

AQUI = Path(__file__).resolve().parent


def caminho_da_base() -> Path:
    arq = Path(os.environ.get("RADAR_BASE") or AQUI / "dados-exemplo" / "base-exemplo.xlsx")
    if not arq.exists():
        raise FileNotFoundError(f"Base nao encontrada em {arq}: rode python dados-exemplo/gerar.py")
    return arq


@lru_cache(maxsize=None)
def aba(nome: str) -> tuple[tuple[str, ...], tuple[tuple, ...]]:
    """Devolve (cabecalho, linhas) da aba, sem as linhas de enfeite."""
    wb = openpyxl.load_workbook(caminho_da_base(), data_only=True)
    linhas = [r for r in wb[nome].iter_rows(values_only=True)]
    # Cabecalho: primeira linha com tres ou mais celulas preenchidas.
    i = next(k for k, r in enumerate(linhas) if r and sum(c is not None for c in r) >= 3)
    cabecalho = tuple(c for c in linhas[i] if c)
    corpo = tuple(r for r in linhas[i + 1:] if r and r[0])
    return cabecalho, corpo


def prospects() -> list[dict]:
    cabecalho, corpo = aba("Prospects")
    return [dict(zip(cabecalho, linha)) for linha in corpo]


def tabela(nome: str) -> list[dict]:
    cabecalho, corpo = aba(nome)
    return [dict(zip(cabecalho, linha)) for linha in corpo]
