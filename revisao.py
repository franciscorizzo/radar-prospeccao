# -*- coding: utf-8 -*-
"""Revisao humana da evidencia: o laco de retroalimentacao do dossie real.

    python -m revisao <codigo> <criterio> confirmada|errada ["motivo"]
    python -m revisao --resumo

Quem aborda a conta confere a evidencia contra a pagina. O veredito fica num
arquivo de revisoes e volta para o dossie na rodada seguinte:

  - errada: a evidencia sai do score, o criterio volta para "sem evidencia" e
    o dossie avisa que houve recusa. Nao some calada.
  - confirmada: a evidencia fica, marcada como revisada por pessoa.

E o resumo das revisoes e a precisao do extrator medida por quem usa, por
criterio -- o numero que a Semana 4 pede ("existem respostas incorretas ou sem
sustentacao?").

O arquivo guarda codigo, criterio, veredito, motivo e data. Nao guarda quem
revisou: nao precisa, e seria dado pessoal.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

from score import CRITERIOS, Evidencia

ARQUIVO = Path(os.environ.get("RADAR_DADOS") or Path(__file__).resolve().parent / "dados-exemplo") / "revisoes.jsonl"
VEREDITOS = ("confirmada", "errada")


def registrar(codigo: str, criterio: str, veredito: str, motivo: str = "",
              arquivo: Path = ARQUIVO, hoje: date | None = None) -> dict:
    if criterio not in CRITERIOS:
        raise ValueError(f"criterio desconhecido: {criterio}; use um de {CRITERIOS}")
    if veredito not in VEREDITOS:
        raise ValueError(f"veredito: {VEREDITOS}")
    r = {"codigo": str(codigo), "criterio": criterio, "veredito": veredito, "motivo": motivo,
         "data": (hoje or date.today()).isoformat()}
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    with open(arquivo, "a", encoding="utf-8") as f:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return r


def carregar(arquivo: Path = ARQUIVO) -> dict[tuple[str, str], dict]:
    """O veredito mais recente por (codigo, criterio)."""
    if not arquivo.exists():
        return {}
    ultimo = {}
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        if linha.strip():
            r = json.loads(linha)
            ultimo[(r["codigo"], r["criterio"])] = r
    return ultimo


def aplicar(codigo: str, ev: dict[str, Evidencia], revisoes: dict) -> tuple[dict, list[str]]:
    """Tira do score o que a revisao recusou e marca o que ela confirmou."""
    saida, alertas = dict(ev), []
    for criterio, e in ev.items():
        r = revisoes.get((str(codigo), criterio))
        if not r or e is None:
            continue
        if r["veredito"] == "errada":
            del saida[criterio]
            alertas.append(f"Evidencia de {criterio} recusada na revisao de {r['data']}"
                           + (f": {r['motivo']}" if r["motivo"] else ""))
        else:
            saida[criterio] = Evidencia(e.valor, e.fonte, tipo=f"{e.tipo}, revisado por pessoa em {r['data']}",
                                        url=e.url, detalhe=e.detalhe)
    return saida, alertas


def resumo(revisoes: dict) -> dict:
    """Precisao por criterio, segundo quem revisou."""
    por = {}
    for (_, criterio), r in revisoes.items():
        c = por.setdefault(criterio, {"confirmada": 0, "errada": 0})
        c[r["veredito"]] += 1
    for c in por.values():
        c["precisao"] = c["confirmada"] / (c["confirmada"] + c["errada"])
    return por


if __name__ == "__main__":
    if sys.argv[1:] == ["--resumo"]:
        for criterio, c in sorted(resumo(carregar()).items()):
            print(f"{criterio:20} {c['precisao']:.0%} ({c['confirmada']} confirmadas, {c['errada']} erradas)")
    else:
        print(registrar(*sys.argv[1:5]))
