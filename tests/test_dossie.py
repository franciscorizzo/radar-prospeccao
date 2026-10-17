# -*- coding: utf-8 -*-
"""Dossie com dado real: o que cada fonte vira, e o que nao pode virar.

A Receita e trocada por um dicionario; o resto sao registros no formato que a
coleta grava. O teste com o indice e a base de verdade fica marcado `es`.
"""
from datetime import date

import pytest

import dossie
from score import ICP_PADRAO

HOJE = date(2026, 10, 3)
URL_LISTA = "https://lista.exemplo/empresa/7/"


def _associada(cargo="Diretor Comercial", dominio="exemplo.com.br"):
    prov = {"fonte": "lista de origem", "url": URL_LISTA, "tipo": "observado"}
    return {"codigo": "7", "campos": {"razao_social": "EXEMPLO IND LTDA", "contato_cargo": cargo,
                                      "dominio": dominio, "uf": "SP"},
            "proveniencia": {"razao_social": prov, "contato_cargo": prov}}


def _rec(**mudar):
    base = {"estabelecimentos": 3, "ufs": ["MG", "SP"], "uf_matriz": "SP", "cnae_principal": "2710401",
            "abertos_24m": 2, "filial_mais_recente": {"data_inicio_atividade": "2026-07-05",
                                                      "uf": "MG", "municipio": "EXTREMA"},
            "razao_social": "EXEMPLO INDUSTRIA LTDA", "porte_receita": "05"}
    return {**base, **mudar}


def _campo(valor, trecho, escopo=None, url="https://exemplo.com.br/sobre"):
    c = {"valor": valor, "url": url, "trecho": trecho, "tipo": "extraido",
         "fonte": "site da empresa, lido por Qwen3.5-9B-Q4_K_M", "ancora": {}}
    if escopo:
        c["escopo"] = escopo
    return c


def _site(**campos):
    return {"codigo": "7", "campos": campos, "erro": None,
            "paginas": [{"url": "https://exemplo.com.br/trabalhe-conosco", "resultado": "ok"}]}


def _ev(associada=None, rec=None, site=None):
    return dossie.evidencias(associada or _associada(), rec if rec is not None else _rec(), site, ICP_PADRAO, HOJE)


# --- segmento e cargo -----------------------------------------------------------------

@pytest.mark.parametrize("cnae,seg", [("2710401", "Indústria"), ("6201501", "Tecnologia"),
                                      ("6110801", "Telecom"), ("4651601", None), ("3511501", "Energia")])
def test_segmento_por_cnae(cnae, seg):
    assert dossie.segmento_por_cnae(cnae) == seg


@pytest.mark.parametrize("cargo,e", [("Gerente de Recursos Humanos", True), ("Dir Comercial Mkt e Pessoas", True),
                                     ("Ger de Beneficios Saude e Rt", True), ("Diretor Comercial", False),
                                     ("Gerente de P&d", False), (None, False)])
def test_cargo_de_decisor(cargo, e):
    assert dossie.cargo_de_decisor(cargo, ICP_PADRAO) is e


# --- o que cada fonte vira ------------------------------------------------------------

def test_receita_da_multi_regiao_crescimento_e_sinal_datado():
    ev, _, _, fontes = _ev()
    assert ev["multi_regiao"].valor is True and "MG, SP" in ev["multi_regiao"].detalhe
    assert ev["crescimento"].valor == "Alto"
    assert ev["sinal_recente"].valor == {"forca": "Médio", "dias": 90}
    assert ev["segmento"].valor == "Indústria" and ev["segmento"].tipo == "calibrado"
    assert fontes == {"receita"}


def test_uma_uf_so_e_evidencia_desfavoravel_e_nao_ausencia():
    ev, *_ = _ev(rec=_rec(ufs=["SP"], abertos_24m=0, filial_mais_recente=None))
    assert ev["multi_regiao"].valor is False
    assert "crescimento" not in ev and "sinal_recente" not in ev


def test_porte_so_pontua_com_numero_do_brasil():
    ev, _, alertas, _ = _ev(site=_site(colaboradores=_campo(9000, "9000+ Employees", "grupo")))
    assert "porte" not in ev and any("no grupo" in a for a in alertas)
    ev, *_ = _ev(site=_site(colaboradores=_campo(1200, "mais de 1.200 colaboradores", "brasil")))
    assert ev["porte"].valor == 1200 and ev["porte"].tipo == "extraido"


def test_porte_da_receita_vira_alerta_nao_numero():
    ev, _, alertas, _ = _ev(rec=_rec(porte_receita="03"))
    assert "porte" not in ev
    assert any("Empresa de Pequeno Porte" in a for a in alertas)


def test_site_reforca_crescimento_e_traz_employer_branding():
    site = _site(sinal_crescimento=_campo(True, "Estamos em plena expansao"),
                 employer_branding=_campo(True, "Certificada Great Place to Work 2025"))
    ev, _, _, fontes = _ev(rec=_rec(abertos_24m=1), site=site)
    assert ev["crescimento"].valor == "Alto" and "plena expansao" in ev["crescimento"].detalhe
    assert ev["employer_branding"].valor == "Alto"
    assert fontes == {"receita", "site"}


def test_contato_de_rh_vira_decisor_por_cargo_e_rh_estruturado():
    ev, canal, *_ = _ev(associada=_associada(cargo="Gerente de Recursos Humanos"))
    assert ev["decisor"].valor == "cargo" and ev["rh"].valor is True
    assert canal["cargo"] == "Gerente de Recursos Humanos"


