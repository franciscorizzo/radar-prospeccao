# -*- coding: utf-8 -*-
"""Demo ao vivo: uma empresa da lista passa pelo processo inteiro.

    python -m demo "serdia"                 # por nome (parte da razao social)
    python -m demo 33449965000115           # por CNPJ
    python -m demo "serdia" --gravado       # plano B: usa a leitura do site ja gravada
    python -m demo "serdia" --pausa         # espera Enter entre os passos, para apresentar

Cinco passos, cada um impresso na tela:
  1. a empresa na lista de origem e o CNPJ achado na Receita
  2. o que a Receita diz: estabelecimentos, UFs, filial nova, CNAE, porte
  3. o site lido agora pelo modelo local, com o trecho que sustenta cada campo
  4. o score, ponto a ponto, com a fonte
  5. o dossie no navegador

Se o site nao responder ou o modelo local estiver parado, a leitura gravada no
lote (extracao-v3) entra no lugar e a tela diz que entrou. Precisa do
Elasticsearch local; o modelo local so para a leitura ao vivo.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import date
from pathlib import Path

import dossie
import lote_extracao
from score import ICP_PADRAO, justificativa


class Ambiguo(LookupError):
    pass


def _digitos(t: str) -> str:
    return re.sub(r"\D", "", t)


def achar(consulta: str, associadas: list[dict], casamento: list[dict]) -> dict:
    """A associada pelo CNPJ ou por parte da razao social (sem acento, sem caixa)."""
    cnpj_de = {c["codigo"]: c.get("cnpj") for c in casamento}
    if len(_digitos(consulta)) == 14:
        alvo = _digitos(consulta)
        achadas = [a for a in associadas if cnpj_de.get(a["codigo"]) == alvo]
    else:
        termo = dossie._sem_acento(consulta).strip()
        achadas = [a for a in associadas if termo in dossie._sem_acento(a["campos"].get("razao_social") or "")]
    if not achadas:
        raise LookupError(f"nenhuma empresa da lista casa com '{consulta}'")
    if len(achadas) > 1:
        nomes = "; ".join(a["campos"]["razao_social"] for a in achadas[:10])
        raise Ambiguo(f"{len(achadas)} empresas casam com '{consulta}': {nomes}")
    return achadas[0]


def _ler_ao_vivo(associada: dict) -> dict:
    return lote_extracao.processar(associada)


def executar(consulta: str, associadas: list[dict], casamento: list[dict], hoje: date,
             consultar=dossie.receita, ler_site=_ler_ao_vivo, gravados: dict | None = None,
             taxas: dict | None = None, cnaes: dict | None = None, mostrar=None,
             usar_gravado: bool = False) -> dict:
    mostrar = mostrar or (lambda titulo, linhas: None)
    gravados = gravados or {}
    a = achar(consulta, associadas, casamento)
    c = a["campos"]
    cas = next(x for x in casamento if x["codigo"] == a["codigo"])
    da_lista = a.get("fonte_lista", dossie.FONTE_LISTA) == dossie.FONTE_LISTA
    lugar = f" ({c['municipio']}/{c['uf']})" if c.get("municipio") else ""
    linhas = [f"{c['razao_social']}{lugar}, site {c.get('dominio') or '-'}",
              f"CNPJ {cas.get('cnpj') or '-'}, " + (cas.get("origem") or "informado na tela" if cas["status"] == "informado"
                                                    else f"achado na Receita pelo nome (casamento {cas['status']})")]
    if da_lista:
        linhas.append(f"contato publicado na lista de origem: {c.get('contato_cargo') or 'sem cargo'} (o nome nao e guardado)")
    mostrar("1. Empresa " + ("na lista de origem" if da_lista else "informada na tela") + " e CNPJ na Receita",
            linhas)

    t0 = time.time()
    rec = consultar(cas["cnpj"][:8], hoje)
    f = rec.get("filial_mais_recente") or {}
    mostrar("2. O que a Receita Federal diz", [
        f"{rec['estabelecimentos']} estabelecimento(s) ativo(s) em {len(rec['ufs'])} UF: {', '.join(rec['ufs'])}",
        f"filiais abertas nos ultimos 24 meses: {rec['abertos_24m']}"
        + (f" (a mais nova em {f['municipio']}/{f['uf']}, {f['data_inicio_atividade']})" if f else ""),
        f"CNAE principal {rec.get('cnae_principal')} {(cnaes or {}).get(rec.get('cnae_principal'), '')}".strip(),
        f"porte declarado: {dossie.PORTE_RECEITA.get(rec.get('porte_receita'), '-')}"
        f"  [{time.time() - t0:.2f} s no indice local de 11,5 milhoes de estabelecimentos]"])

    t0 = time.time()
    site, origem = None, "nao lido"
    if not usar_gravado:
        try:
            site = ler_site(a)
            origem = "ao vivo" if not site.get("erro") else None
        except Exception as e:
            site, origem = None, None
            motivo = f"{type(e).__name__}"
        else:
            motivo = (site or {}).get("erro")
        if origem is None:
            site = None
    else:
        motivo = "pedido --gravado"
    if site is None and a["codigo"] in gravados:
        site, origem = gravados[a["codigo"]], f"gravado no lote ({motivo})"
    if site is not None:
        site = lote_extracao.normalizar(json.loads(json.dumps(site)))
    origem = origem or "nao lido"
    linhas = [f"leitura: {origem}  [{time.time() - t0:.0f} s]"]
    for campo, v in ((site or {}).get("campos") or {}).items():
        linhas.append(f"{campo}: {v['valor']}" + (f" (escopo {v['escopo']})" if v.get("escopo") else ""))
        linhas.append(f"    \"{v.get('trecho') or '(trecho omitido)'}\"  <{v.get('url')}>")
    descartes = len((site or {}).get("descartados") or [])
    linhas.append(f"{len(((site or {}).get('campos') or {}))} campo(s) aceito(s); {descartes} leitura(s) do modelo "
                  "recusada(s) pelo codigo (trecho fora da pagina, longo ou sem relacao com o campo)")
    mostrar("3. O site da empresa, lido pelo modelo local", linhas)

    d = dossie.montar(ICP_PADRAO, hoje, consultar=lambda raiz, h: rec, associadas=[a], casamento=[cas],
                      extracao=[site] if site else [], taxas=taxas if taxas is not None else dossie.taxas_historico(),
                      cnaes=cnaes or {}, revisoes={})[0]
    d["origem_site"] = origem
    mostrar("4. Score, ponto a ponto, com a fonte", justificativa(d["resultado"]).splitlines())
    mostrar("5. Dossie", ["abrindo no navegador"])
    return d


def _imprimir(pausa: bool):
    def mostrar(titulo, linhas):
        if pausa:
            input("\n[Enter] ")
        print(f"\n=== {titulo} ===")
        for l in linhas:
            print("  " + l)
    return mostrar


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("consulta")
    ap.add_argument("--gravado", action="store_true", help="plano B: nao le o site agora")
    ap.add_argument("--pausa", action="store_true", help="espera Enter entre os passos")
    args = ap.parse_args(argv)
    associadas = dossie._jsonl(dossie.LISTA / "lista.jsonl")
    casamento = json.loads((dossie.LISTA / "casamento.json").read_text(encoding="utf-8"))
    gravados = {r["codigo"]: r for r in dossie._jsonl(dossie.LISTA / "extracao.jsonl") if not r.get("erro")}
    hoje = date.today()
    try:
        d = executar(args.consulta, associadas, casamento, hoje, gravados=gravados, cnaes=dossie._cnaes(),
                     mostrar=_imprimir(args.pausa), usar_gravado=args.gravado)
    except LookupError as e:
        sys.exit(str(e))
    destino = abrir_no_radar(d, hoje)
    print(f"  {destino}")
    if hasattr(os, "startfile"):
        os.startfile(destino)


def abrir_no_radar(d: dict, hoje: date) -> Path:
    """O radar inteiro, com a empresa lida agora no lugar da gravada e ja aberta."""
    import radar
    arq = dossie.LISTA / f"dossie-{hoje.isoformat()}.json"
    if not arq.exists():
        dossie.main(["--top", "0"])
    dossies = [x for x in json.loads(arq.read_text(encoding="utf-8")) if x["codigo_lista"] != d["codigo_lista"]]
    dossies.append(dossie.como_dict(d))
    dossies.sort(key=lambda x: -x["score"])
    destino = dossie.LISTA / "radar-demo.html"
    destino.write_text(radar.gerar(dossies, hoje, foco=radar.empresa(dossie.como_dict(d), hoje)["id"]),
                       encoding="utf-8")
    return destino


if __name__ == "__main__":
    main()
