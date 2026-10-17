# -*- coding: utf-8 -*-
"""Cadastro de CNPJ da Receita Federal: a primeira fonte da camada de coleta.

Entra um CNPJ, sai o que o registro publico responde do ICP, com a URL de onde
saiu presa a cada campo. O que esta fonte NAO responde sai como lacuna
declarada, em vez de campo vazio -- a diferenca importa, porque campo vazio
alguem preenche no chute e lacuna declarada alguem vai buscar.

Duas regras que este modulo faz cumprir, e que vem do desenho da Semana 2:

  - **O quadro de socios nunca atravessa.** E onde dado de pessoa juridica vira
    dado de pessoa natural, e reusa-lo para prospeccao mudaria a finalidade que
    motivou a publicacao. O filtro esta na normalizacao, nao na coleta, para
    valer mesmo que a fonte mude de formato.
  - **`porte` da Receita nao e numero de colaboradores.** Aqui e faixa de
    receita (ME, EPP, DEMAIS). O ICP do cliente pede 200 a 5.000 pessoas. Sai com
    nome proprio, `porte_receita`, e colaboradores fica como lacuna.
"""
from __future__ import annotations

import json
import re
import urllib.request

FONTE = "Receita Federal (dados abertos, via BrasilAPI)"
BASE = "https://brasilapi.com.br/api/cnpj/v1/"
AGENTE = ("ITA-Challenge-Sprint-2026/0.1 "
          "(prototipo academico; codigo aberto)")

# O que o cadastro nao responde. Nomeadas aqui para nao se perderem no caminho.
LACUNAS = ("colaboradores", "multi_regiao", "dominio")

_PROIBIDO = re.compile(r"qsa|socio", re.IGNORECASE)


def limpar_cnpj(cnpj: str) -> str:
    """So digitos, e 14 deles. Recusa antes de gastar rede."""
    so_digitos = re.sub(r"\D", "", cnpj or "")
    if len(so_digitos) != 14:
        raise ValueError(f"CNPJ precisa de 14 digitos, recebi {len(so_digitos)}: {cnpj!r}")
    return so_digitos


def normalizar(bruto: dict, url: str) -> dict:
    """Resposta da API vira campos do ICP, com proveniencia e lacunas."""
    bruto = {k: v for k, v in bruto.items() if not _PROIBIDO.search(k)}

    campos = {
        "razao_social": bruto.get("razao_social"),
        "nome_fantasia": bruto.get("nome_fantasia"),
        "cnae_principal": str(bruto.get("cnae_fiscal") or ""),
        "cnae_principal_descricao": bruto.get("cnae_fiscal_descricao"),
        "cnaes_secundarios": len(bruto.get("cnaes_secundarios") or []),
        "municipio": bruto.get("municipio"),
        "uf": bruto.get("uf"),
        "natureza_juridica": bruto.get("natureza_juridica"),
        "porte_receita": bruto.get("porte"),
        "capital_social": bruto.get("capital_social"),
        "situacao_cadastral": bruto.get("descricao_situacao_cadastral"),
        "ativa": bruto.get("descricao_situacao_cadastral") == "ATIVA",
        "data_inicio_atividade": bruto.get("data_inicio_atividade"),
        "matriz_ou_filial": bruto.get("descricao_identificador_matriz_filial"),
    }
    campos = {k: v for k, v in campos.items() if v not in (None, "")}

    proveniencia = {
        campo: {"fonte": FONTE, "url": url, "tipo": "observado"}
        for campo in campos
    }
    return {"campos": campos, "proveniencia": proveniencia, "lacunas": list(LACUNAS)}


def _obter(url: str, tempo: int = 25) -> dict:
    req = urllib.request.Request(
        url, headers={"User-Agent": AGENTE, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=tempo) as r:
        return json.load(r)


def buscar(cnpj: str, obter=_obter) -> dict:
    """Consulta o cadastro e devolve o registro normalizado.

    `obter` e injetavel para o teste nao tocar a rede.
    """
    url = BASE + limpar_cnpj(cnpj)
    return normalizar(obter(url), url)
