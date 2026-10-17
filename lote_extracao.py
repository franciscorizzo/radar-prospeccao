# -*- coding: utf-8 -*-
"""Extracao em lote: para cada associada da lista de origem com site, le as paginas e
extrai os campos do ICP com o modelo local.

    python -m lote_extracao <associadas.jsonl> <saida.jsonl>

Retomavel: cada empresa concluida vira uma linha na saida, e rodar de novo pula
quem ja esta la. Falha numa empresa vira linha com `erro`, e o lote segue.

Feito para rodar no container `extrator` do compose, que fica fora do limite de
10 minutos dos comandos do ambiente de desenvolvimento.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import extrator


def ja_feitos(saida: Path) -> set[str]:
    if not saida.exists():
        return set()
    return {json.loads(l)["codigo"] for l in saida.read_text(encoding="utf-8").splitlines() if l.strip()}


def processar(associada: dict, chamar=None, paginas=None) -> dict:
    c = associada["campos"]
    registro = {"codigo": associada["codigo"], "razao_social": c.get("razao_social"),
                "dominio": c.get("dominio")}
    t0 = time.time()
    try:
        texto, tentativas = (paginas or extrator.paginas_do_site)(c["dominio"])
        registro["paginas"] = tentativas
        if not texto:
            registro["erro"] = "nenhuma pagina legivel"
            return registro
        r = extrator.extrair(texto, c.get("razao_social", ""), chamar=chamar or extrator.chamar_local)
        registro.update(r)
    except Exception as e:  # uma empresa quebrada nao derruba o lote
        registro["erro"] = f"{type(e).__name__}: {e}"
    registro["segundos"] = round(time.time() - t0, 1)
    return registro


def rodar(entrada: Path, saida: Path, chamar=None, paginas=None, log=print) -> int:
    associadas = [json.loads(l) for l in entrada.read_text(encoding="utf-8").splitlines() if l.strip()]
    com_site = [a for a in associadas if "campos" in a and a["campos"].get("dominio")]
    feitos = ja_feitos(saida)
    pendentes = [a for a in com_site if a["codigo"] not in feitos]
    log(f"{len(com_site)} com site, {len(feitos)} ja feitas, {len(pendentes)} pendentes")
    with open(saida, "a", encoding="utf-8") as f:
        for i, a in enumerate(pendentes, 1):
            r = processar(a, chamar, paginas)
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            achados = len(r.get("campos") or {})
            log(f"{i}/{len(pendentes)} {r['razao_social'][:40]}: {achados} campos"
                + (f", ERRO {r['erro'][:60]}" if r.get("erro") else "") + f" ({r.get('segundos', 0)}s)")
    return len(pendentes)


def normalizar(registro: dict) -> dict:
    """Reaplica as regras de pos-processamento a um registro gravado antes delas.

    Telefone e e-mail pessoal saem do trecho; valor numerico que nao confere com
    o trecho passa a vir do trecho; campo que a pertinencia de hoje recusa sai,
    registrado como descarte. Nao chama o modelo de novo.
    """
    campos = registro.get("campos") or {}
    for campo in list(campos):
        c = campos[campo]
        if c.get("trecho") and not extrator.pertinente(campo, c["trecho"]):
            del campos[campo]
            registro.setdefault("descartados", []).append(
                {"campo": campo, "tamanho": len(c["trecho"]), "motivo": "trecho nao sustenta o campo (regra posterior)"})
            continue
        if c.get("trecho"):
            mascarado = extrator.mascarar_contato(c["trecho"])
            if mascarado != c["trecho"]:
                c["trecho"], c["trecho_mascarado"] = mascarado, True
            if campo not in extrator.BOOLEANOS:
                c["valor"] = extrator._confere_com_trecho(c["valor"], c["trecho"])
    return registro


if __name__ == "__main__":
    if sys.argv[1] == "--normalizar":
        caminho = Path(sys.argv[2])
        linhas = [normalizar(json.loads(l)) for l in caminho.read_text(encoding="utf-8").splitlines() if l.strip()]
        caminho.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in linhas), encoding="utf-8")
        print(f"{len(linhas)} registros normalizados")
        sys.exit()
    rodar(Path(sys.argv[1]), Path(sys.argv[2]), log=lambda m: print(time.strftime("%H:%M:%S"), m, flush=True))
