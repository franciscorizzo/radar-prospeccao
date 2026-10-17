# -*- coding: utf-8 -*-
"""Da marca ao CNPJ: site, agente de busca e verificacao pelo codigo.

O caso que motivou: "dasa" casava pelo nome com DASA - LTDA, um motel no Amapa.
A Dasa e a DIAGNOSTICOS DA AMERICA S.A., que nenhuma busca por nome alcanca.
"""
import json

import pytest

import resolucao as rs

DIAG = {"raiz": "61486650", "razao": "DIAGNOSTICOS DA AMERICA S.A .", "estab": 988, "porte": "05",
        "cnae": "8640202", "cnae_desc": "Laboratórios clínicos", "ufs": ["SP", "RJ"], "fantasias": ["DASA"]}
MOTEL = {"raiz": "51531868", "razao": "DASA - LTDA", "estab": 1, "porte": "03",
         "cnae": "5510803", "cnae_desc": "Motéis", "ufs": ["AP"], "fantasias": []}
SITE_DASA = "Dasa - Líder em Medicina Diagnóstica no Brasil. Uma rede ampla de laboratórios e milhares de profissionais"


# --- verificacao --------------------------------------------------------------------

@pytest.mark.parametrize("marca,razao,ok", [
    ("dasa", "DIAGNOSTICOS DA AMERICA S.A .", True),     # sigla
    ("totvs", "TOTVS S.A.", True),                      # nome
    ("localiza", "LOCALIZA RENT A CAR SA", True),
    ("dasa", "FLEURY S.A.", False),
    ("magalu", "MAGAZINE LUIZA S/A", False),            # apelido nao e sigla: fica para outro sinal
])
def test_nome_ou_sigla_bate_com_a_marca(marca, razao, ok):
    assert rs.nome_bate(marca, razao, []) is ok


def test_porte_demais_vale_mesmo_com_um_estabelecimento():
    """Conquest One: CONQUESTONE IT SERVICES BR LTDA., porte 05, so a matriz; sem site, o porte decide."""
    c = {"raiz": "01802155", "razao": "CONQUESTONE IT SERVICES BR LTDA.", "estab": 1, "porte": "05",
         "cnae": "6204000", "cnae_desc": "Consultoria em tecnologia da informação", "fantasias": []}
    assert rs.verificar("Conquest One", c, "")["aceito"] is True


def test_nome_fantasia_registrado_tambem_vale():
    assert rs.nome_bate("magalu", "MAGAZINE LUIZA S/A", ["MAGALU"])


def test_verificacao_barra_o_homonimo_pequeno_de_outro_ramo():
    assert rs.verificar("dasa", DIAG, SITE_DASA)["aceito"] is True
    v = rs.verificar("dasa", MOTEL, SITE_DASA)
    assert v["aceito"] is False and v["nome"] is True and v["ramo"] is False and v["porte"] is False


# --- indice: nome fantasia e lista para escolher ---------------------------------------

def _req_falso(empresas, estab):
    """Elasticsearch de mentira: so as consultas que o Indice faz."""
    def req(metodo, caminho, corpo):
        q = corpo["query"]
        if caminho.startswith("/cnpj-empresas"):
            if "term" in q:
                raiz = q["term"]["cnpj_basico"]
                return {"hits": {"hits": [{"_source": e} for e in empresas if e["cnpj_basico"] == raiz]}}
            texto = q["match"]["razao_social"]["query"].upper()
            return {"hits": {"hits": [{"_source": e} for e in empresas if texto in e["razao_social"]]}}
        if "term" in q:
            raiz = q["term"]["cnpj_basico"]
            meus = [e for e in estab if e["cnpj_basico"] == raiz]
            mat = [e for e in meus if e["matriz"]]
            return {"hits": {"total": {"value": len(meus)}}, "aggregations": {
                "ufs": {"buckets": [{"key": u} for u in sorted({e["uf"] for e in meus})]},
                "matriz": {"d": {"hits": {"hits": [{"_source": e} for e in mat]}}},
                "fant": {"hits": {"hits": [{"_source": e} for e in meus]}}}}
        texto = q["match"]["nome_fantasia"]["query"].upper()
        raizes = sorted({e["cnpj_basico"] for e in estab if texto in (e.get("nome_fantasia") or "")})
        return {"aggregations": {"r": {"buckets": [{"key": r} for r in raizes]}}}
    return req


