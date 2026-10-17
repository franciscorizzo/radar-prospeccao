# -*- coding: utf-8 -*-
"""A normalizacao do cadastro de CNPJ, contra a resposta real guardada em fixture.

Sem rede: o fixture e a resposta que a API devolveu em 30/09/2026, com o QSA
removido antes de tocar no disco.
"""
import json
from pathlib import Path

import pytest

from fontes import receita

FIXTURE = Path(__file__).parent / "fixtures" / "brasilapi-47960950000121.json"
URL = "https://brasilapi.com.br/api/cnpj/v1/47960950000121"


@pytest.fixture
def bruto():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def cadastro(bruto):
    return receita.normalizar(bruto, URL)


def test_identifica_a_empresa(cadastro):
    assert cadastro["campos"]["razao_social"] == "MAGAZINE LUIZA S/A"
    assert cadastro["campos"]["nome_fantasia"] == "MAGAZINE LUIZA"


def test_traz_o_cnae_principal_com_descricao(cadastro):
    assert cadastro["campos"]["cnae_principal"] == "4713004"
    assert "Lojas de departamentos" in cadastro["campos"]["cnae_principal_descricao"]
    assert cadastro["campos"]["cnaes_secundarios"] == 35


def test_traz_localizacao_e_natureza(cadastro):
    assert cadastro["campos"]["municipio"] == "FRANCA"
    assert cadastro["campos"]["uf"] == "SP"
    assert cadastro["campos"]["natureza_juridica"] == "Sociedade Anônima Aberta"


def test_situacao_cadastral_vira_booleano_util(cadastro):
    assert cadastro["campos"]["situacao_cadastral"] == "ATIVA"
    assert cadastro["campos"]["ativa"] is True


def test_porte_da_receita_nao_e_numero_de_colaboradores(cadastro):
    """Porte aqui e faixa de receita (ME, EPP, DEMAIS), nao headcount.

    O ICP do cliente pede 200 a 5.000 colaboradores. Confundir os dois faria a
    ferramenta responder outra pergunta, entao o campo sai com nome proprio e
    colaboradores entra como lacuna.
    """
    assert cadastro["campos"]["porte_receita"] == "DEMAIS"
    assert "colaboradores" not in cadastro["campos"]
    assert "colaboradores" in cadastro["lacunas"]


def test_o_que_esta_fonte_nao_responde_vira_lacuna_declarada(cadastro):
    assert set(cadastro["lacunas"]) == {"colaboradores", "multi_regiao", "dominio"}


def test_todo_campo_preenchido_tem_proveniencia(cadastro):
    assert set(cadastro["campos"]) == set(cadastro["proveniencia"])
    for campo, p in cadastro["proveniencia"].items():
        assert p["url"] == URL, campo
        assert p["tipo"] == "observado", campo
        assert p["fonte"].startswith("Receita Federal"), campo


def test_quadro_de_socios_nunca_sai_da_normalizacao(bruto):
    """O QSA e onde dado de PJ vira dado de pessoa natural. Fica fora, mesmo
    que a fonte passe a devolve-lo de novo."""
    bruto["qsa"] = [{"nome_socio": "FULANO DE TAL", "cnpj_cpf_do_socio": "***123***"}]
    saida = json.dumps(receita.normalizar(bruto, URL), ensure_ascii=False)
    assert "FULANO" not in saida
    assert "socio" not in saida.lower()


def test_cnpj_invalido_e_recusado_antes_da_rede():
    with pytest.raises(ValueError):
        receita.limpar_cnpj("1234")


@pytest.mark.rede
def test_contra_o_dado_real(): 
    """Suite verde nao prova comportamento. Este roda contra a API de verdade.

        python -m pytest tests -m rede
    """
    saida = receita.buscar("47.960.950/0001-21")
    assert saida["campos"]["razao_social"] == "MAGAZINE LUIZA S/A"
    assert saida["campos"]["ativa"] is True
    assert "socio" not in json.dumps(saida, ensure_ascii=False).lower()
