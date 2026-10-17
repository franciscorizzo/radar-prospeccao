# -*- coding: utf-8 -*-
"""Casamento de nome publicado por uma fonte com a razao social da Receita.

O problema real, medido em 8 lista de exemplo (ficticia): a fonte abrevia (IND, EQUIP,
INDUST), a Receita as vezes escreve por extenso, e palavra comum de setor
("AUTOMACAO") faz empresa errada parecer certa. A primeira versao, com busca
aproximada e desempate pela cidade, acertou 5, errou 1 e nao achou 2.

Duas regras saem disso:

  - **Toda palavra distintiva do nome tem que casar**, como prefixo, para
    aceitar abreviacao. E isso que separa APB de CMV.
  - **Na duvida, nao chuta.** CNPJ errado e pior que CNPJ nenhum: ele carrega
    o cadastro de outra empresa para dentro do dossie, com cara de verdade.
    Dois candidatos igualmente bons viram "ambiguo".

Cidade e UF da matriz servem para graduar a confianca, nao para decidir: Sao
Paulo desempata pouco, e a fonte pode publicar o endereco de uma filial.
"""
from __future__ import annotations

import re
import unicodedata

# Siglas de duas letras sem ambiguidade. Duas letras so casam exatas (a v3
# deixou "sc" casar com "schneider"), entao estas sao expandidas antes.
SIGLAS = {"br": "brasil"}

PARADAS = {"ltda", "ltd", "sa", "s", "a", "me", "epp", "eireli", "cia",
           "do", "da", "de", "dos", "das", "e", "em", "the", "of"}


