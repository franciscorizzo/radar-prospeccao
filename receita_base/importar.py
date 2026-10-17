# -*- coding: utf-8 -*-
"""Carrega uma competencia da base aberta do CNPJ no Elasticsearch local.

    python -m receita_base.importar 2026-09

Tres passadas, porque o filtro depende de informacao espalhada em dois arquivos
que nao estao alinhados entre si (Estabelecimentos5 comeca no CNPJ 37756105):

  A. Empresas: monta o conjunto de raizes que NAO sao empresario individual.
  B. Estabelecimentos: indexa os ativos cuja raiz esta em A, e anota quais
     raizes tem pelo menos um estabelecimento ativo.
  C. Empresas de novo: indexa so as raizes de A que apareceram ativas em B.

Disco: os 10 zips de Empresas (1,4 GB) ficam ate o fim, porque sao lidos duas
vezes. Cada zip de Estabelecimentos e baixado, lido e apagado antes do proximo,
entao o pico e o maior deles, 2,2 GB.

Retomada: cada arquivo concluido deixa um marcador `feito-B-<arquivo>`. Rodar
de novo pula o que ja foi. O id de cada documento e a chave natural, entao
reindexar sobrescreve em vez de duplicar.
"""
from __future__ import annotations

import base64
import os
from array import array
import sys
import time
import urllib.request
from pathlib import Path

from receita_base import indice, leitura

RAIZ = Path(__file__).resolve().parent.parent
REPOSITORIO = "https://arquivos.receitafederal.gov.br/public.php/webdav"
COMPARTILHAMENTO = "YggdBLfdninEJX9"
AGENTE = "ITA-Challenge-Sprint-2026/0.1 (prototipo academico; codigo aberto)"
LOTE = 5000


def pasta(competencia: str) -> Path:
    p = RAIZ / "dados-receita" / competencia
    p.mkdir(parents=True, exist_ok=True)
    return p


def baixar(competencia: str, nome: str) -> Path:
    destino = pasta(competencia) / nome
    if destino.exists():
        return destino
    auth = base64.b64encode(f"{COMPARTILHAMENTO}:".encode()).decode()
    req = urllib.request.Request(f"{REPOSITORIO}/{competencia}/{nome}",
                                 headers={"User-Agent": AGENTE, "Authorization": "Basic " + auth})
    parcial = destino.with_suffix(".parcial")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=600) as r, open(parcial, "wb") as f:
        while bloco := r.read(1 << 20):
            f.write(bloco)
    os.replace(parcial, destino)
    log(f"baixado {nome}: {destino.stat().st_size / 1e6:.0f} MB em {time.time() - t0:.0f}s")
    return destino


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def _marcador(competencia: str, passada: str, nome: str) -> Path:
    return pasta(competencia) / f"feito-{passada}-{nome}"


def salvar_conjunto(caminho: Path, conjunto: set[int]) -> None:
    """Raizes de CNPJ cabem em 32 bits sem sinal: 4 bytes por raiz em disco."""
    parcial = caminho.with_suffix(".parcial")
    with open(parcial, "wb") as f:
        array("I", sorted(conjunto)).tofile(f)
    os.replace(parcial, caminho)


def ler_conjunto(caminho: Path) -> set[int]:
    a = array("I")
    with open(caminho, "rb") as f:
        a.frombytes(f.read())
    return set(a)


def passada_a(competencia: str, arquivos: list[str]) -> set[int]:
    salvo = pasta(competencia) / "raizes-nao-ei.bin"
    if salvo.exists():
        nao_ei = ler_conjunto(salvo)
        log(f"A: {len(nao_ei):,} raizes lidas de {salvo.name}, sem reler Empresas")
        return nao_ei
    nao_ei = set()
    for nome in arquivos:
        for campos in leitura.linhas(baixar(competencia, nome)):
            if leitura.empresa(campos) is not None:
                nao_ei.add(int(campos[0]))
        log(f"A {nome}: {len(nao_ei):,} raizes acumuladas que nao sao empresario individual")
    salvar_conjunto(salvo, nao_ei)
    return nao_ei


