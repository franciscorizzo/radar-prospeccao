# -*- coding: utf-8 -*-
"""Cobertura do ICP por empresa, somando a base da Receita e o site.

E a metrica M1 da Semana 2: quantos dos 100 pontos de peso do ICP do cliente tem
evidencia observada, partindo so do nome publicado por uma fonte de lista.

Cada criterio do ICP (aba ICP_Criterios) tem uma ou mais fontes possiveis:

| Criterio                  | Peso | De onde vem                                   |
|---------------------------|------|-----------------------------------------------|
| Porte (colaboradores)     | 20   | site, se o numero for da operacao no Brasil   |
| Regiao                    |  8   | Receita: UF da matriz                         |
| Estrutura de RH           | 14   | site                                          |
| Beneficios                | 12   | site                                          |
| Crescimento               | 10   | Receita: estabelecimento aberto nos ultimos 24 meses; ou site |
| Employer branding         | 10   | site                                          |
| Distribuicao geografica   | 10   | Receita: estabelecimentos ativos em 2+ UFs    |
| Dor de retencao           |  8   | site (raro)                                   |
| Momento de compra         |  8   | nenhuma fonte publica                         |

"Coberto" quer dizer que existe evidencia para responder o criterio, nao que a
resposta e favoravel: uma empresa com matriz so no Acre tem o criterio de regiao
coberto, e desfavoravel.
"""
from __future__ import annotations

from datetime import date

PESOS = {
    "porte": 20, "regiao": 8, "rh": 14, "beneficios": 12, "crescimento": 10,
    "employer_branding": 10, "distribuicao": 10, "dor_retencao": 8, "momento_compra": 8,
}
assert sum(PESOS.values()) == 100
TETO = 100 - PESOS["momento_compra"] - PESOS["dor_retencao"]   # 84, o declarado na Semana 2


def receita(cnpj_basico: str, requisicao=None, hoje: date | None = None) -> dict:
    """O que a base propria responde sobre a raiz: UFs ativas, matriz, filial recente."""
    if requisicao is None:
        from receita_base.indice import requisicao
    hoje = hoje or date.today()
    corte = date(hoje.year - 2, hoje.month, min(hoje.day, 28)).isoformat()
    r = requisicao("POST", "/cnpj-estabelecimentos/_search", {
        "size": 0,
        "query": {"term": {"cnpj_basico": cnpj_basico}},
        "aggs": {
            "ufs": {"terms": {"field": "uf", "size": 40}},
            "matriz": {"filter": {"term": {"matriz": True}},
                       "aggs": {"uf": {"terms": {"field": "uf", "size": 1}}}},
            # So filial: matriz aberta ha pouco e empresa nova, nao expansao.
            "recentes": {"filter": {"bool": {"filter": [
                {"term": {"matriz": False}},
                {"range": {"data_inicio_atividade": {"gte": corte}}}]}}},
        },
    })
    a = r["aggregations"]
    ufs = [b["key"] for b in a["ufs"]["buckets"] if b["key"] != "EX"]
    matriz_uf = next((b["key"] for b in a["matriz"]["uf"]["buckets"]), None)
    return {"estabelecimentos": r["hits"]["total"]["value"], "ufs": ufs,
            "uf_matriz": matriz_uf, "abertos_24m": a["recentes"]["doc_count"]}


def criterios(rec: dict | None, site: dict | None) -> dict:
    """Para cada criterio, a fonte que o cobre, ou None."""
    campos = (site or {}).get("campos") or {}
    c = dict.fromkeys(PESOS)
    if rec:
        if rec.get("uf_matriz"):
            c["regiao"] = "receita"
        if rec.get("estabelecimentos"):
            # Uma UF so tambem responde o criterio: responde "nao distribuida".
            c["distribuicao"] = "receita"
        if rec.get("abertos_24m"):
            c["crescimento"] = "receita"
    col = campos.get("colaboradores")
    if col and col.get("escopo") in ("brasil", "indefinido"):
        c["porte"] = "site"
    for criterio, campo in (("rh", "rh_estruturado"), ("beneficios", "beneficios"),
                            ("employer_branding", "employer_branding"), ("dor_retencao", "dor_retencao")):
        if campo in campos:
            c[criterio] = "site"
    if c["crescimento"] is None and "sinal_crescimento" in campos:
        c["crescimento"] = "site"
    return c


def pontos(cobertos: dict) -> int:
    return sum(PESOS[k] for k, fonte in cobertos.items() if fonte)