def _ascii(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()


def tokens(nome: str) -> list[str]:
    """Palavras distintivas, minusculas e sem acento, na ordem.

    Letras soltas em sequencia viram uma palavra: "J.M." e "jm", "A/V" e "av".
    Sem isso, "J.M. FONTANA" perdia a sigla, e a fonte que escreve "JM" nao
    casava.
    """
    partes = re.findall(r"[a-z0-9]+", _ascii(nome).lower())
    juntas, letras = [], ""
    for p in partes:
        if len(p) == 1:
            letras += p
            continue
        if letras:
            juntas.append(letras)
            letras = ""
        juntas.append(p)
    if letras:
        juntas.append(letras)
    # Letra solta que sobra conta: em "T SERVICES" ela e a marca. Na v4 ela era
    # descartada, "services" virava marca e casava com SERVIT e SERVILUZ.
    return [SIGLAS.get(p, p) for p in juntas if p not in PARADAS]


def variantes(nome: str) -> list[str]:
    """O nome, e o nome sem o que vem depois de um travessao.

    A lista de origem pendura marca no fim: "LEGRAND BRASIL LTDA – GL". Mas o
    travessao tambem aparece no meio de nome de verdade ("UTILI ENERGIA –
    EQUIP E SOLUCOES"), entao a versao cortada e tentativa a mais, nao troca.
    """
    corte = re.split(r"\s[–—-]\s", nome, maxsplit=1)
    if len(corte) == 2 and tokens(corte[0]):
        return [nome, corte[0].strip()]
    return [nome]


def _subsequencia(curta: str, longa: str) -> bool:
    it = iter(longa)
    return all(ch in it for ch in curta)


def _casa(a: str, b: str, exata_ate: int = 2, radical: bool = True) -> bool:
    """Prefixo em qualquer direcao, abreviacao que pula letras, ou mesmo radical.

    "inds" casa com "industrias", "maqs" com "maquinas", "medica" com "medico".
    Palavra com ate `exata_ate` letras so casa exata: na v3, "sc" (de S&C) casou
    como prefixo de "schneider", e "br" como prefixo de "brothertec". A
    abreviacao precisa ter 3 letras ou mais e comecar pelas mesmas duas, senao
    vira coringa: "apb" e subsequencia de muita coisa.
    """
    if a == b:
        return True
    curta, longa = (a, b) if len(a) <= len(b) else (b, a)
    # Curta demais so casa exata, a menos que seja prefixo de palavra longa: "nac"
    # abrevia "nacional", mas "itb" nao abrevia "itbf" (a v3 casou os dois).
    if len(curta) <= exata_ate:
        return len(curta) >= 3 and len(longa) >= 6 and longa.startswith(curta)
    if longa.startswith(curta):
        return True
    if radical and len(curta) >= 5 and curta[:5] == longa[:5]:
        return True
    return len(curta) >= 3 and curta[:2] == longa[:2] and _subsequencia(curta, longa)


def similaridade(fonte: list[str], receita: list[str]) -> float:
    """Fracao das palavras da fonte que casam com alguma da Receita."""
    if not fonte:
        return 0.0
    return sum(any(_casa(f, r) for r in receita) for f in fonte) / len(fonte)


GENERICAS = {"ind", "industria", "industrias", "industrial", "fab", "fabrica", "com",
             "comercio", "grupo", "centro", "sociedade", "companhia", "empresa"}


def marca(toks: list[str]) -> str | None:
    """A primeira palavra distintiva que nao e generica.

    Em "S/A FAB PAPELAO TIMBO" a marca e "papelao": "fab" e so fabrica, e na v4,
    tratada como marca de 3 letras, exigia casamento exato e perdeu a empresa.
    """
    for t in toks:
        if t not in GENERICAS:
            return t
    return toks[0] if toks else None


def marca_casa(fonte: list[str], receita: list[str]) -> bool:
    """A marca nunca pode ser a palavra que falta, e casa sem radical.

    Na v3, a tolerancia de uma palavra faltando deixou VOICEINTERACTION casar com
    BROTHERTEC. Na v4, o radical de 5 letras casou SIEMENS com SIEMEX e DIGITRO
    com DIGITAL. Marca de ate 4 letras so casa exata, porque ITB casou com ITBF.
    """
    m = marca(fonte)
    return m is not None and any(_casa(m, r, exata_ate=4, radical=False) for r in receita)


def consulta(nome: str, tamanho: int = 10) -> dict:
    """Query do Elasticsearch: cada palavra distintiva como prefixo.

    Com ate 3 palavras, todas obrigatorias. Com mais, tolera uma faltando, porque
    a lista da lista de origem corta nomes longos.
    """
    toks = tokens(nome)
    exigidas = len(toks) if len(toks) <= 3 else len(toks) - 1
    return {"bool": {
        # Prefixo curto so para RECUPERAR candidatos: "maqs" nao e prefixo de
        # "maquinas", mas "maq" e. O rigor de verdade fica em decidir().
        "should": [{"prefix": {"razao_social": t if len(t) <= 3 else t[:3]}} for t in toks]
                  + [{"match": {"razao_social": {"query": nome, "boost": 0.1}}}],
        "minimum_should_match": exigidas,
    }}


def _mesmo_lugar(cidade: str, uf: str, cand: dict) -> bool:
    return (_ascii(cidade).upper().strip() == _ascii(cand.get("municipio") or "").upper().strip()
            and (uf or "").upper() == (cand.get("uf") or "").upper())


def decidir(nome: str, cidade: str, uf: str, candidatos: list[dict]) -> dict:
    """Escolhe o CNPJ, ou declara que nao da para escolher.

    status: confiavel (nome e cidade da matriz), provavel (nome, cidade
    diferente), ambiguo (mais de um igualmente bom), nao_encontrado.

    Ranqueia por duas medidas: quanto do nome da fonte a Receita cobre, e quanto
    do nome da Receita a fonte cobre. A segunda separou HARTING de HARTING
    FASHION: as duas cobrem "harting", so uma nao sobra palavra.
    """
    toks = tokens(nome)
    exigencia = 1.0 if len(toks) <= 3 else (len(toks) - 1) / len(toks)
    avaliados = []
    for cd in candidatos:
        rt = tokens(cd["razao_social"])
        if not marca_casa(toks, rt):
            continue
        ida = similaridade(toks, rt)
        if ida >= exigencia:
            # Marca identica ganha de marca que so comeca igual: DIGITRO e prefixo
            # de DIGITRONIX, e as duas casavam com o mesmo peso.
            identica = marca(toks) in rt
            # Identica so desempata: na v5 ela vinha primeiro, e GRUPO MULTI foi
            # para GRUPO FG MULTI SERVICOS em vez de GRUPO MULTILASER.
            avaliados.append(((ida, similaridade(rt, toks), identica), cd))
    if not avaliados:
        return {"status": "nao_encontrado"}
    melhor = max(chave for chave, _ in avaliados)
    topo = [cd for chave, cd in avaliados if chave == melhor]
    locais = [cd for cd in topo if _mesmo_lugar(cidade, uf, cd)]
    if len(locais) > 1 or (not locais and len(topo) > 1):
        return {"status": "ambiguo", "candidatos": [cd["cnpj"] for cd in (locais or topo)]}
    escolhido = locais[0] if locais else topo[0]
    status = "confiavel" if locais else "provavel"
    # Uma palavra distintiva so, e a Receita com palavra a mais: pouco nome para
    # tanta certeza.
    if status == "confiavel" and len(toks) == 1 and melhor[1] < 1.0:
        status = "provavel"
    return {"status": status, "cnpj": escolhido["cnpj"], "candidato": escolhido}


_ORDEM = {"confiavel": 0, "provavel": 1, "ambiguo": 2, "nao_encontrado": 3}


def _buscar_um(nome, cidade, uf, requisicao, tamanho):
    hits = requisicao("POST", "/cnpj-empresas/_search",
                      {"size": tamanho, "query": consulta(nome)})["hits"]["hits"]
    if not hits:
        return {"status": "nao_encontrado"}
    nomes = {h["_source"]["cnpj_basico"]: h["_source"]["razao_social"] for h in hits}
    matrizes = requisicao("POST", "/cnpj-estabelecimentos/_search", {
        "size": len(nomes),
        "query": {"bool": {"filter": [{"terms": {"cnpj_basico": list(nomes)}},
                                      {"term": {"matriz": True}}]}},
    })["hits"]["hits"]
    candidatos = [{"cnpj": m["_source"]["cnpj"], "razao_social": nomes[m["_source"]["cnpj_basico"]],
                   "municipio": m["_source"].get("municipio"), "uf": m["_source"].get("uf")}
                  for m in matrizes]
    return decidir(nome, cidade, uf, candidatos)


def buscar(nome: str, cidade: str, uf: str, requisicao=None, tamanho: int = 50) -> dict:
    """Consulta a base propria para cada variante do nome e fica com a melhor.

    `requisicao` e injetavel para teste.
    """
    if requisicao is None:
        from receita_base.indice import requisicao
    resultados = [_buscar_um(v, cidade, uf, requisicao, tamanho) for v in variantes(nome)]
    return min(resultados, key=lambda r: _ORDEM[r["status"]])


if __name__ == "__main__":
    # python -m receita_base.casamento associadas.jsonl casamento.json
    import json
    import sys
    from pathlib import Path

    saida = []
    for linha in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
        a = json.loads(linha)
        c = a["campos"]
        r = buscar(c["razao_social"], c.get("municipio") or "", c.get("uf") or "")
        saida.append({"codigo": a["codigo"], "lista": c["razao_social"], "cidade": c.get("municipio"),
                      "uf": c.get("uf"), **r})
    Path(sys.argv[2]).write_text(json.dumps(saida, ensure_ascii=False, indent=1), encoding="utf-8")
    contagem = {}
    for r in saida:
        contagem[r["status"]] = contagem.get(r["status"], 0) + 1
    print(contagem)