EMPRESAS = [{"cnpj_basico": "04625102", "razao_social": "PLATINUM AUTOMOVEIS IMPORTADOS LTDA", "porte": "05"},
            {"cnpj_basico": "60232960", "razao_social": "SCP PROGENIS OSTEN", "porte": "05"}]
ESTAB = ([{"cnpj_basico": "04625102", "cnpj": "04625102000110", "matriz": True, "uf": "SP", "municipio": "SAO PAULO",
           "cnae_principal": "4511101", "nome_fantasia": "OSTEN GROUP"}]
         + [{"cnpj_basico": "04625102", "cnpj": f"0462510200{i:02d}99", "matriz": False, "uf": "SP",
             "municipio": "SANTOS", "cnae_principal": "4511101", "nome_fantasia": "OSTEN GROUP" if i % 2 else None}
            for i in range(2, 11)]
         + [{"cnpj_basico": "60232960", "cnpj": "60232960000109", "matriz": True, "uf": "MG", "municipio": "BH",
             "cnae_principal": "6810202", "nome_fantasia": None}])


def test_detalhes_traz_o_nome_fantasia_dos_estabelecimentos():
    """O indice nao tem nome_fantasia.keyword: a agregacao por termo voltava vazia, sempre."""
    i = rs.Indice(requisicao=_req_falso(EMPRESAS, ESTAB), cnaes={"4511101": "Comércio de automóveis"})
    d = i.detalhes("04625102")
    assert d["fantasias"] == ["OSTEN GROUP"] and d["municipio"] == "SAO PAULO" and d["estab"] == 10


def test_nome_fantasia_faz_a_concessionaria_passar_na_conferencia():
    i = rs.Indice(requisicao=_req_falso(EMPRESAS, ESTAB), cnaes={})
    assert rs.verificar("osten", i.detalhes("04625102"), "")["aceito"] is True


def test_lista_para_escolher_poe_quem_casa_pelo_nome_fantasia_e_e_maior_no_topo():
    i = rs.Indice(requisicao=_req_falso(EMPRESAS, ESTAB), cnaes={})
    lista = i.lista("osten")
    assert [c["razao"] for c in lista][:1] == ["PLATINUM AUTOMOVEIS IMPORTADOS LTDA"]
    assert {c["raiz"] for c in lista} == {"04625102", "60232960"}


# --- camada 1: CNPJ publicado no site ---------------------------------------------------

def test_cnpj_publicado_no_site_resolve_sem_agente():
    paginas = {"https://www.totvs.com/politica-de-privacidade": "TOTVS S.A., inscrita no CNPJ 53.113.791/0001-22"}
    r = rs.cnpj_no_site("totvs.com", baixar=lambda u: paginas.get(u, ""), ativo=lambda raiz: raiz == "53113791")
    assert r == {"cnpj": "53113791000122", "url": "https://www.totvs.com/politica-de-privacidade"}


def test_cnpj_invalido_ou_inativo_no_site_nao_vale():
    paginas = {"https://www.x.com.br/": "CNPJ 11.111.111/1111-11 e 53.113.791/0001-22"}
    assert rs.cnpj_no_site("x.com.br", baixar=lambda u: paginas.get(u, ""), ativo=lambda raiz: False) is None


# --- camada 2: agente de busca ----------------------------------------------------------

