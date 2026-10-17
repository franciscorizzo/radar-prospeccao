# -*- coding: utf-8 -*-
"""Site oficial de empresa nova: palpite local pelo nome, depois a busca na web do Claude.

O caso que motivou: OSTEN. A razao social e PLATINUM AUTOMOVEIS IMPORTADOS LTDA, o
nome fantasia e OSTEN GROUP, e o site e osten.com.br, que nao publica o CNPJ.
"""
import site_oficial as so

OSTEN = "<html><head><title>OSTEN | Concessionarias BMW e Volvo</title></head><body>Grupo Osten</body></html>"
OUTRA = "<html><head><title>Platinum Joias</title></head><body>joias finas</body></html>"


def test_palpites_saem_da_marca_e_do_nome_fantasia_sem_palavra_generica():
    p = so.palpites(["osten", "OSTEN GROUP"])
    assert p[:2] == ["osten.com.br", "osten.com"]
    assert "ostengroup.com.br" in p and not any(d.startswith("group.") for d in p)


def test_palpite_vale_quando_o_titulo_da_pagina_cita_o_nome():
    paginas = {"https://www.osten.com.br/": OSTEN}
    r = so.conferir("osten.com.br", ["osten", "OSTEN GROUP"], baixar=lambda u: paginas[u])
    assert r["dominio"] == "osten.com.br" and "OSTEN" in r["titulo"]


def test_palpite_com_titulo_de_outra_empresa_nao_vale():
    assert so.conferir("platinum.com.br", ["OSTEN GROUP"], baixar=lambda u: OUTRA) is None


def test_site_fora_do_ar_nao_vale():
    def baixar(u):
        raise so.fonte_site.Indisponivel("timeout")
    assert so.conferir("osten.com", ["osten"], baixar=baixar) is None


def test_sem_chave_do_claude_vale_o_palpite():
    paginas = {"https://www.osten.com.br/": OSTEN}

    def baixar(u):
        if u not in paginas:
            raise so.fonte_site.Indisponivel("404")
        return paginas[u]

    r = so.descobrir("osten", "PLATINUM AUTOMOVEIS IMPORTADOS LTDA", ["OSTEN GROUP"], "SAO PAULO", "SP",
                     "04625102000110", baixar=baixar, claude=lambda **k: None)
    assert r["dominio"] == "osten.com.br" and r["origem"] == "palpite pelo nome, conferido no titulo da pagina"


def test_com_chave_o_claude_vem_antes_do_palpite():
    """osten.com.br e da Osten Ferragens (PR): o titulo "OSTEN" enganou o palpite."""
    paginas = {"https://www.osten.com.br/": "<title>OSTEN</title>Osten Ferragens",
               "https://www.ostengroup.com.br/": "<title>Osten Group | BMW e Volvo</title>"}
    pedidos = []

    def claude(**k):
        pedidos.append(k)
        return "ostengroup.com.br"

    r = so.descobrir("osten", "PLATINUM AUTOMOVEIS IMPORTADOS LTDA", ["OSTEN GROUP"], "SAO PAULO", "SP",
                     "04625102000110", baixar=lambda u: paginas[u], claude=claude,
                     cnae="Comércio a varejo de automóveis")
    assert r["dominio"] == "ostengroup.com.br" and "Claude" in r["origem"]
    assert pedidos[0]["cnae"] == "Comércio a varejo de automóveis"


def test_claude_sem_certeza_nao_cai_no_palpite():
    r = so.descobrir("osten", "PLATINUM AUTOMOVEIS IMPORTADOS LTDA", ["OSTEN GROUP"], "SAO PAULO", "SP",
                     "04625102000110", baixar=lambda u: OSTEN, claude=lambda **k: "NENHUM")
    assert r is None


def test_sem_palpite_o_claude_acha_e_o_codigo_confere():
    paginas = {"https://www.grupoexemplo.com.br/": "<title>Inicio</title><p>Somos a Exemplo Distribuidora</p>"}

    def baixar(u):
        if u not in paginas:
            raise so.fonte_site.Indisponivel("404")
        return paginas[u]

    r = so.descobrir(None, "EXEMPLO DISTRIBUIDORA LTDA", [], "CAMPINAS", "SP", "11222333000181",
                     baixar=baixar, claude=lambda **k: "O site oficial e https://www.grupoexemplo.com.br/")
    assert r["dominio"] == "grupoexemplo.com.br" and "Claude" in r["origem"]


def test_dominio_do_claude_vale_pela_sigla_da_razao_social():
    """dasa.com.br diz "Dasa"; a razao social e DIAGNOSTICOS DA AMERICA S.A."""
    pagina = "<title>Dasa - Lider em Medicina Diagnostica</title>"
    r = so.descobrir(None, "DIAGNOSTICOS DA AMERICA S.A.", [], "BARUERI", "SP", "61486650000183",
                     baixar=lambda u: pagina if "dasa" in u else (_ for _ in ()).throw(so.fonte_site.Indisponivel("x")),
                     claude=lambda **k: "dasa.com.br")
    assert r["dominio"] == "dasa.com.br"


def test_dominio_do_claude_que_nao_cita_a_empresa_nao_vale_mas_fica_dito():
    r = so.descobrir(None, "EXEMPLO DISTRIBUIDORA LTDA", [], "CAMPINAS", "SP", "11222333000181",
                     baixar=lambda u: OUTRA, claude=lambda **k: "platinumjoias.com.br")
    assert r["dominio"] is None and r["indicado"] == "platinumjoias.com.br"


def test_empresario_individual_nao_vai_para_a_api():
    """Em MEI e empresario individual a razao social e o nome da pessoa: dado pessoal nao sai da maquina."""
    def claude(**k):
        raise AssertionError("dado de pessoa fisica enviado a API externa")
    r = so.descobrir(None, "JOAO DA SILVA 12345678901", [], "CAMPINAS", "SP", "11222333000181",
                     baixar=lambda u: (_ for _ in ()).throw(so.fonte_site.Indisponivel("x")), claude=claude,
                     natureza="2135")
    assert r is None


def test_quem_e_pessoa_fisica():
    assert so.pessoa_fisica("2135", "JOAO DA SILVA")              # empresario individual, MEI
    assert so.pessoa_fisica("4120", "JOAO DA SILVA")              # produtor rural pessoa fisica
    assert so.pessoa_fisica(None, "MARIA SOUZA 12345678901")      # CPF na razao social
    assert not so.pessoa_fisica("2054", "TOTVS S.A.")             # sociedade anonima
    assert not so.pessoa_fisica("2062", "CONQUESTONE IT SERVICES BR LTDA.")


def test_claude_sem_resposta_ou_sem_chave_devolve_none():
    def baixar(u):
        raise so.fonte_site.Indisponivel("404")
    assert so.descobrir(None, "EXEMPLO LTDA", [], "X", "SP", "1", baixar=baixar, claude=lambda **k: None) is None
    assert so.descobrir(None, "EXEMPLO LTDA", [], "X", "SP", "1", baixar=baixar, claude=lambda **k: "NENHUM") is None
