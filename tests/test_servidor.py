# -*- coding: utf-8 -*-
"""Radar ao vivo: resolver a empresa digitada e o fluxo HTTP de ponta a ponta."""
import http.client
import json
import threading
import time
from datetime import date

import pytest

import dossie
import servidor
from score import ICP_PADRAO
from tests.test_dossie import HOJE, _associada, _rec
from tests.test_demo import CAS, _lista


# --- resolver -------------------------------------------------------------------

def test_empresa_da_lista_por_nome():
    a, cas = servidor.resolver("serdia", None, _lista(), CAS)
    assert a["codigo"] == "8" and cas["status"] == "confiavel"


def test_empresa_nova_por_cnpj_usa_a_razao_da_receita_e_o_site_informado():
    a, cas = servidor.resolver("11.222.333/0001-81", "https://www.nova.com.br/sobre", _lista(), CAS,
                               razao_por_cnpj=lambda raiz: "NOVA IND LTDA")
    assert cas == {"codigo": "NOVA-11222333", "cnpj": "11222333000181", "status": "informado",
                   "origem": "informado na tela"}
    assert a["campos"]["razao_social"] == "NOVA IND LTDA" and a["campos"]["dominio"] == "nova.com.br"
    assert a["fonte_lista"] == "informada na tela"


def test_empresa_escolhida_na_lista_sem_site_ganha_o_site_descoberto():
    passos = []
    achado = {"dominio": "osten.com.br", "origem": "palpite pelo nome, conferido no titulo da pagina",
              "titulo": "OSTEN | Concessionarias"}
    a, cas = servidor.resolver("04625102000110", None, _lista(), CAS, marca="osten",
                               razao_por_cnpj=lambda raiz: "PLATINUM AUTOMOVEIS IMPORTADOS LTDA",
                               por_dominio=lambda marca, cnpj: achado,
                               mostrar=lambda t, l: passos.append((t, l)))
    assert a["campos"]["dominio"] == "osten.com.br"
    assert "site" in passos[0][0].lower() and any("osten.com.br" in l for l in passos[0][1])


def test_site_indicado_e_nao_confirmado_nao_e_lido_e_a_tela_diz():
    passos = []
    a, _ = servidor.resolver("04625102000110", None, _lista(), CAS,
                             razao_por_cnpj=lambda raiz: "PLATINUM AUTOMOVEIS IMPORTADOS LTDA",
                             por_dominio=lambda m, c: {"dominio": None, "indicado": "ostengroup.com.br",
                                                       "origem": "busca na web (Claude), nao confirmado"},
                             mostrar=lambda t, l: passos.append((t, l)))
    assert a["campos"]["dominio"] is None
    assert "nao confirmado" in passos[0][0] and "ostengroup.com.br" in passos[0][1][0]


def test_site_digitado_dispensa_a_descoberta():
    a, _ = servidor.resolver("04625102000110", "osten.com.br", _lista(), CAS,
                             razao_por_cnpj=lambda raiz: "PLATINUM AUTOMOVEIS IMPORTADOS LTDA",
                             por_dominio=lambda m, c: pytest.fail("site ja foi informado"))
    assert a["campos"]["dominio"] == "osten.com.br"


def test_site_nao_descoberto_segue_sem_site_e_diz():
    passos = []
    a, _ = servidor.resolver("04625102000110", None, _lista(), CAS,
                             razao_por_cnpj=lambda raiz: "PLATINUM AUTOMOVEIS IMPORTADOS LTDA",
                             por_dominio=lambda m, c: None, mostrar=lambda t, l: passos.append((t, l)))
    assert a["campos"]["dominio"] is None and "nao achado" in passos[0][0]


def test_cnpj_que_nao_esta_na_receita_avisa():
    with pytest.raises(LookupError):
        servidor.resolver("11222333000181", None, _lista(), CAS, razao_por_cnpj=lambda raiz: None)


