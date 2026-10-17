# -*- coding: utf-8 -*-
"""Site oficial de empresa nova, quando ninguem digitou o site.

Duas camadas, e nas duas quem aceita e o codigo:

  1. Busca na web do Claude, quando ha chave. Vai para a API apenas o que ja e
     publico: razao social, nome fantasia, ramo, cidade e CNPJ. O dominio que
     volta tem que responder e citar a empresa (nome, fantasia ou sigla).
  2. Palpite local, so sem chave: o dominio sai da marca digitada e do nome
     fantasia (OSTEN GROUP -> osten.com.br). Vale se o titulo da pagina cita o
     nome. E fraco com marca de palavra comum: osten.com.br e da Osten
     Ferragens, nao da concessionaria. Por isso nao e o primeiro.

A descoberta automatica por Maps, Places e dominio de e-mail foi descartada
(Desafio/descoberta-de-dominio.md); esta nao depende de nenhuma delas.
"""
from __future__ import annotations

import os
import re
import unicodedata

from fontes import site as fonte_site

GENERICAS = {"ltda", "sa", "me", "epp", "eireli", "group", "grupo", "brasil", "brazil", "do", "da", "de", "dos",
             "das", "e", "comercio", "industria", "servicos", "empresa", "companhia", "cia", "holding",
             "participacoes", "importados", "importadora", "distribuidora", "the", "and"}
MODELO = "claude-sonnet-5-5"
_DOMINIO = re.compile(r"\b((?:[a-z0-9-]+\.)+[a-z]{2,})\b")


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]+", " ", t)


def _palavras(nome: str) -> list[str]:
    return [p for p in _norm(nome).split() if p not in GENERICAS]


def palpites(nomes: list[str], limite: int = 6) -> list[str]:
    """Dominios provaveis, na ordem: marca digitada, depois nomes fantasia."""
    bases = []
    for nome in nomes:
        ps = _palavras(nome)
        if not ps:
            continue
        juntas = "".join(_norm(nome).split())
        # so a primeira palavra quando ela e o nome inteiro: "conquest.com.br" nao e a Conquest One
        for b in ([ps[0]] if len(ps) == 1 else []) + ["".join(ps), juntas]:
            if len(b) >= 3 and b not in bases:
                bases.append(b)
    dominios = [f"{b}.{tld}" for b in bases for tld in ("com.br", "com")]
    return dominios[:limite]


def _titulo(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.I | re.S)
    return " ".join(m.group(1).split()) if m else ""


def _cita(texto: str, nomes: list[str]) -> bool:
    alvo = set(_norm(texto).split())
    return any(p in alvo for nome in nomes for p in _palavras(nome) if len(p) >= 4)


def conferir(dominio: str, nomes: list[str], baixar=None, so_titulo: bool = True) -> dict | None:
    """O dominio vale se a pagina responde e cita a empresa (no titulo, para palpite)."""
    baixar = baixar or fonte_site.baixar
    url = f"https://www.{dominio}/"
    try:
        html = baixar(url)
    except Exception:
        return None
    titulo = _titulo(html)
    if _cita(titulo, nomes):
        return {"dominio": dominio, "url": url, "titulo": titulo}
    if not so_titulo:
        import extrator
        if _cita(extrator.texto_de_html(html)[:5000], nomes):
            return {"dominio": dominio, "url": url, "titulo": titulo}
    return None


def pelo_claude(razao: str, fantasias: list[str], municipio: str, uf: str, cnpj: str, cnae: str = "") -> str | None:
    """Texto da resposta do Claude com busca na web; None so quando nao ha chave."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    import anthropic
    pedido = (f"Qual e o site institucional oficial desta empresa brasileira?\n"
              f"Razao social: {razao}\nNome fantasia: {', '.join(fantasias) or '-'}\n"
              f"Ramo (CNAE): {cnae or '-'}\nCidade: {municipio}/{uf}\nCNPJ: {cnpj}\n"
              "Cuidado com empresas homonimas de outro ramo ou outra cidade. "
              "Responda so com o dominio (ex.: empresa.com.br), ou NENHUM se nao tiver certeza.")
    cliente = anthropic.Anthropic()
    mensagens = [{"role": "user", "content": pedido}]
    r = None
    for _ in range(3):   # a busca no servidor pode pausar o turno; retoma ate 3 vezes
        r = cliente.messages.create(model=MODELO, max_tokens=2048, messages=mensagens,
                                    tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 3}])
        if r.stop_reason != "pause_turn":
            break
        mensagens.append({"role": "assistant", "content": r.content})
    return "".join(b.text for b in r.content if b.type == "text") if r else None


def pessoa_fisica(natureza: str | None, razao: str) -> bool:
    """Empresario individual, MEI e naturezas de pessoa fisica: a razao social e o nome da pessoa.

    2135 e o empresario individual (o MEI e um deles); a familia 4xxx e de pessoa
    fisica (produtor rural, candidato, ...). Na duvida, CPF escrito na razao social.
    """
    n = (natureza or "").strip()
    return n == "2135" or n.startswith("4") or bool(re.search(r"\d{11}", razao or ""))


def descobrir(marca: str | None, razao: str, fantasias: list[str], municipio: str, uf: str, cnpj: str,
              baixar=None, claude=None, cnae: str = "", natureza: str | None = None) -> dict | None:
    """{dominio, url, titulo, origem} ou None.

    Com chave, o Claude vem primeiro, porque sabe a cidade e o ramo: o palpite
    "osten.com.br" tinha o titulo "OSTEN" e era da Osten Ferragens, nao da
    concessionaria. Se o Claude nao tem certeza, nao ha site: o palpite fica so
    para quando nao ha chave.
    """
    nomes = [n for n in [marca, *fantasias] if n]
    if pessoa_fisica(natureza, razao):   # LGPD: nome de pessoa nao vai para API externa
        claude = lambda **k: None
    resposta = (claude or pelo_claude)(razao=razao, fantasias=fantasias, municipio=municipio, uf=uf, cnpj=cnpj,
                                       cnae=cnae)
    if resposta is None:   # sem chave: so o palpite local
        for d in palpites(nomes):
            r = conferir(d, nomes, baixar=baixar)
            if r:
                return {**r, "origem": "palpite pelo nome, conferido no titulo da pagina"}
        return None
    if "NENHUM" in resposta.upper():
        return None
    m = _DOMINIO.search(resposta.lower())
    if not m:
        return None
    dominio = m.group(1).removeprefix("www.")
    from resolucao import _sigla   # DIAGNOSTICOS DA AMERICA S.A. -> dasa
    siglas = [s for s in {_sigla(razao, False), _sigla(razao, True)} if len(s) >= 3]
    r = conferir(dominio, nomes + [razao] + siglas, baixar=baixar, so_titulo=False)
    if r:
        return {**r, "origem": "busca na web (Claude), conferido na pagina"}
    # o Claude indicou, o codigo nao confirmou (pagina recusa leitura ou nao cita a empresa)
    return {"dominio": None, "indicado": dominio, "origem": "busca na web (Claude), nao confirmado"}
