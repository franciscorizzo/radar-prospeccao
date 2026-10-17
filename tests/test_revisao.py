# -*- coding: utf-8 -*-
"""Revisao humana volta para o dossie: o que foi recusado sai do score."""
from datetime import date

import pytest

import dossie
import revisao
from score import ICP_PADRAO, Evidencia
from tests.test_dossie import HOJE, _associada, _campo, _rec, _site


def test_registrar_e_carregar_fica_com_o_ultimo_veredito(tmp_path):
    arq = tmp_path / "rev.jsonl"
    revisao.registrar("7", "rh", "errada", "vaga de terceiro", arquivo=arq, hoje=date(2026, 10, 1))
    revisao.registrar("7", "rh", "confirmada", arquivo=arq, hoje=date(2026, 10, 2))
    assert revisao.carregar(arq)[("7", "rh")]["veredito"] == "confirmada"


def test_criterio_ou_veredito_invalido_e_recusado(tmp_path):
    with pytest.raises(ValueError):
        revisao.registrar("7", "colaboradores", "errada", arquivo=tmp_path / "r.jsonl")
    with pytest.raises(ValueError):
        revisao.registrar("7", "rh", "talvez", arquivo=tmp_path / "r.jsonl")


def test_revisao_nao_guarda_quem_revisou(tmp_path):
    r = revisao.registrar("7", "rh", "confirmada", arquivo=tmp_path / "r.jsonl")
    assert set(r) == {"codigo", "criterio", "veredito", "motivo", "data"}


def test_evidencia_errada_sai_do_score_com_alerta_e_confirmada_fica_marcada():
    ev = {"rh": Evidencia(True, "site"), "multi_regiao": Evidencia(True, "receita")}
    revs = {("7", "rh"): {"veredito": "errada", "motivo": "vaga de terceiro", "data": "2026-10-03"},
            ("7", "multi_regiao"): {"veredito": "confirmada", "motivo": "", "data": "2026-10-03"}}
    saida, alertas = revisao.aplicar("7", ev, revs)
    assert "rh" not in saida and "vaga de terceiro" in alertas[0]
    assert saida["multi_regiao"].tipo.startswith("observado, revisado por pessoa")


def test_dossie_aplica_a_revisao(tmp_path):
    site = _site(rh_estruturado=_campo(True, "Gerente de RH"))
    base = dict(icp=ICP_PADRAO, hoje=HOJE, consultar=lambda r, h: _rec(), associadas=[_associada()],
                casamento=[{"codigo": "7", "cnpj": "12345678000190", "status": "confiavel"}],
                extracao=[site], taxas={}, cnaes={})
    antes = dossie.montar(**base)[0]["resultado"]
    revs = {("7", "rh"): {"veredito": "errada", "motivo": "", "data": "2026-10-03"}}
    depois = dossie.montar(**base, revisoes=revs)[0]["resultado"]
    assert depois.score == antes.score - 14
    assert "rh" in depois.sem_evidencia
    assert any("recusada na revisao" in a for a in depois.alertas)


def test_resumo_da_precisao_por_criterio():
    revs = {("1", "rh"): {"veredito": "confirmada"}, ("2", "rh"): {"veredito": "errada"},
            ("3", "rh"): {"veredito": "confirmada"}}
    assert revisao.resumo(revs)["rh"]["precisao"] == pytest.approx(2 / 3)