def test_contato_fora_de_rh_e_canal_e_nao_decisor():
    ev, canal, *_ = _ev(site=_site())
    assert ev["decisor"].valor == "canal" and "rh" not in ev
    assert "site institucional: https://exemplo.com.br" in canal["descricao"]
    assert "pagina de carreiras: https://exemplo.com.br/trabalhe-conosco" in canal["descricao"]


# --- montagem -------------------------------------------------------------------------

def _montar(casamento_status="confiavel", extracao=None, rec=None):
    cas = [{"codigo": "7", "cnpj": "12345678000190", "status": casamento_status}]
    return dossie.montar(ICP_PADRAO, HOJE, consultar=lambda raiz, hoje: rec or _rec(),
                         associadas=[_associada()], casamento=cas, extracao=extracao or [],
                         taxas={"Indústria": 0.5}, cnaes={"2710401": "Fabricacao de geradores"})


def test_dossie_tem_os_seis_campos_do_briefing():
    d = dossie.como_dict(_montar()[0])
    for campo in ("empresa", "segmento", "score", "evidencias", "justificativa", "decisor_ou_canal"):
        assert d[campo], campo
    assert d["empresa"] == "EXEMPLO INDUSTRIA LTDA" and d["cnae"] == "2710401 Fabricacao de geradores"


def test_so_receita_alerta_evidencia_escassa_e_site_nao_lido():
    r = _montar()[0]["resultado"]
    assert any("escassa" in a for a in r.alertas)
    assert "Site ainda nao lido" in r.alertas


def test_casamento_provavel_alerta_e_nao_encontrado_sai():
    assert any("casamento provavel" in a for a in _montar("provavel")[0]["resultado"].alertas)
    assert _montar("ambiguo") == []


def test_sem_estabelecimento_ativo_desqualifica():
    r = _montar(rec=_rec(estabelecimentos=0, ufs=[], abertos_24m=0, filial_mais_recente=None))[0]["resultado"]
    assert r.desqualificada.startswith("D04")


def test_dossie_nao_carrega_nome_de_pessoa_nem_telefone():
    a = _associada()
    a["campos"]["telefone"] = "11 5555-0000"
    d = dossie.montar(ICP_PADRAO, HOJE, consultar=lambda r, h: _rec(), associadas=[a],
                      casamento=[{"codigo": "7", "cnpj": "12345678000190", "status": "confiavel"}],
                      extracao=[], taxas={}, cnaes={})
    texto = repr(dossie.como_dict(d[0])) + dossie.relatorio_html(d, ICP_PADRAO, HOJE)
    assert "5555" not in texto


def test_dossie_dos_dados_de_exemplo():
    """A lista de exemplo inteira vira dossie, sem indice da Receita: o CNPJ ficticio vem do arquivo."""
    ds = dossie.montar(ICP_PADRAO, HOJE)
    assert len(ds) == 24
    assert all(d["resultado"].canal for d in ds)
    assert all(ev.fonte for d in ds for *_, ev in d["resultado"].linhas)


def test_cobertura_m1_soma_receita_e_site():
    d = _montar(extracao=[_site(rh_estruturado=_campo(True, "Gerente de RH"))])[0]
    # receita: regiao 8 + distribuicao 10 + crescimento 10; site: rh 14
    assert d["cobertura_icp"] == 42 and d["site_lido"] is True
    m1 = dossie.resumo_m1([d])
    assert m1["media"] == 42 and m1["teto"] == 84


def test_toda_evidencia_tem_fonte():
    """M2: nenhum ponto sem origem."""
    site = _site(employer_branding=_campo(True, "GPTW"), sinal_crescimento=_campo(True, "expansao"))
    d = dossie.como_dict(_montar(extracao=[site])[0])
    assert d["evidencias"] and all(e["fonte"] for e in d["evidencias"])


def test_crescimento_datado_de_mais_de_dois_anos_nao_conta():
    """"2022 Expansao para Sao Paulo" e historia, nao sinal de agora."""
    site = _site(sinal_crescimento=_campo(True, "2022 Expansão para São Paulo"))
    ev, _, alertas, fontes = _ev(rec=_rec(abertos_24m=0, filial_mais_recente=None), site=site)
    assert "crescimento" not in ev and "site" not in fontes
    assert any("2022" in a for a in alertas)
    site = _site(sinal_crescimento=_campo(True, "Em 2025 abrimos a filial de Manaus"))
    ev, *_ = _ev(rec=_rec(abertos_24m=0, filial_mais_recente=None), site=site)
    assert ev["crescimento"].valor == "Médio"


def test_empresa_digitada_sem_lista_de_origem():
    """Empresa nova, fora da lista de origem: CNPJ e site informados por quem usa."""
    a = {"codigo": "NOVA-12345678", "fonte_lista": "informada na tela",
         "campos": {"razao_social": "NOVA S.A.", "dominio": "nova.com.br", "contato_cargo": None}}
    d = dossie.montar(ICP_PADRAO, HOJE, consultar=lambda r, h: _rec(), associadas=[a],
                      casamento=[{"codigo": "NOVA-12345678", "cnpj": "12345678000190", "status": "informado"}],
                      extracao=[], taxas={}, cnaes={}, revisoes={})
    r = d[0]["resultado"]
    dec = next(e for _, c, _, e in r.linhas if c == "decisor")
    assert dec.fonte == "site da empresa" and dec.url == "https://nova.com.br"
    assert "lista de origem" not in r.canal["descricao"]


@pytest.mark.parametrize("trecho", ["eleita o quarto melhor lugar para se trabalhar no Brasil",
                                    "entre os melhores lugares para trabalhar"])
def test_ranking_de_lugar_para_trabalhar_e_employer_branding_alto(trecho):
    ev, *_ = _ev(site=_site(employer_branding=_campo(True, trecho)))
    assert ev["employer_branding"].valor == "Alto"
