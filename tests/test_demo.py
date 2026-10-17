# -*- coding: utf-8 -*-
"""Demo ao vivo: uma empresa passa pelo processo inteiro, com plano B gravado."""
import pytest

import demo
from tests.test_dossie import HOJE, _associada, _campo, _rec, _site


def _lista():
    a = _associada()
    b = _associada()
    b["codigo"], b["campos"] = "8", {**b["campos"], "razao_social": "SERDIA ELETRONICA INDUSTRIAL S.A.",
                                       "dominio": "serdia.com.br"}
    return [a, b]


CAS = [{"codigo": "7", "cnpj": "12345678000190", "status": "confiavel"},
       {"codigo": "8", "cnpj": "87654321000110", "status": "confiavel"}]


def test_acha_por_nome_sem_acento_e_por_cnpj():
    assert demo.achar("serdia eletronica", _lista(), CAS)["codigo"] == "8"
    assert demo.achar("87.654.321/0001-10", _lista(), CAS)["codigo"] == "8"


def test_nome_ambiguo_lista_as_opcoes():
    with pytest.raises(demo.Ambiguo) as e:
        demo.achar("ind", _lista(), CAS)
    assert "EXEMPLO IND LTDA" in str(e.value)


def test_nome_desconhecido_avisa():
    with pytest.raises(LookupError):
        demo.achar("empresa que nao existe", _lista(), CAS)


def _rodar(ler_site, gravados=None):
    passos = []
    d = demo.executar("serdia", associadas=_lista(), casamento=CAS, hoje=HOJE,
                      consultar=lambda raiz, hoje: _rec(), ler_site=ler_site,
                      gravados=gravados or {}, taxas={"Indústria": 0.5}, cnaes={},
                      mostrar=lambda titulo, linhas: passos.append(titulo))
    return d, passos


def test_ao_vivo_passa_pelos_cinco_passos():
    site = {**_site(colaboradores=_campo(230, "parque com 230 colaboradores", "brasil")), "codigo": "8"}
    d, passos = _rodar(lambda associada: site)
    assert len(passos) == 5
    assert d["origem_site"] == "ao vivo"
    assert any(c == "porte" for _, c, *_ in d["resultado"].linhas)


def test_site_fora_do_ar_cai_no_gravado_e_diz_isso():
    gravado = {**_site(rh_estruturado=_campo(True, "Gerente de RH")), "codigo": "8"}

    def fora(associada):
        raise TimeoutError("site nao respondeu")

    d, _ = _rodar(fora, gravados={"8": gravado})
    assert d["origem_site"].startswith("gravado")
    assert any(c == "rh" for _, c, *_ in d["resultado"].linhas)


def test_sem_site_e_sem_gravado_segue_so_com_a_receita():
    def fora(associada):
        raise TimeoutError("site nao respondeu")

    d, passos = _rodar(fora)
    assert d["origem_site"] == "nao lido"
    assert len(passos) == 5 and d["resultado"].score > 0


def test_empresa_informada_na_tela_nao_fala_da_lista():
    a = {"codigo": "NOVA-11222333", "fonte_lista": "informada na tela",
         "campos": {"razao_social": "NOVA IND LTDA", "dominio": None, "contato_cargo": None}}
    cas = {"codigo": "NOVA-11222333", "cnpj": "11222333000181", "status": "informado"}
    passos = []
    demo.executar("11222333000181", [a], [cas], HOJE, consultar=lambda r, h: _rec(),
                  ler_site=lambda x: {"erro": "sem site"}, taxas={}, cnaes={},
                  mostrar=lambda t, l: passos.append((t, l)))
    titulo, linhas = passos[0]
    assert "informada na tela" in titulo and not any("lista de origem" in l or "(/)" in l for l in linhas)
