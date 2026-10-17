# -*- coding: utf-8 -*-
"""Conversa com o Elasticsearch local por HTTP puro, sem biblioteca cliente.

Um indice por competencia (`cnpj-empresas-2026-09`) e um alias estavel
(`cnpj-empresas`) que aponta para a competencia vigente. Trocar de mes e trocar
o alias, sem janela em que a busca fica vazia: a ideia e do projeto de 2024,
que ja nomeava o indice pela competencia.
"""
from __future__ import annotations

import http.client
import json
import os
import time
import urllib.parse

# Na maquina, 127.0.0.1. No container da carga, o nome do servico no compose.
#
# A variavel tem nome proprio do projeto de proposito. A primeira versao lia
# `ES_URL`, e essa variavel ja existia no ambiente do autor apontando para
# um Elasticsearch de homologacao na nuvem. O teste de integracao passou a
# mirar la, e so nao gravou porque a conexao expirou antes de sair requisicao.
URL = os.environ.get("ITA_ES_URL", "http://127.0.0.1:9200")

# Esta base so vai para Elasticsearch local. Qualquer outro host e recusado
# antes de abrir conexao, mesmo que alguem configure a variavel errado.
HOSTS_LOCAIS = {"127.0.0.1", "localhost", "elasticsearch"}


def _host_local(url: str) -> tuple[str, int]:
    partes = urllib.parse.urlsplit(url)
    if partes.hostname not in HOSTS_LOCAIS:
        raise ErroIndice(f"Recusado: {partes.hostname!r} nao e Elasticsearch local. "
                         f"Esta base so e carregada em {sorted(HOSTS_LOCAIS)}.")
    return partes.hostname, partes.port or 9200

_TEXTO_PT = {
    "analysis": {
        "analyzer": {
            "nome": {"type": "custom", "tokenizer": "standard",
                     "filter": ["lowercase", "asciifolding"]},
        }
    }
}

MAPEAMENTOS = {
    "empresas": {
        "properties": {
            "cnpj_basico": {"type": "keyword"},
            "razao_social": {"type": "text", "analyzer": "nome",
                             "fields": {"exato": {"type": "keyword"}}},
            "natureza_juridica": {"type": "keyword"},
            "porte": {"type": "keyword"},
            "capital_social": {"type": "double"},
        }
    },
    "estabelecimentos": {
        "properties": {
            "cnpj": {"type": "keyword"},
            "cnpj_basico": {"type": "keyword"},
            "matriz": {"type": "boolean"},
            "nome_fantasia": {"type": "text", "analyzer": "nome"},
            "data_inicio_atividade": {"type": "date"},
            "cnae_principal": {"type": "keyword"},
            "cnaes_secundarios": {"type": "keyword"},
            "uf": {"type": "keyword"},
            "municipio_codigo": {"type": "keyword"},
            "municipio": {"type": "keyword"},
            "cep": {"type": "keyword"},
        }
    },
}


class ErroIndice(Exception):
    pass


_conexao: http.client.HTTPConnection | None = None


def _conectar() -> http.client.HTTPConnection:
    """Uma conexao persistente por processo.

    A primeira versao abria uma conexao TCP nova a cada requisicao. Medido:
    3.000 requisicoes levaram 36 s assim e 6 s com conexao persistente, e a
    versao antiga deixou quase 3.000 sockets em TIME_WAIT. Numa carga de horas
    isso se acumula, e a carga de fumaca caiu com timeout de conexao.
    """
    global _conexao
    if _conexao is None:
        host, porta = _host_local(URL)
        _conexao = http.client.HTTPConnection(host, porta, timeout=300)
    return _conexao


def _descartar_conexao() -> None:
    global _conexao
    if _conexao is not None:
        _conexao.close()
    _conexao = None


def requisicao(metodo: str, caminho: str, corpo=None, ndjson: bool = False,
               tentativas: int = 5):
    """Requisicao ao Elasticsearch, com nova tentativa se a conexao cair.

    Tentar de novo e seguro aqui porque toda escrita usa a chave natural como
    id: reenviar um lote sobrescreve os mesmos documentos, nao duplica.
    """
    dados = None
    cabecalhos = {}
    if corpo is not None:
        dados = corpo.encode("utf-8") if isinstance(corpo, str) else json.dumps(corpo).encode("utf-8")
        cabecalhos["Content-Type"] = "application/x-ndjson" if ndjson else "application/json"
    espera = 2.0
    for tentativa in range(1, tentativas + 1):
        try:
            c = _conectar()
            c.request(metodo, caminho, body=dados, headers=cabecalhos)
            r = c.getresponse()
            texto = r.read().decode("utf-8")
        except (OSError, http.client.HTTPException) as e:
            _descartar_conexao()
            if tentativa == tentativas:
                raise ErroIndice(f"{metodo} {caminho}: {type(e).__name__} apos {tentativas} tentativas") from e
            time.sleep(espera)
            espera *= 2
            continue
        if r.status >= 400:
            raise ErroIndice(f"{metodo} {caminho}: HTTP {r.status} {texto[:300]!r}")
        return json.loads(texto) if texto else {}


def nome_indice(tipo: str, competencia: str) -> str:
    return f"cnpj-{tipo}-{competencia}"


def criar(tipo: str, competencia: str, enviar=requisicao) -> str:
    """Cria o indice da competencia, sem replica e sem refresh durante a carga."""
    nome = nome_indice(tipo, competencia)
    enviar("PUT", f"/{nome}", {
        "settings": {"number_of_shards": 1, "number_of_replicas": 0,
                     "refresh_interval": "-1", **_TEXTO_PT},
        "mappings": MAPEAMENTOS[tipo],
    })
    return nome


def corpo_bulk(indice: str, documentos: list[dict], chave: str) -> str:
    """NDJSON de indexacao. O id e a chave natural, entao recarregar sobrescreve
    em vez de duplicar."""
    partes = []
    for d in documentos:
        partes.append(json.dumps({"index": {"_index": indice, "_id": d[chave]}}))
        partes.append(json.dumps(d, ensure_ascii=False))
    return "\n".join(partes) + "\n"


def enviar_lote(indice: str, documentos: list[dict], chave: str, enviar=requisicao) -> int:
    if not documentos:
        return 0
    r = enviar("POST", "/_bulk", corpo_bulk(indice, documentos, chave), ndjson=True)
    if r.get("errors"):
        falhas = [i for i in r["items"] if i["index"].get("error")]
        raise ErroIndice(f"{len(falhas)} documentos recusados; primeiro: {falhas[0]['index']['error']}")
    return len(documentos)


def finalizar(indice: str, alias: str, enviar=requisicao) -> None:
    """Liga o refresh, e aponta o alias para esta competencia, tirando da anterior."""
    enviar("PUT", f"/{indice}/_settings", {"index": {"refresh_interval": "1s"}})
    enviar("POST", f"/{indice}/_refresh")
    acoes = [{"remove": {"index": f"cnpj-{alias.split('-', 1)[1]}-*", "alias": alias}},
             {"add": {"index": indice, "alias": alias}}]
    try:
        enviar("POST", "/_aliases", {"actions": acoes})
    except ErroIndice:
        enviar("POST", "/_aliases", {"actions": acoes[1:]})