def passada_b(competencia: str, arquivos: list[str], nao_ei: set[int], destino: str,
              municipios: dict, apagar_depois: bool = True) -> set[int]:
    ativas = set()
    for nome in arquivos:
        marcador = _marcador(competencia, "B", nome)
        salvo = pasta(competencia) / f"ativas-{nome}.bin"
        if marcador.exists() and salvo.exists():
            # Concluido numa rodada anterior. O zip pode ja ter sido apagado, e
            # baixar de novo so para recalcular o conjunto custaria gigabytes.
            ativas |= ler_conjunto(salvo)
            continue
        caminho = baixar(competencia, nome)
        lote, total, t0, deste = [], 0, time.time(), set()
        for campos in leitura.linhas(caminho):
            if not campos or not campos[0].isdigit() or int(campos[0]) not in nao_ei:
                continue
            doc = leitura.estabelecimento(campos, municipios)
            if doc is None:
                continue
            deste.add(int(doc["cnpj_basico"]))
            lote.append(doc)
            if len(lote) >= LOTE:
                total += indice.enviar_lote(destino, lote, "cnpj")
                lote = []
        total += indice.enviar_lote(destino, lote, "cnpj")
        salvar_conjunto(salvo, deste)
        marcador.touch()
        ativas |= deste
        log(f"B {nome}: {total:,} estabelecimentos ativos indexados em {time.time() - t0:.0f}s")
        if apagar_depois:
            caminho.unlink(missing_ok=True)
    return ativas


def passada_c(competencia: str, arquivos: list[str], ativas: set[int], destino: str) -> int:
    total = 0
    for nome in arquivos:
        marcador = _marcador(competencia, "C", nome)
        if marcador.exists():
            continue
        lote, n, t0 = [], 0, time.time()
        for campos in leitura.linhas(baixar(competencia, nome)):
            doc = leitura.empresa(campos)
            if doc is None or int(doc["cnpj_basico"]) not in ativas:
                continue
            lote.append(doc)
            if len(lote) >= LOTE:
                n += indice.enviar_lote(destino, lote, "cnpj_basico")
                lote = []
        n += indice.enviar_lote(destino, lote, "cnpj_basico")
        marcador.touch()
        total += n
        log(f"C {nome}: {n:,} empresas indexadas em {time.time() - t0:.0f}s")
    return total


def _existe(nome_indice: str) -> bool:
    try:
        indice.requisicao("HEAD", f"/{nome_indice}")
        return True
    except indice.ErroIndice:
        return False


def importar(competencia: str, empresas: list[str], estabelecimentos: list[str],
             apagar_estabelecimentos: bool = True) -> None:
    t0 = time.time()
    municipios = leitura.tabela_codigos(baixar(competencia, "Municipios.zip"))
    idx_estab = indice.nome_indice("estabelecimentos", competencia)
    idx_emp = indice.nome_indice("empresas", competencia)
    if not _existe(idx_estab):
        indice.criar("estabelecimentos", competencia)
    if not _existe(idx_emp):
        indice.criar("empresas", competencia)

    nao_ei = passada_a(competencia, empresas)
    ativas = passada_b(competencia, estabelecimentos, nao_ei, idx_estab, municipios,
                       apagar_estabelecimentos)
    del nao_ei
    log(f"{len(ativas):,} raizes com estabelecimento ativo")
    passada_c(competencia, empresas, ativas, idx_emp)

    indice.finalizar(idx_estab, "cnpj-estabelecimentos")
    indice.finalizar(idx_emp, "cnpj-empresas")
    log(f"concluido em {(time.time() - t0) / 60:.0f} min")


if __name__ == "__main__":
    comp = sys.argv[1] if len(sys.argv) > 1 else "2026-09"
    importar(comp,
             [f"Empresas{i}.zip" for i in range(10)],
             [f"Estabelecimentos{i}.zip" for i in range(10)])
