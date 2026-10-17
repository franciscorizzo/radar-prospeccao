# -*- coding: utf-8 -*-
"""Cobertura do ICP somando Receita e site: a metrica M1 da Semana 2."""
from datetime import date

import cobertura as cob


def test_pesos_somam_100_e_o_teto_e_84():
    assert sum(cob.PESOS.values()) == 100
    assert cob.TETO == 84


def test_receita_sozinha_cobre_regiao_e_distribuicao():
    rec = {"estabelecimentos": 1, "ufs": ["SP"], "uf_matriz": "SP", "abertos_24m": 0}
    c = cob.criterios(rec, None)
    assert c["regiao"] == "receita" and c["distribuicao"] == "receita"
    assert c["crescimento"] is None          # ausencia de filial nova nao prova que nao cresce
    assert cob.pontos(c) == 18


def test_filial_recente_cobre_crescimento():
    rec = {"estabelecimentos": 5, "ufs": ["SP", "MG"], "uf_matriz": "SP", "abertos_24m": 2}
    assert cob.criterios(rec, None)["crescimento"] == "receita"


def test_colaboradores_do_grupo_nao_cobrem_o_porte_do_cnpj():
    site = {"campos": {"colaboradores": {"valor": 9000, "escopo": "grupo"}}}
    assert cob.criterios(None, site)["porte"] is None
    site["campos"]["colaboradores"]["escopo"] = "brasil"
    assert cob.criterios(None, site)["porte"] == "site"


def test_site_e_receita_somam():
    rec = {"estabelecimentos": 3, "ufs": ["RS", "SP"], "uf_matriz": "RS", "abertos_24m": 0}
    site = {"campos": {"rh_estruturado": {}, "beneficios": {}, "sinal_crescimento": {}}}
    c = cob.criterios(rec, site)
    assert c["crescimento"] == "site"
    assert cob.pontos(c) == 8 + 10 + 14 + 12 + 10


def test_consulta_da_receita_conta_so_filial_recente():
    enviado = {}
    def requisicao(metodo, caminho, corpo):
        enviado.update(corpo)
        return {"hits": {"total": {"value": 4}}, "aggregations": {
            "ufs": {"buckets": [{"key": "SP"}, {"key": "MG"}, {"key": "EX"}]},
            "matriz": {"uf": {"buckets": [{"key": "SP"}]}},
            "recentes": {"doc_count": 1}}}
    r = cob.receita("12345678", requisicao=requisicao, hoje=date(2026, 10, 1))
    assert r == {"estabelecimentos": 4, "ufs": ["SP", "MG"], "uf_matriz": "SP", "abertos_24m": 1}
    filtros = enviado["aggs"]["recentes"]["filter"]["bool"]["filter"]
    assert {"term": {"matriz": False}} in filtros
    assert filtros[1]["range"]["data_inicio_atividade"]["gte"] == "2024-10-01"
