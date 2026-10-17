# -*- coding: utf-8 -*-
"""Site da propria empresa: onde estao carreiras e lideranca.

Duas regras que este modulo faz cumprir, e nenhuma e detalhe:

  - **robots.txt antes de qualquer GET.** Nao e cortesia: e a diferenca entre
    consultar fonte publica e raspar site alheio, e e a posicao que as entregas
    assumiram por escrito. Se o robots nega, a funcao levanta `Bloqueado` e
    nao busca.
  - **Dominio proprio, nunca agregador.** O link de carreiras que aponta para
    fora do dominio da empresa e devolvido separado, marcado como externo, para
    quem consome decidir. O protótipo nao segue esses links.

O agente identifica o projeto e um contato. Fingir navegador seria a mesma
coisa que dizer nos documentos que respeitamos os termos e nao respeitar.
"""
from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from functools import lru_cache

AGENTE = ("ITA-Challenge-Sprint-2026/0.1 "
          "(prototipo academico; codigo aberto)")

# Segmento de caminho, nao pedaco de texto solto: "sobre" casa com /sobre/ e
# com /quem-somos, e nao com /tudo-sobre-arraial-do-cabo.
PADROES = {
    "carreiras": r"(carreira|carreiras|trabalhe-conosco|trabalhe|vagas|jobs|careers)",
    "institucional": r"(sobre|sobre-nos|quem-somos|institucional|a-empresa|about|lideranca|governanca)",
}


class Bloqueado(Exception):
    """O robots.txt do site nega este caminho para o nosso agente."""


class Indisponivel(Exception):
    """O site respondeu erro, ou nao respondeu. Inclui 403 de protecao de bot."""


class RobotsIndisponivel(Exception):
    """O robots.txt nao pode ser lido por falha de servidor ou de rede.

    Diferente de nao existir: nao existir libera, nao conseguir ler nao diz
    nada, e na duvida nao se busca.
    """


def _ler_robots(host: str) -> str | None:
    """Texto do robots.txt, ou None quando o site declara que nao ha um.

    Busca com o agente do projeto. A versao anterior deixava o
    `RobotFileParser` buscar sozinho, com o agente padrao do urllib, e varios
    sites corporativos devolvem 403 para esse agente -- o parser traduz 403 em
    "tudo proibido", e o modulo passava a recusar site que na verdade libera.
    Foi o caso de totvs.com, abes.org.br e abia.org.br.
    """
    req = urllib.request.Request(f"https://{host}/robots.txt",
                                 headers={"User-Agent": AGENTE})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            bruto = r.read()
            cod = r.headers.get_content_charset() or "utf-8"
        return decodificar(bruto, cod)
    except urllib.error.HTTPError as e:
        if 400 <= e.code < 500:
            return None  # nao ha robots: a convencao e liberar
        raise RobotsIndisponivel(f"HTTP {e.code} em {host}/robots.txt") from e
    except Exception as e:
        raise RobotsIndisponivel(f"{type(e).__name__} em {host}/robots.txt") from e


@lru_cache(maxsize=256)
def _robots(host: str) -> urllib.robotparser.RobotFileParser:
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(f"https://{host}/robots.txt")
    texto = _ler_robots(host)
    rp.parse((texto or "").splitlines())
    return rp


def permitido(url: str) -> bool:
    host = urllib.parse.urlsplit(url).netloc
    return _robots(host).can_fetch(AGENTE, url)


def baixar(url: str, tempo: int = 25) -> str:
    """GET com o agente do projeto, depois de consultar o robots."""
    if not permitido(url):
        raise Bloqueado(f"robots.txt nega {url} para o nosso agente")
    req = urllib.request.Request(url, headers={"User-Agent": AGENTE})
    try:
        with urllib.request.urlopen(req, timeout=tempo) as r:
            bruto = r.read()
            codificacao = r.headers.get_content_charset() or "utf-8"
    except Exception as e:  # HTTPError, URLError, timeout
        raise Indisponivel(f"{type(e).__name__} em {url}: {e}") from e
    return decodificar(bruto, codificacao)


def decodificar(bruto: bytes, charset: str | None) -> str:
    """Decodifica pelo charset declarado; se o nome nao existe, UTF-8."""
    try:
        return bruto.decode(charset or "utf-8", "replace")
    except LookupError:  # ex.: "utf8mb4", nome do MySQL
        return bruto.decode("utf-8", "replace")


def _mesmo_dominio(dominio: str, url: str) -> bool:
    host = urllib.parse.urlsplit(url).netloc.lower()
    return host == dominio or host.endswith("." + dominio)