class Indice:
    """Indice falso: so o que as ferramentas precisam."""
    def nome(self, texto):
        return [MOTEL] if "dasa" in texto.lower() else []

    def cnae(self, palavras):
        return [("8640202", "Laboratórios clínicos")] if "laborat" in palavras.lower() else []

    def maiores(self, cnae):
        return [DIAG] if cnae == "8640202" else []

    def detalhes(self, raiz):
        return {"61486650": DIAG, "51531868": MOTEL}.get(raiz)


def _roteiro(*passos):
    passos = list(passos)
    return lambda sistema, usuario: json.dumps(passos.pop(0))


def test_agente_acha_pelo_ramo_e_o_codigo_confere():
    chamar = _roteiro({"acao": "buscar_nome", "argumento": "dasa", "motivo": "comecar pelo nome"},
                      {"acao": "buscar_cnae", "argumento": "laboratorios", "motivo": "o site fala de laboratorios"},
                      {"acao": "maiores_por_cnae", "argumento": "8640202", "motivo": "site diz lider"},
                      {"acao": "responder", "argumento": "61486650", "motivo": "maior rede, sigla DASA"})
    r = rs.agente("dasa", "dasa.com.br", SITE_DASA, Indice(), chamar=chamar)
    assert r["raiz"] == "61486650" and r["verificacao"]["aceito"]
    assert [p["acao"] for p in r["caminho"]] == ["buscar_nome", "buscar_cnae", "maiores_por_cnae", "responder"]


def test_resposta_do_agente_reprovada_cai_no_melhor_candidato_visto():
    """O modelo errou a resposta final; entre o que ele viu, o codigo fica com o que passa."""
    chamar = _roteiro({"acao": "buscar_cnae", "argumento": "laboratorios", "motivo": ""},
                      {"acao": "maiores_por_cnae", "argumento": "8640202", "motivo": ""},
                      {"acao": "buscar_nome", "argumento": "dasa", "motivo": ""},
                      {"acao": "responder", "argumento": "51531868", "motivo": "nome igual"})
    r = rs.agente("dasa", "dasa.com.br", SITE_DASA, Indice(), chamar=chamar)
    assert r["raiz"] == "61486650"


def test_agente_sem_candidato_que_passe_devolve_none():
    chamar = _roteiro({"acao": "buscar_nome", "argumento": "dasa", "motivo": ""},
                      {"acao": "responder", "argumento": "51531868", "motivo": ""})
    r = rs.agente("dasa", "dasa.com.br", SITE_DASA, Indice(), chamar=chamar)
    assert r["raiz"] is None and r["caminho"]


def test_resposta_reprovada_com_nome_compativel_vira_sugestao():
    chamar = _roteiro({"acao": "buscar_nome", "argumento": "dasa", "motivo": ""},
                      {"acao": "responder", "argumento": "51531868", "motivo": ""})
    r = rs.agente("dasa", "dasa.com.br", SITE_DASA, Indice(), chamar=chamar)
    assert r["raiz"] is None and r["sugerido"]["razao"] == "DASA - LTDA"


def test_agente_tem_limite_de_passos():
    chamar = lambda s, u: json.dumps({"acao": "buscar_nome", "argumento": "x", "motivo": ""})
    r = rs.agente("dasa", "dasa.com.br", SITE_DASA, Indice(), chamar=chamar, passos=4)
    assert len(r["caminho"]) == 4


def test_raiz_com_digito_a_menos_usa_o_candidato_ja_visto():
    chamar = _roteiro({"acao": "maiores_por_cnae", "argumento": "8640202", "motivo": ""},
                      {"acao": "detalhes", "argumento": "6148665", "motivo": ""},
                      {"acao": "responder", "argumento": "61486650", "motivo": ""})
    r = rs.agente("dasa", "dasa.com.br", SITE_DASA, Indice(), chamar=chamar)
    assert "DIAGNOSTICOS" in r["caminho"][1]["resultado"] and r["raiz"] == "61486650"
