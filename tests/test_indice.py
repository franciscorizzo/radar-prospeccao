# -*- coding: utf-8 -*-
import json

import pytest

from receita_base import indice


def test_nome_do_indice_leva_a_competencia():
    assert indice.nome_indice("empresas", "2026-09") == "cnpj-empresas-2026-09"


def test_corpo_bulk_usa_a_chave_natural_como_id():
    corpo = indice.corpo_bulk("cnpj-empresas-2026-09",
                              [{"cnpj_basico": "00000000", "razao_social": "BANCO DO BRASIL SA"}],
                              "cnpj_basico")
    linhas = corpo.strip().split("\n")
    assert json.loads(linhas[0]) == {"index": {"_index": "cnpj-empresas-2026-09", "_id": "00000000"}}
    assert json.loads(linhas[1])["razao_social"] == "BANCO DO BRASIL SA"
    assert corpo.endswith("\n")


def test_lote_com_documento_recusado_e_erro_e_nao_silencio():
    def enviar(*a, **k):
        return {"errors": True, "items": [{"index": {"error": {"type": "mapper_parsing_exception"}}}]}
    with pytest.raises(indice.ErroIndice, match="1 documentos recusados"):
        indice.enviar_lote("x", [{"k": "1"}], "k", enviar=enviar)


def test_criar_desliga_refresh_e_replica_na_carga():
    chamadas = []
    indice.criar("empresas", "2026-09", enviar=lambda *a, **k: chamadas.append(a))
    metodo, caminho, corpo = chamadas[0]
    assert (metodo, caminho) == ("PUT", "/cnpj-empresas-2026-09")
    assert corpo["settings"]["refresh_interval"] == "-1"
    assert corpo["settings"]["number_of_replicas"] == 0
    assert corpo["mappings"]["properties"]["razao_social"]["analyzer"] == "nome"


@pytest.mark.es
def test_ida_e_volta_no_elasticsearch_local():
    """Contra o Elasticsearch de verdade, num indice de teste que se apaga."""
    nome = indice.criar("empresas", "teste")
    try:
        indice.enviar_lote(nome, [
            {"cnpj_basico": "61079117", "razao_social": "ABB AUTOMACAO LTDA", "porte": "05"},
            {"cnpj_basico": "00000000", "razao_social": "BANCO DO BRASIL SA", "porte": "05"},
        ], "cnpj_basico")
        indice.requisicao("POST", f"/{nome}/_refresh")
        r = indice.requisicao("POST", f"/{nome}/_search",
                              {"query": {"match": {"razao_social": {"query": "abb automação", "fuzziness": "AUTO"}}}})
        assert r["hits"]["hits"][0]["_source"]["cnpj_basico"] == "61079117"
    finally:
        indice.requisicao("DELETE", f"/{nome}")


def test_conexao_que_cai_e_refeita_e_a_requisicao_repetida(monkeypatch):
    """A carga de fumaca caiu com timeout de conexao. A requisicao tem que
    sobreviver a uma queda e repetir, porque reenviar e idempotente."""
    tentativas = {"n": 0}

    class Conexao:
        def request(self, *a, **k):
            tentativas["n"] += 1
            if tentativas["n"] == 1:
                raise TimeoutError("WinError 10060")
        def getresponse(self):
            class R:
                status = 200
                def read(self): return b'{"ok": true}'
            return R()
        def close(self): pass

    monkeypatch.setattr(indice, "_conectar", lambda: Conexao())
    monkeypatch.setattr(indice.time, "sleep", lambda s: None)
    assert indice.requisicao("GET", "/") == {"ok": True}
    assert tentativas["n"] == 2


def test_desiste_depois_de_esgotar_as_tentativas(monkeypatch):
    class Morta:
        def request(self, *a, **k): raise ConnectionRefusedError()
        def close(self): pass
    monkeypatch.setattr(indice, "_conectar", lambda: Morta())
    monkeypatch.setattr(indice.time, "sleep", lambda s: None)
    with pytest.raises(indice.ErroIndice, match="apos 3 tentativas"):
        indice.requisicao("GET", "/", tentativas=3)


def test_endereco_remoto_e_recusado_antes_de_conectar():
    """A base da Receita so vai para Elasticsearch local. Um host remoto, mesmo
    configurado por engano, e recusado sem abrir conexao."""
    with pytest.raises(indice.ErroIndice, match="nao e Elasticsearch local"):
        indice._host_local("https://elasticsearch-x-hml.es.eastus2.azure.elastic-cloud.com/")


def test_hosts_locais_passam():
    assert indice._host_local("http://127.0.0.1:9200") == ("127.0.0.1", 9200)
    assert indice._host_local("http://elasticsearch:9200") == ("elasticsearch", 9200)


def test_variavel_generica_es_url_e_ignorada(monkeypatch):
    """ES_URL e nome comum, e ja existe nesta maquina apontando para outro
    lugar. O modulo so le ITA_ES_URL."""
    import importlib
    monkeypatch.setenv("ES_URL", "https://algum-cluster-remoto.example.com/")
    monkeypatch.delenv("ITA_ES_URL", raising=False)
    recarregado = importlib.reload(indice)
    assert recarregado.URL == "http://127.0.0.1:9200"
