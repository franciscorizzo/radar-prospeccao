# -*- coding: utf-8 -*-
"""Leitura dos arquivos abertos do CNPJ.

A amostra de Empresas tem 30 linhas reais da competencia 2026-09, nenhuma de
empresario individual. O caso de empresario individual e montado no teste, com
nome inventado, porque o ponto e justamente nao ter nome de pessoa no repo.
"""
from pathlib import Path

import pytest

from receita_base import layout, leitura

FX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def empresas_amostra():
    return [leitura.empresa(c) for c in leitura.linhas(FX / "receita-empresas-amostra.zip")]


def test_le_a_amostra_inteira_em_fluxo(empresas_amostra):
    assert len(empresas_amostra) == 30
    assert all(e is not None for e in empresas_amostra)


def test_banco_do_brasil_e_a_primeira_raiz(empresas_amostra):
    bb = empresas_amostra[0]
    assert bb["cnpj_basico"] == "00000000"
    assert bb["razao_social"] == "BANCO DO BRASIL SA"
    assert bb["porte"] == "05"
    assert bb["capital_social"] == 120_000_000_000.0


def test_empresario_individual_fica_de_fora():
    linha = ["12345678", "FULANO DE TAL 12345678901", layout.EMPRESARIO_INDIVIDUAL,
             "50", "1000,00", "01", ""]
    assert leitura.empresa(linha) is None


def test_linha_curta_nao_derruba_a_leitura():
    assert leitura.empresa(["123"]) is None
    assert leitura.estabelecimento(["123"]) is None


def _linha_estab(**troca):
    base = dict.fromkeys(layout.ESTABELECIMENTOS, "")
    base.update(cnpj_basico="47960950", cnpj_ordem="0001", cnpj_dv="21",
                identificador_matriz_filial="1", nome_fantasia="MAGAZINE  LUIZA",
                situacao_cadastral="02", data_inicio_atividade="19661024",
                cnae_fiscal_principal="4713004", cnae_fiscal_secundaria="4751201,4752100",
                uf="SP", municipio="6425", cep="14400490",
                email="alguem@exemplo.com", telefone1="37112002",
                logradouro="VOLUNTARIOS DA FRANCA", numero="1465")
    base.update(troca)
    return [base[c] for c in layout.ESTABELECIMENTOS]


def test_estabelecimento_ativo_vira_documento():
    e = leitura.estabelecimento(_linha_estab(), {"6425": "FRANCA"})
    assert e["cnpj"] == "47960950000121"
    assert e["matriz"] is True
    assert e["nome_fantasia"] == "MAGAZINE LUIZA"
    assert e["data_inicio_atividade"] == "1966-10-24"
    assert e["cnaes_secundarios"] == ["4751201", "4752100"]
    assert e["municipio"] == "FRANCA"


def test_estabelecimento_inativo_fica_de_fora():
    assert leitura.estabelecimento(_linha_estab(situacao_cadastral="08")) is None


def test_contato_e_endereco_fino_nunca_entram():
    e = leitura.estabelecimento(_linha_estab())
    texto = repr(e)
    for proibido in ("alguem@exemplo.com", "37112002", "VOLUNTARIOS", "1465"):
        assert proibido not in texto


def test_data_zerada_vira_nada():
    assert leitura._data("00000000") is None
    assert leitura._data("2005") is None
