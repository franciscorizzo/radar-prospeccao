# -*- coding: utf-8 -*-
"""Descoberta de paginas no site da propria empresa.

Fixture e a home de uma locadora ficticia, so com as ancoras.
"""
from pathlib import Path

import pytest

from fontes import site

FIXTURE = Path(__file__).parent / "fixtures" / "home-locadora-exemplo.html"


@pytest.fixture(scope="module")
def html():
    return FIXTURE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def achados(html):
    return site.classificar_links(html, "locadora.exemplo", "https://locadora.exemplo/")


def test_acha_o_portal_de_carreiras_mesmo_em_subdominio(achados):
    assert any("portalcarreira.locadora.exemplo" in u for u in achados["carreiras"])


def test_nao_confunde_sobre_no_meio_de_uma_frase(achados):
    """'/tudo-sobre-praias-do-litoral' nao e pagina institucional.

    O casamento e por segmento de caminho inteiro, nao por trecho solto: foi
    isso que a home real devolveu como falso positivo na primeira tentativa.
    """
    todos = achados["carreiras"] + achados["institucional"]
    assert not any("praias" in u for u in todos)


def test_link_para_fora_do_dominio_sai_separado():
    html = ('<a href="https://vagas.com.br/empresa/x">Vagas</a>'
            '<a href="https://minhaempresa.com.br/carreiras">Carreiras</a>')
    r = site.classificar_links(html, "minhaempresa.com.br")
    assert r["externos"] == ["https://vagas.com.br/empresa/x"]
    assert r["carreiras"] == ["https://minhaempresa.com.br/carreiras"]


def test_link_relativo_vira_absoluto():
    r = site.classificar_links('<a href="/sobre/">Sobre</a>', "x.com.br")
    assert r["institucional"] == ["https://x.com.br/sobre/"]


def test_nada_e_buscado_quando_o_robots_nega(monkeypatch):
    monkeypatch.setattr(site, "permitido", lambda url: False)
    with pytest.raises(site.Bloqueado):
        site.baixar("https://exemplo.com.br/")


def test_descobrir_usa_o_baixador_injetado(html):
    r = site.descobrir("locadora.exemplo", baixador=lambda url: html)
    assert r["home"] == "https://locadora.exemplo/"
    assert r["carreiras"]


@pytest.mark.rede
def test_robots_real_de_sites_que_bloqueiam_agente_padrao():
    """totvs.com, abes.org.br e abia.org.br devolvem 403 no robots.txt para o
    agente padrao do urllib, e 200 para o nosso. Os tres LIBERAM a raiz. Este
    teste existe porque a primeira versao do modulo dizia que os tres
    proibiam."""
    site._robots.cache_clear()
    for url in ("https://localiza.com/", "https://www.totvs.com/",
                "https://abes.org.br/", "https://abia.org.br/"):
        assert site.permitido(url) is True, url
    site._robots.cache_clear()


@pytest.mark.rede
def test_robots_real_proibe_onde_de_fato_proibe():
    site._robots.cache_clear()
    assert site.permitido("https://www.totvs.com/wp-json/alguma-coisa") is False
    site._robots.cache_clear()


def test_403_no_robots_nao_vira_tudo_proibido(monkeypatch):
    """Regressao: varios sites corporativos devolvem 403 para o agente padrao
    do urllib. A versao anterior lia isso como "o site proibe tudo" e recusava
    fonte valida. 4xx significa que nao ha robots, e sem robots se busca."""
    site._robots.cache_clear()
    monkeypatch.setattr(site, "_ler_robots", lambda host: None)
    assert site.permitido("https://exemplo.com.br/qualquer") is True
    site._robots.cache_clear()


def test_robots_ilegivel_por_falha_de_servidor_nao_libera(monkeypatch):
    """5xx e timeout nao dizem nada sobre politica. Na duvida, nao se busca."""
    site._robots.cache_clear()
    def explode(host):
        raise site.RobotsIndisponivel("HTTP 503")
    monkeypatch.setattr(site, "_ler_robots", explode)
    with pytest.raises(site.RobotsIndisponivel):
        site.permitido("https://exemplo.com.br/")
    site._robots.cache_clear()


def test_robots_real_e_respeitado_quando_de_fato_proibe(monkeypatch):
    site._robots.cache_clear()
    monkeypatch.setattr(site, "_ler_robots",
                        lambda host: "User-agent: *\nDisallow: /privado/\n")
    assert site.permitido("https://exemplo.com.br/publico") is True
    assert site.permitido("https://exemplo.com.br/privado/x") is False
    site._robots.cache_clear()


def test_charset_desconhecido_cai_em_utf8():
    """sisvoo.com.br declara charset=utf8mb4, nome do MySQL que o Python nao conhece."""
    from fontes.site import decodificar
    assert decodificar("ação".encode("utf-8"), "utf8mb4") == "ação"
    assert decodificar("ação".encode("latin-1"), "iso-8859-1") == "ação"
    assert decodificar(b"abc", None) == "abc"
