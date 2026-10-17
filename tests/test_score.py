# -*- coding: utf-8 -*-
"""Score, retroalimentacao e a suite de aceite do cliente.

Os testes de regra usam evidencia montada a mao; os da suite rodam contra a
planilha real do cliente (Casos_Validacao), que e o criterio de aceite.
"""
import math

import pytest

import calibracao
from score import CONFIANCA_MINIMA, PESOS, Evidencia, justificativa, pontuar


def _ev(**campos):
    return {k: Evidencia(v, "teste") for k, v in campos.items()}


COMPLETA = dict(porte=1200, rh=True, multi_regiao=True, crescimento="Alto",
                employer_branding="Alto", dor_retencao="Alto", renovacao="0-3 meses",
                sinal_recente={"forca": "Alto", "dias": 0}, decisor="cargo", segmento="Varejo")


# --- regra ---------------------------------------------------------------------

def test_tudo_favoravel_soma_cem_com_confianca_total():
    r = pontuar("X", _ev(**COMPLETA), taxas_segmento={"Varejo": 0.6})
    assert r.score == 100 and r.confianca == 1.0 and r.prioridade == "Prioridade A"


def test_criterio_sem_evidencia_nao_pontua_nem_e_imputado():
    campos = dict(COMPLETA)
    del campos["porte"], campos["rh"]
    r = pontuar("X", _ev(**campos), taxas_segmento={"Varejo": 0.6})
    assert r.score == 100 - PESOS["porte"] - PESOS["rh"]
    assert r.confianca == 0.66
    assert set(r.sem_evidencia) == {"porte", "rh"}


def test_valor_none_conta_como_sem_evidencia():
    r = pontuar("X", {"crescimento": Evidencia(None, "teste")})
    assert "crescimento" in r.sem_evidencia


@pytest.mark.parametrize("n,pontos", [(200, 20), (5000, 20), (5001, 14), (150, 8)])
def test_faixas_de_porte(n, pontos):
    r = pontuar("X", _ev(porte=n))
    assert r.linhas[0][0] == pontos


def test_sinal_perde_peso_com_a_idade():
    novo = pontuar("X", _ev(sinal_recente={"forca": "Alto", "dias": 0})).score
    velho = pontuar("X", _ev(sinal_recente={"forca": "Alto", "dias": 300})).score
    vencido = pontuar("X", _ev(sinal_recente={"forca": "Alto", "dias": 400})).score
    assert novo == 10 and 0 < velho < novo and vencido == 0


def test_canal_sem_decisor_vale_menos_que_cargo():
    assert pontuar("X", _ev(decisor="canal")).score < pontuar("X", _ev(decisor="cargo")).score


def test_segmento_pontua_pela_taxa_relativa():
    taxas = {"A": 0.6, "B": 0.3}
    assert pontuar("X", _ev(segmento="A"), taxas).score == 5
    assert pontuar("X", _ev(segmento="B"), taxas).score == 2.5
    assert pontuar("X", _ev(segmento="C"), taxas).score == 0


# --- desqualificadores e alertas -------------------------------------------------

def test_menos_de_80_colaboradores_desqualifica_mesmo_com_score_alto():
    r = pontuar("X", _ev(**{**COMPLETA, "porte": 50}), {"Varejo": 0.6})
    assert r.prioridade == "Desqualificada" and r.desqualificada.startswith("D01")


def test_inativa_desqualifica():
    r = pontuar("X", _ev(**COMPLETA), {"Varejo": 0.6}, ativa=False)
    assert r.desqualificada.startswith("D04")


def test_bom_fit_com_renovacao_distante_alerta_timing():
    r = pontuar("X", _ev(**{**COMPLETA, "renovacao": ">12 meses"}), {"Varejo": 0.6})
    assert any("timing fraco" in a for a in r.alertas)


def test_pouca_evidencia_alerta_baixa_confianca():
    r = pontuar("X", _ev(porte=1200, rh=True))
    assert r.confianca < CONFIANCA_MINIMA
    assert any("Baixa confianca" in a for a in r.alertas)


def test_uma_fonte_publica_so_alerta_evidencia_escassa():
    """CV-15: campos cheios nao bastam; se tudo vem de uma fonte, sinalizar."""
    r = pontuar("X", _ev(**COMPLETA), {"Varejo": 0.6}, fontes_publicas=1)
    assert r.confianca == 1.0
    assert any("escassa" in a for a in r.alertas)
    assert not any("escassa" in a for a in
                   pontuar("X", _ev(**COMPLETA), {"Varejo": 0.6}, fontes_publicas=3).alertas)