def test_empresa_nova_por_nome_so_sugere_e_pede_o_cnpj():
    """"dasa" casou com DASA - LTDA, um motel no Amapa: pelo nome, so sugestao."""
    achado = {"status": "provavel", "cnpj": "51531868000159",
              "candidato": {"razao_social": "DASA - LTDA", "municipio": "MACAPA", "uf": "AP"}}
    with pytest.raises(servidor.Confirmar) as e:
        servidor.resolver("dasa", "dasa.com.br", _lista(), CAS, buscar_nome=lambda n: achado,
                          por_site=lambda d: None, por_agente=lambda m, d: {"raiz": None, "caminho": []})
    assert "DASA - LTDA" in str(e.value) and "51.531.868/0001-59" in str(e.value)


def test_resposta_do_agente_nao_conferida_vira_sugestao_com_cnpj():
    """Conquest One: o agente acertou, o codigo nao conseguiu conferir; a tela sugere em vez de dizer 'nenhuma'."""
    agente = {"raiz": None, "caminho": [{"acao": "responder", "argumento": "01802155", "motivo": ""}],
              "sugerido": {"razao": "CONQUESTONE IT SERVICES BR LTDA.", "cnpj": "01802155000162", "ufs": ["SP"]}}
    with pytest.raises(servidor.Confirmar) as e:
        servidor.resolver("Conquest One", None, _lista(), CAS, por_site=lambda d: None,
                          por_agente=lambda m, d: agente,
                          buscar_nome=lambda n: pytest.fail("a sugestao do agente vem antes da busca por nome"))
    assert "CONQUESTONE" in str(e.value) and "01.802.155/0001-62" in str(e.value)


def test_nome_ambiguo_na_receita_pede_cnpj():
    with pytest.raises(LookupError) as e:
        servidor.resolver("weg", None, _lista(), CAS,
                          buscar_nome=lambda n: {"status": "ambiguo", "candidatos": ["1", "2"]},
                          por_site=lambda d: None, por_agente=lambda m, d: {"raiz": None, "caminho": []})
    assert "CNPJ" in str(e.value)


# --- HTTP de ponta a ponta ------------------------------------------------------------

def _base(tmp_path, monkeypatch):
    monkeypatch.setattr(servidor, "ANALISADAS", tmp_path / "analisadas.jsonl")
    base = object.__new__(servidor.Base)
    base.hoje, base.associadas, base.casamento = HOJE, _lista(), CAS
    base.gravados, base.cnaes, base.taxas = {}, {}, {"Indústria": 0.5}
    d = dossie.montar(ICP_PADRAO, HOJE, consultar=lambda r, h: _rec(), associadas=[_associada()],
                      casamento=[CAS[0]], extracao=[], taxas={}, cnaes={}, revisoes={})[0]
    base.dossies = {"7": dossie.como_dict(d)}
    base.trabalhos, base.trava = {}, threading.Lock()
    return base


