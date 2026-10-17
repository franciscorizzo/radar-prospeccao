# -*- coding: utf-8 -*-
"""Da marca ao CNPJ, para empresa fora da lista: site, agente de busca, verificacao.

A Receita guarda a razao social, nao a marca: "dasa" casava pelo nome com DASA -
LTDA, um motel no Amapa, e a Dasa e a DIAGNOSTICOS DA AMERICA S.A. Tres camadas,
e em todas quem decide e o codigo:

  1. CNPJ publicado no proprio site (politica de privacidade, termos, rodape),
     com digito verificador e ativo na Receita. Deterministico.
  2. Agente de busca: o modelo local nao precisa saber a resposta, precisa
     buscar. Ele tem quatro ferramentas sobre o indice da Receita (por nome, por
     ramo na tabela CNAE, maiores de um CNAE, detalhes de um CNPJ) e no maximo
     alguns passos. A resposta dele e conferida; se nao passar, vale o melhor
     candidato que ele viu e que passa.
  3. Verificacao: nome ou sigla batem com a marca (ou nome fantasia registrado),
     e mais um sinal: o ramo do CNAE aparece no texto do site, ou o porte e de
     empresa estabelecida (nao ME/EPP).
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter

from fontes import site as fonte_site

PARADAS = {"de", "da", "do", "das", "dos", "e", "em", "para", "a", "o"}
PAGINAS_LEGAIS = ("/", "/politica-de-privacidade", "/privacidade", "/termos-de-uso", "/termos",
                  "/aviso-de-privacidade", "/sobre", "/quem-somos")


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]+", " ", t)


def _palavras(t: str) -> list[str]:
    return [p for p in _norm(t).split() if p]


# --- verificacao ---------------------------------------------------------------------

def _sigla(razao: str, com_paradas: bool) -> str:
    t = _norm(re.sub(r"\bS\s*[./]?\s*A\b\.?", " SA ", razao.upper()))
    ps = [p for p in t.split() if com_paradas or p not in PARADAS]
    letras = "".join(p if p == "sa" else p[0] for p in ps if p not in ("ltda", "me", "epp", "eireli"))
    return letras


def nome_bate(marca: str, razao: str, fantasias: list[str]) -> bool:
    m = _norm(marca).replace(" ", "")
    if not m:
        return False
    tokens = _palavras(razao)
    if any(t.startswith(m) or (len(t) >= 4 and m.startswith(t) and len(m) - len(t) <= 2) for t in tokens):
        return True
    if m in (_sigla(razao, False), _sigla(razao, True)):
        return True
    return any(m == _norm(f).replace(" ", "") or m in _palavras(f) for f in fantasias or [])


def _radicais(t: str) -> set[str]:
    return {p[:6] for p in _palavras(t) if len(p) >= 5 and p not in PARADAS}


def verificar(marca: str, c: dict, texto_site: str) -> dict:
    nome = nome_bate(marca, c["razao"], c.get("fantasias") or [])
    ramo = bool(_radicais(c.get("cnae_desc") or "") & _radicais(texto_site or ""))
    porte = c.get("porte") == "05"   # "demais": nao e ME nem EPP, mesmo com so a matriz
    return {"nome": nome, "ramo": ramo, "porte": porte, "aceito": nome and (ramo or porte)}


# --- camada 1: CNPJ no site ----------------------------------------------------------

def cnpj_no_site(dominio: str, baixar=None, ativo=None, paginas=PAGINAS_LEGAIS) -> dict | None:
    baixar = baixar or (lambda u: fonte_site.baixar(u))
    ativo = ativo or (lambda raiz: bool(Indice().detalhes(raiz)))
    for caminho in paginas:
        url = f"https://www.{dominio}{caminho}"
        try:
            html = baixar(url)
        except Exception:
            continue
        for cnpj in fonte_site.cnpjs_na_pagina(html or ""):
            if ativo(cnpj[:8]):
                return {"cnpj": cnpj, "url": url}
    return None


# --- ferramentas sobre o indice ------------------------------------------------------

class Indice:
    """As quatro ferramentas do agente, sobre o Elasticsearch local."""

    def __init__(self, requisicao=None, cnaes=None):
        if requisicao is None:
            from receita_base.indice import requisicao
        self.req = requisicao
        self._cnaes = cnaes

    @property
    def cnaes(self) -> dict:
        if self._cnaes is None:
            import dossie
            self._cnaes = dossie._cnaes()
        return self._cnaes

    def detalhes(self, raiz: str) -> dict | None:
        e = self.req("POST", "/cnpj-empresas/_search", {"size": 1, "query": {"term": {"cnpj_basico": raiz}}})
        e = e["hits"]["hits"]
        if not e:
            return None
        r = self.req("POST", "/cnpj-estabelecimentos/_search", {
            "size": 0, "query": {"term": {"cnpj_basico": raiz}},
            "aggs": {"ufs": {"terms": {"field": "uf", "size": 30}},
                     "matriz": {"filter": {"term": {"matriz": True}},
                                "aggs": {"d": {"top_hits": {"size": 1, "_source": [
                                    "cnpj", "cnae_principal", "municipio", "nome_fantasia"]}}}},
                     # o indice nao tem nome_fantasia.keyword: agregar por termo voltava vazio
                     "fant": {"top_hits": {"size": 30, "_source": ["nome_fantasia"]}}}})
        a = r["aggregations"]
        m = [h["_source"] for h in a["matriz"]["d"]["hits"]["hits"]]
        cnae = m[0]["cnae_principal"] if m else None
        vistos = Counter(h["_source"].get("nome_fantasia") for h in a["fant"]["hits"]["hits"])
        fantasias = [f for f, _ in vistos.most_common() if f and f.strip()][:3]
        return {"raiz": raiz, "razao": e[0]["_source"]["razao_social"], "porte": e[0]["_source"].get("porte"),
                "estab": r["hits"]["total"]["value"], "ufs": [b["key"] for b in a["ufs"]["buckets"]],
                "cnae": cnae, "cnae_desc": self.cnaes.get(cnae, ""), "cnpj": m[0]["cnpj"] if m else None,
                "municipio": m[0].get("municipio") if m else None, "fantasias": fantasias,
                "natureza": e[0]["_source"].get("natureza_juridica")}

    def _por_raizes(self, raizes: list[str]) -> list[dict]:
        return [d for d in (self.detalhes(r) for r in raizes) if d]

    def nome(self, texto: str) -> list[dict]:
        r = self.req("POST", "/cnpj-empresas/_search", {
            "size": 6, "query": {"match": {"razao_social": {"query": texto, "operator": "and"}}}})
        raizes = [h["_source"]["cnpj_basico"] for h in r["hits"]["hits"]]
        f = self.req("POST", "/cnpj-estabelecimentos/_search", {
            "size": 0, "query": {"match": {"nome_fantasia": {"query": texto, "operator": "and"}}},
            "aggs": {"r": {"terms": {"field": "cnpj_basico", "size": 4}}}})
        raizes += [b["key"] for b in f["aggregations"]["r"]["buckets"] if b["key"] not in raizes]
        return self._por_raizes(raizes[:8])

    def lista(self, texto: str, n: int = 10) -> list[dict]:
        """Candidatos para quem digitou escolher: razao social e nome fantasia, com erro de digitacao.

        Ordem: quem casa pelo nome ou sigla (fantasia incluida) primeiro, e entre eles
        o que tem mais estabelecimentos; o resto, pela ordem de relevancia do indice.
        """
        busca = {"query": texto, "operator": "and", "fuzziness": "AUTO"}
        r = self.req("POST", "/cnpj-empresas/_search", {"size": n, "query": {"match": {"razao_social": busca}}})
        raizes = [h["_source"]["cnpj_basico"] for h in r["hits"]["hits"]]
        f = self.req("POST", "/cnpj-estabelecimentos/_search", {
            "size": 0, "query": {"match": {"nome_fantasia": busca}},
            "aggs": {"r": {"terms": {"field": "cnpj_basico", "size": n, "order": {"rel": "desc"}},
                           "aggs": {"rel": {"max": {"script": "_score"}}}}}})
        for b in f["aggregations"]["r"]["buckets"]:
            if b["key"] not in raizes:
                raizes.append(b["key"])
        cands = self._por_raizes(raizes[: 2 * n])
        ordem = {r: i for i, r in enumerate(raizes)}
        cands.sort(key=lambda c: (not nome_bate(texto, c["razao"], c["fantasias"]),
                                  -(c["estab"] or 0) if nome_bate(texto, c["razao"], c["fantasias"]) else ordem[c["raiz"]]))
        return cands[:n]

    def cnae(self, palavras: str) -> list[tuple[str, str]]:
        alvo = _radicais(palavras)
        achados = [(c, d) for c, d in self.cnaes.items() if alvo and alvo <= _radicais(d)]
        if not achados:
            achados = [(c, d) for c, d in self.cnaes.items() if alvo & _radicais(d)]
        return achados[:10]

    def maiores(self, cnae: str) -> list[dict]:
        r = self.req("POST", "/cnpj-estabelecimentos/_search", {
            "size": 0, "query": {"term": {"cnae_principal": cnae}},
            "aggs": {"r": {"terms": {"field": "cnpj_basico", "size": 6}}}})
        return self._por_raizes([b["key"] for b in r["aggregations"]["r"]["buckets"]])


# --- camada 2: agente ----------------------------------------------------------------

SISTEMA = """Voce acha o CNPJ da empresa dona de uma marca, buscando na base da Receita Federal.
A Receita guarda a razao social, que muitas vezes nao contem a marca (ex.: a marca pode ser sigla da razao social).
A cada passo escolha UMA acao:
- buscar_nome: argumento = palavras da razao social ou do nome fantasia
- buscar_cnae: argumento = palavras do ramo de atividade (ex.: "laboratorios clinicos"), devolve codigos CNAE
- maiores_por_cnae: argumento = codigo CNAE de 7 digitos, devolve as empresas com mais estabelecimentos nele
- detalhes: argumento = raiz do CNPJ (8 digitos)
- responder: argumento = raiz do CNPJ (8 digitos) da empresa dona da marca
Use o texto do site para saber o ramo e o tamanho. A raiz tem 8 digitos: copie exatamente como veio.
Responda assim que um candidato tiver nome ou sigla compativel com a marca e o ramo do site."""

ESQUEMA = {"type": "object", "properties": {
    "acao": {"type": "string", "enum": ["buscar_nome", "buscar_cnae", "maiores_por_cnae", "detalhes", "responder"]},
    "argumento": {"type": "string"}, "motivo": {"type": "string"}},
    "required": ["acao", "argumento", "motivo"]}


def _linha(c: dict) -> str:
    return (f"{c['raiz']} | {c['razao']} | {c['estab']} estab. | porte {c.get('porte')} | "
            f"CNAE {c.get('cnae')} {c.get('cnae_desc', '')} | {','.join(c.get('ufs', [])[:6])}")


def _chamar_local(sistema: str, usuario: str) -> str:
    import extrator
    texto, _ = extrator.chamar_local(sistema, usuario, esquema=ESQUEMA, nome_esquema="acao")
    return texto


def agente(marca: str, dominio: str | None, texto_site: str, indice, chamar=None, passos: int = 8) -> dict:
    chamar = chamar or _chamar_local
    vistos: dict[str, dict] = {}
    caminho = []
    historico = (f"Marca: {marca}\nSite: {dominio or '-'}\nTexto do site (inicio): {(texto_site or '')[:1500]}\n")
    resposta = None
    for _ in range(passos):
        try:
            p = json.loads(chamar(SISTEMA, historico))
        except Exception as e:
            caminho.append({"acao": "erro", "argumento": "", "motivo": type(e).__name__, "resultado": ""})
            break
        acao, arg = p.get("acao"), str(p.get("argumento", "")).strip()
        if acao == "responder":
            resposta = re.sub(r"\D", "", arg)[:8]
            caminho.append({"acao": acao, "argumento": resposta, "motivo": p.get("motivo", ""), "resultado": ""})
            break
        if acao == "buscar_nome":
            r = indice.nome(arg)
        elif acao == "maiores_por_cnae":
            r = indice.maiores(re.sub(r"\D", "", arg))
        elif acao == "detalhes":
            raiz = re.sub(r"\D", "", arg)[:8]
            if len(raiz) < 8:   # o modelo copia a raiz com digito a menos: vale o candidato ja visto
                raiz = next((v for v in vistos if v.startswith(raiz)), raiz) if raiz else raiz
            d = indice.detalhes(raiz) if len(raiz) == 8 else None
            r = [d] if d else []
        elif acao == "buscar_cnae":
            r = indice.cnae(arg)
        else:
            r = []
        if acao == "buscar_cnae":
            texto = "\n".join(f"{c} {d}" for c, d in r) or "nada"
        else:
            for c in r:
                vistos[c["raiz"]] = c
            texto = "\n".join(_linha(c) for c in r) or "nada"
        caminho.append({"acao": acao, "argumento": arg, "motivo": p.get("motivo", ""), "resultado": texto})
        historico += f"\nAcao: {acao}({arg})\nResultado:\n{texto}\n"

    if resposta and resposta not in vistos:
        d = indice.detalhes(resposta)
        if d:
            vistos[resposta] = d
    verif = {r: verificar(marca, c, texto_site) for r, c in vistos.items()}
    if resposta in verif and verif[resposta]["aceito"]:
        escolhida = resposta
    else:
        aprovadas = [r for r, v in verif.items() if v["aceito"]]
        escolhida = max(aprovadas, key=lambda r: vistos[r].get("estab") or 0) if aprovadas else None
    # resposta que nao passou, mas com nome compativel: vira sugestao, nao "nenhuma empresa"
    sugerido = (vistos[resposta] if escolhida is None and resposta in verif and verif[resposta]["nome"]
                else None)
    return {"raiz": escolhida, "candidato": vistos.get(escolhida), "verificacao": verif.get(escolhida),
            "sugerido": sugerido, "caminho": caminho}