def test_justificativa_cita_fonte_de_cada_ponto():
    ev = _ev(**COMPLETA)
    ev["sinal_recente"] = Evidencia({"forca": "Alto", "dias": 10}, "noticia", url="https://x.com.br/n")
    texto = justificativa(pontuar("Empresa X", ev, {"Varejo": 0.6}))
    assert "Empresa X: Prioridade A" in texto
    assert "<https://x.com.br/n>" in texto
    assert texto.count("[observado: teste]") == 9


# --- retroalimentacao ------------------------------------------------------------

def _op(id_, resultado):
    return {"ID Empresa": id_, "Resultado": resultado}


def test_taxa_por_segmento_suavizada_e_ignora_em_negociacao():
    ops = [_op("a", "Ganha"), _op("b", "Perdida"), _op("c", "Em negociação"), _op("d", "Ganha")]
    taxas = calibracao.taxas_por_segmento(ops, {"a": "S", "b": "S", "c": "S", "d": "T"})
    assert taxas["S"] == pytest.approx(2 / 4)     # (1+1)/(2+2)
    assert taxas["T"] == pytest.approx(2 / 3)     # (1+1)/(1+2): um ganho nao vira 100%


def test_auc():
    assert calibracao.auc([3, 4], [1, 2]) == 1.0
    assert calibracao.auc([1], [1]) == 0.5
    assert math.isnan(calibracao.auc([], [1]))


def test_lift_por_criterio():
    ops = [_op("a", "Ganha"), _op("b", "Perdida"), _op("c", "Perdida")]
    lift = calibracao.lift_por_criterio(ops, {"rh": {"a": True, "b": False, "c": False}})
    assert lift["rh"]["com"] == 1.0 and lift["rh"]["sem"] == 0.0


# --- o ICP e entrada ---------------------------------------------------------------

def test_outro_icp_muda_a_faixa_de_porte_e_os_pesos():
    from score import Icp
    pesos = dict(PESOS, porte=30, segmento=0, sinal_recente=5)
    icp = Icp("industria grande", pesos, porte=(1000, 50000), porte_minimo=500)
    r = pontuar("X", _ev(porte=800), icp=icp)
    assert r.linhas[0][0] == 12 and r.desqualificada is None
    assert pontuar("X", _ev(porte=400), icp=icp).desqualificada.startswith("D01: menos de 500")
    assert pontuar("X", _ev(porte=2000), icp=icp).score == 30


def test_icp_com_pesos_que_nao_somam_cem_e_recusado():
    from score import Icp
    with pytest.raises(ValueError):
        Icp("x", dict(PESOS, porte=50))


# --- faixa indecidida -----------------------------------------------------------------

def _faixa_de(score):
    from score import FAIXAS
    return next(nome for corte, nome in FAIXAS if score >= corte)


def test_pouca_evidencia_e_faixa_aberta_vira_inconclusiva_e_nao_baixa():
    """Ausencia de evidencia nao e sinal negativo: 30 pontos com 40% avaliado
    pode ser A. O score fica, a faixa nao e inventada."""
    r = pontuar("X", _ev(rh=True, multi_regiao=True, decisor="cargo", segmento="Varejo"), {"Varejo": 0.6})
    assert r.score == 34 and r.confianca < CONFIANCA_MINIMA
    assert r.teto == 34 + 20 + 10 + 10 + 8 + 8 + 10
    assert r.prioridade == "Inconclusiva"
    assert "pode chegar a 100" in justificativa(r)


def test_pouca_evidencia_mas_faixa_ja_decidida_mantem_a_faixa():
    from score import Icp
    pesos = dict(PESOS, porte=60, rh=10, multi_regiao=5, crescimento=5, employer_branding=5,
                 dor_retencao=5, renovacao=3, sinal_recente=3, decisor=2, segmento=2)
    r = pontuar("X", _ev(porte=1000), icp=Icp("x", pesos))
    assert r.score == 60 and r.confianca == 0.6 and r.prioridade == "Prioridade B"
    r = pontuar("X", _ev(porte=1000, rh=True, multi_regiao=True), icp=Icp("x", pesos))
    assert r.score == 75 and r.prioridade == "Prioridade A"


def test_desqualificada_continua_desqualificada_com_pouca_evidencia():
    assert pontuar("X", _ev(porte=50)).prioridade == "Desqualificada"