def classificar_links(html: str, dominio: str, base: str = "") -> dict:
    """Separa os links da home em carreiras, institucional e externos.

    Devolve {"carreiras": [...], "institucional": [...], "externos": [...]},
    cada lista com URL absoluta, sem repetir, na ordem em que aparecem.
    """
    base = base or f"https://{dominio}/"
    achados = {"carreiras": [], "institucional": [], "externos": []}
    vistos = set()
    for href in re.findall(r'href="([^"]+)"', html, re.I):
        url = urllib.parse.urljoin(base, href.strip())
        if not url.startswith(("http://", "https://")) or url in vistos:
            continue
        caminho = urllib.parse.urlsplit(url).path.lower()
        host = urllib.parse.urlsplit(url).netloc.lower()
        segmentos = [s for s in caminho.split("/") if s] or [""]
        for tipo, padrao in PADROES.items():
            casou_caminho = any(re.fullmatch(padrao + r"(-[a-z0-9-]+)?", s) for s in segmentos)
            # Subdominio: "portalcarreira.locadora.exemplo" e carreiras, e o nome
            # vem colado. Olhamos so o primeiro rotulo do host.
            rotulo = host.split(".")[0]
            casou_host = re.search(r"(carreira|vagas|jobs|trabalhe|talento)", rotulo) is not None
            if casou_caminho or (tipo == "carreiras" and casou_host):
                vistos.add(url)
                alvo = tipo if _mesmo_dominio(dominio, url) else "externos"
                achados[alvo].append(url)
                break
    return achados


def descobrir(dominio: str, baixador=baixar) -> dict:
    """Da home da empresa, acha as paginas de carreiras e institucional."""
    home = f"https://{dominio}/"
    html = baixador(home)
    achados = classificar_links(html, dominio, home)
    achados["home"] = home
    return achados

# --- CNPJ publicado na propria pagina ---------------------------------------
#
# Loja virtual brasileira e obrigada a publicar o CNPJ (Decreto 7.962/2013), e
# muita empresa que nao vende online publica tambem, quase sempre no rodape. E o
# elo entre um site conhecido e o cadastro da Receita, sem busca paga por nome.

_CNPJ = re.compile(r"(?<!\d)(\d{2})\.?(\d{3})\.?(\d{3})/?(\d{4})-?(\d{2})(?!\d)")


def cnpj_valido(cnpj: str) -> bool:
    d = re.sub(r"\D", "", cnpj)
    if len(d) != 14 or d == d[0] * 14:
        return False
    def dv(base: str) -> str:
        pesos = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2][-len(base):]
        resto = sum(int(a) * b for a, b in zip(base, pesos)) % 11
        return "0" if resto < 2 else str(11 - resto)
    return dv(d[:12]) == d[12] and dv(d[:13]) == d[13]


def cnpjs_na_pagina(html: str) -> list[str]:
    """CNPJs validos no texto da pagina, na ordem em que aparecem, sem repetir."""
    texto = re.sub(r"<[^>]+>", " ", html)
    achados = []
    for m in _CNPJ.finditer(texto):
        numero = "".join(m.groups())
        if cnpj_valido(numero) and numero not in achados:
            achados.append(numero)
    return achados


# --- quando a home nao tem link reconhecivel --------------------------------------
#
# Medido nas primeiras 25 lista de exemplo (ficticia): na maioria so a home foi lida,
# porque o menu nao tinha link para carreiras ou institucional que o descobridor
# reconhecesse. Duas saidas, nesta ordem, as duas educadas: o sitemap que o
# proprio site publica para ser lido, e os caminhos de praxe.

CAMINHOS_DE_PRAXE = {
    "institucional": ["/sobre", "/sobre-nos", "/quem-somos", "/a-empresa", "/empresa",
                      "/institucional", "/about", "/about-us"],
    "carreiras": ["/trabalhe-conosco", "/carreiras", "/vagas", "/careers"],
}


def paginas_pelo_sitemap(dominio: str, baixador=None, declarados=None, limite_filhos: int = 5) -> dict:
    """URLs de carreiras e institucional listadas no sitemap do site.

    `declarados` sao os sitemaps que o robots.txt anuncia; sem eles, tenta os
    nomes de praxe. Indice de sitemap e seguido ate `limite_filhos` arquivos.
    """
    baixador = baixador or baixar
    if declarados is None:
        try:
            declarados = list(_robots(dominio if dominio.startswith("www.") else "www." + dominio).site_maps() or [])
        except Exception:
            declarados = []
    candidatos = declarados or [f"https://www.{dominio}/sitemap.xml", f"https://www.{dominio}/sitemap_index.xml"]
    locs, fila, vistos = [], list(candidatos), set()
    while fila and len(vistos) < limite_filhos + len(candidatos):
        url = fila.pop(0)
        if url in vistos:
            continue
        vistos.add(url)
        try:
            xml = baixador(url)
        except Exception:
            continue
        achados = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)
        if "<sitemapindex" in xml:
            fila.extend(achados[:limite_filhos])
        else:
            locs.extend(achados)
    html = "".join(f'<a href="{u}">x</a>' for u in locs)
    return classificar_links(html, dominio, f"https://www.{dominio}/")