def test_fluxo_http_analisa_e_devolve_a_empresa_para_o_painel(tmp_path, monkeypatch):
    base = _base(tmp_path, monkeypatch)
    orig = base.analisar

    def analisar_sem_rede(consulta, site):
        import demo
        def executar(*a, **k):
            return demo.executar(*a, **{**k, "consultar": lambda raiz, hoje: _rec(),
                                        "ler_site": lambda assoc: {"erro": "sem rede no teste"}})
        return orig(consulta, site, executar=executar)

    base.analisar = analisar_sem_rede
    srv = servidor.criar_servidor(base, porta=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    porta = srv.server_address[1]
    try:
        c = http.client.HTTPConnection("127.0.0.1", porta, timeout=10)
        c.request("GET", "/")
        pagina = c.getresponse().read().decode("utf-8")
        assert "ANALISAR EMPRESA AO VIVO" in pagina and "window.RADAR=" in pagina

        c.request("POST", "/analisar", body=json.dumps({"consulta": "serdia"}),
                  headers={"Content-Type": "application/json"})
        tid = json.loads(c.getresponse().read())["id"]
        for _ in range(50):
            c.request("GET", f"/trabalho/{tid}")
            t = json.loads(c.getresponse().read())
            if t["status"] != "rodando":
                break
            time.sleep(0.1)
        assert t["status"] == "pronto", t
        assert len(t["passos"]) == 5 and t["empresa"]["id"] == "LISTA-8"
        assert "8" in base.dossies
        assert json.loads((tmp_path / "analisadas.jsonl").read_text(encoding="utf-8"))["codigo_lista"] == "8"

        c.request("POST", "/analisar", body=json.dumps({"consulta": ""}),
                  headers={"Content-Type": "application/json"})
        r = c.getresponse()
        assert r.status == 400
        r.read()
    finally:
        srv.shutdown()


def test_buscar_devolve_a_lista_para_escolher_ou_aponta_a_associada(tmp_path, monkeypatch):
    base = _base(tmp_path, monkeypatch)
    base.indice = type("I", (), {"lista": lambda self, q: [
        {"raiz": "04625102", "cnpj": "04625102000110", "razao": "PLATINUM AUTOMOVEIS IMPORTADOS LTDA",
         "fantasias": ["OSTEN GROUP"], "municipio": "SAO PAULO", "ufs": ["SP"], "estab": 10, "porte": "05",
         "cnae": "4511101", "cnae_desc": "Comércio de automóveis"}]})()
    srv = servidor.criar_servidor(base, porta=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
        c.request("GET", "/buscar?q=osten")
        r = json.loads(c.getresponse().read())
        assert r["associada"] is None and r["candidatos"][0]["fantasias"] == ["OSTEN GROUP"]
        c.request("GET", "/buscar?q=serdia")
        assert json.loads(c.getresponse().read())["associada"] == "8"
    finally:
        srv.shutdown()


def test_servidor_so_escuta_local(tmp_path, monkeypatch):
    srv = servidor.criar_servidor(_base(tmp_path, monkeypatch), porta=0)
    try:
        assert srv.server_address[0] == "127.0.0.1"
    finally:
        srv.server_close()


def test_empresa_nova_tem_id_sem_prefixo_da_lista():
    import radar
    d = {"codigo_lista": "NOVA-11222333", "empresa": "NOVA", "segmento": "Indústria", "cnpj": "11222333000181",
         "evidencias": [], "decisor_ou_canal": {}, "alertas": []}
    assert radar.empresa(d, HOJE)["id"] == "NOVA-11222333"


def test_nome_resolvido_pelo_cnpj_publicado_no_site():
    passos = []
    a, cas = servidor.resolver("totvs", "totvs.com", _lista(), CAS, mostrar=lambda t, l: passos.append(t),
                               por_site=lambda d: {"cnpj": "53113791000122", "url": "https://www.totvs.com/privacidade",
                                                   "razao": "TOTVS S.A."},
                               por_agente=lambda m, d: pytest.fail("nao devia chamar o agente"))
    assert cas["cnpj"] == "53113791000122" and cas["origem"].startswith("publicado no site")
    assert "site" in passos[0]


def test_nome_resolvido_pelo_agente_mostra_o_caminho():
    passos = []
    agente = {"raiz": "61486650", "caminho": [{"acao": "maiores_por_cnae", "argumento": "8640202", "motivo": "lider"}],
              "candidato": {"razao": "DIAGNOSTICOS DA AMERICA S.A .", "estab": 988, "cnpj": "61486650000183"},
              "verificacao": {"nome": True, "ramo": True, "porte": True, "aceito": True}}
    a, cas = servidor.resolver("dasa", "dasa.com.br", _lista(), CAS, mostrar=lambda t, l: passos.append((t, l)),
                               por_site=lambda d: None, por_agente=lambda m, d: agente)
    assert cas["cnpj"] == "61486650000183" and a["campos"]["razao_social"].startswith("DIAGNOSTICOS")
    titulo, linhas = passos[0]
    assert "agente" in titulo and any("maiores empresas do CNAE" in l for l in linhas)
