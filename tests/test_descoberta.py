# -*- coding: utf-8 -*-
"""Descoberta de paginas quando a home nao tem link para carreiras ou institucional.

Medido nas primeiras 25 lista de exemplo (ficticia): em 19 o extrator nao achou nada, e
na maioria so a home foi lida, porque o menu nao tinha link reconhecivel. Duas
saidas baratas, nesta ordem: o sitemap do site, e os caminhos de praxe.
"""
from fontes import site

SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.x.com.br/</loc></url>
  <url><loc>https://www.x.com.br/produtos/inversor-500</loc></url>
  <url><loc>https://www.x.com.br/quem-somos/</loc></url>
  <url><loc>https://www.x.com.br/trabalhe-conosco/</loc></url>
  <url><loc>https://outro-dominio.com/sobre</loc></url>
</urlset>"""

INDICE = """<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://www.x.com.br/page-sitemap.xml</loc></sitemap>
</sitemapindex>"""


def test_sitemap_simples_entrega_carreiras_e_institucional():
    paginas = {"https://www.x.com.br/sitemap.xml": SITEMAP}
    achados = site.paginas_pelo_sitemap("x.com.br", baixador=lambda u: paginas[u],
                                        declarados=[])
    assert achados["institucional"] == ["https://www.x.com.br/quem-somos/"]
    assert achados["carreiras"] == ["https://www.x.com.br/trabalhe-conosco/"]
    assert achados["externos"] == ["https://outro-dominio.com/sobre"]


def test_indice_de_sitemap_e_seguido():
    paginas = {"https://www.x.com.br/sitemap_index.xml": INDICE,
               "https://www.x.com.br/page-sitemap.xml": SITEMAP}
    achados = site.paginas_pelo_sitemap("x.com.br", baixador=lambda u: paginas[u],
                                        declarados=["https://www.x.com.br/sitemap_index.xml"])
    assert achados["carreiras"] == ["https://www.x.com.br/trabalhe-conosco/"]


def test_sitemap_ausente_devolve_vazio_e_nao_quebra():
    def nada(url):
        raise site.Indisponivel("404")
    achados = site.paginas_pelo_sitemap("x.com.br", baixador=nada, declarados=[])
    assert achados == {"carreiras": [], "institucional": [], "externos": []}


def test_caminhos_de_praxe_cobrem_os_dois_tipos():
    caminhos = site.CAMINHOS_DE_PRAXE
    assert "/quem-somos" in caminhos["institucional"]
    assert "/trabalhe-conosco" in caminhos["carreiras"]
