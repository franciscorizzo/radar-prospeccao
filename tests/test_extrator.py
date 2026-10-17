# -*- coding: utf-8 -*-
"""Extrator: o modelo le texto corrido e devolve campo do ICP com trecho literal.

Sem rede e sem gastar: o modelo e trocado por uma funcao que devolve a resposta
pronta. O que se testa aqui e o que o CODIGO faz com a resposta, que e onde mora
a garantia: trecho que nao esta na pagina nao vira campo.
"""
import json

import pytest

import extrator

PAGINA = (
    "=== https://www.exemplo.com.br/sobre ===\n"
    "Somos uma industria fundada em 1982 com mais de 1.200 colaboradores "
    "em 4 fabricas, em SP, MG e RS.\n"
    "=== https://www.exemplo.com.br/carreiras ===\n"
    "Vaga: Analista de Beneficios Pleno - area de Recursos Humanos.\n"
    "Fomos certificados Great Place to Work em 2025.\n"
)


def _resposta(**campos):
    """Monta a resposta do modelo no formato do esquema, com o resto vazio."""
    base = {c: {"encontrado": False, "valor": "", "trecho": ""} for c in extrator.CAMPOS}
    base.update(campos)
    return json.dumps(base, ensure_ascii=False)


def _rodar(resposta_json, pagina=PAGINA):
    return extrator.extrair(pagina, "EXEMPLO S.A.", chamar=lambda sistema, usuario: resposta_json)


def test_campo_com_trecho_literal_entra_com_url_de_origem():
    r = _rodar(_resposta(colaboradores={"encontrado": True, "valor": "1200",
                                        "trecho": "mais de 1.200 colaboradores"}))
    c = r["campos"]["colaboradores"]
    assert c["valor"] == 1200
    assert c["trecho"] == "mais de 1.200 colaboradores"
    assert c["url"] == "https://www.exemplo.com.br/sobre"
    assert c["tipo"] == "extraido"


def test_trecho_que_nao_esta_na_pagina_e_descartado():
    """O modelo citou algo que nao existe: o campo nao entra, e o descarte fica
    registrado. E a defesa contra invencao."""
    r = _rodar(_resposta(colaboradores={"encontrado": True, "valor": "5000",
                                        "trecho": "mais de 5.000 colaboradores"}))
    assert "colaboradores" not in r["campos"]
    assert r["descartados"][0]["campo"] == "colaboradores"


def test_trecho_confere_ignorando_espaco_e_caixa():
    r = _rodar(_resposta(rh_estruturado={"encontrado": True, "valor": "sim",
                                         "trecho": "analista de beneficios   pleno"}))
    assert r["campos"]["rh_estruturado"]["valor"] is True
    assert r["campos"]["rh_estruturado"]["url"] == "https://www.exemplo.com.br/carreiras"


def test_nao_encontrado_nao_vira_campo_nem_descarte():
    r = _rodar(_resposta())
    assert r["campos"] == {} and r["descartados"] == []


@pytest.mark.parametrize("valor,esperado", [
    ("1200", 1200), ("1.200", 1200), ("mais de 1.200", 1200),
    ("cerca de 3 mil", 3000), ("entre 500 e 1000", 500), ("sem numero", None),
])
def test_numero_de_colaboradores(valor, esperado):
    assert extrator.numero(valor) == esperado


def test_sim_nao_vira_booleano():
    r = _rodar(_resposta(multi_localidade={"encontrado": True, "valor": "sim",
                                           "trecho": "em 4 fabricas, em SP, MG e RS"}))
    assert r["campos"]["multi_localidade"]["valor"] is True


def test_texto_grande_demais_e_cortado_e_o_corte_e_declarado():
    """Nao corta em silencio: o resultado diz que cortou."""
    grande = PAGINA + ("x " * (extrator.LIMITE_CARACTERES))
    r = extrator.extrair(grande, "EXEMPLO", chamar=lambda s, u: _resposta())
    assert r["truncado"] is True


def test_recusa_do_modelo_vira_erro_explicito_e_nao_campo_vazio():
    def recusa(sistema, usuario):
        raise extrator.Recusa("refusal")
    r = extrator.extrair(PAGINA, "EXEMPLO", chamar=recusa)
    assert r["erro"].startswith("recusa")
    assert r["campos"] == {}


def test_esquema_e_estrito_e_cobre_todos_os_campos():
    e = extrator.ESQUEMA
    assert e["additionalProperties"] is False
    assert set(e["required"]) == set(extrator.CAMPOS)
    for c in extrator.CAMPOS:
        assert e["properties"][c]["additionalProperties"] is False


def test_html_vira_texto_sem_script_nem_estilo():
    html = "<html><style>.a{}</style><script>var x=1</script><p>Ola&nbsp;mundo</p></html>"
    assert extrator.texto_de_html(html) == "Ola mundo"


@pytest.mark.llm
def test_contra_o_modelo_de_verdade():
    """Chama a API de verdade. Custa centavos. Roda com: pytest -m llm"""
    r = extrator.extrair(PAGINA, "EXEMPLO S.A.")
    assert r.get("erro") is None
    assert r["campos"]["colaboradores"]["valor"] == 1200
    assert r["campos"]["rh_estruturado"]["valor"] is True
    assert r["descartados"] == []


# --- achado nos sites reais: numero do grupo global nao e numero do CNPJ -----

def test_escopo_global_e_registrado_e_nao_confundido_com_brasil():
    """Empresa de grupo estrangeiro: o site diz "9000+ Employees" do grupo no exterior.
    O numero entra, mas marcado como do grupo, nao da empresa brasileira."""
    pagina = "=== https://www.x.com.br/about ===\n27 Countries 9000+ Employees worldwide."
    r = extrator.extrair(pagina, "X BRASIL LTDA", chamar=lambda s, u: _resposta(
        colaboradores={"encontrado": True, "valor": "9000", "trecho": "9000+ Employees", "escopo": "grupo"}))
    c = r["campos"]["colaboradores"]
    assert c["valor"] == 9000 and c["escopo"] == "grupo"


def test_escopo_desconhecido_vira_indefinido():
    r = _rodar(_resposta(colaboradores={"encontrado": True, "valor": "1200",
                                        "trecho": "mais de 1.200 colaboradores", "escopo": "planeta"}))
    assert r["campos"]["colaboradores"]["escopo"] == "indefinido"


def test_esquema_pede_escopo_onde_ele_importa():
    for c in ("colaboradores", "multi_localidade"):
        assert "escopo" in extrator.ESQUEMA["properties"][c]["required"]
    assert "escopo" not in extrator.ESQUEMA["properties"]["rh_estruturado"]["properties"]


# --- modelo local (LM Studio) ----------------------------------------------------

def test_corpo_local_usa_o_mesmo_esquema_estrito():
    c = extrator.corpo_local("s", "u", modelo="qwen2.5-7b-instruct")
    assert c["temperature"] == 0
    assert c["response_format"]["json_schema"]["strict"] is True
    assert c["response_format"]["json_schema"]["schema"] is extrator.ESQUEMA


def test_resposta_local_passa_pela_mesma_conferencia():
    """Trecho inventado pelo modelo local e descartado igual ao do Claude."""
    def postar(url, corpo):
        assert url.endswith("/v1/chat/completions")
        conteudo = _resposta(colaboradores={"encontrado": True, "valor": "5000",
                                            "trecho": "mais de 5.000 colaboradores"})
        return {"model": "qwen2.5-7b-instruct", "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                "choices": [{"finish_reason": "stop", "message": {"content": conteudo}}]}
    r = extrator.extrair(PAGINA, "EXEMPLO", chamar=lambda s, u: extrator.chamar_local(s, u, postar=postar))
    assert "colaboradores" not in r["campos"]
    assert r["descartados"][0]["campo"] == "colaboradores"
    assert r["uso"]["modelo"] == "qwen2.5-7b-instruct"


def test_resposta_local_cortada_e_erro():
    def postar(url, corpo):
        return {"choices": [{"finish_reason": "length", "message": {"content": "{"}}]}
    with pytest.raises(RuntimeError, match="cortada"):
        extrator.chamar_local("s", "u", postar=postar)


def test_modelo_local_so_aceita_endereco_local(monkeypatch):
    monkeypatch.setattr(extrator, "LOCAL_URL", "https://api.algum-lugar.com")
    with pytest.raises(RuntimeError, match="nao e local"):
        extrator.chamar_local("s", "u", postar=lambda u, c: {})



# --- pertinencia: o trecho existe, mas sustenta o campo? -----------------------
#
# Casos reais de 01/10. Os ERRADOS sao do Qwen2.5-7B local; os CERTOS sao do
# Claude nas mesmas paginas. A conferencia tem que derrubar uns e manter os outros.

ERRADOS = [
    ("beneficios", "Vaga: Analista de Beneficios Pleno - area de Recursos Humanos."),
    ("beneficios", "Boreal's HR team includes business partners(BP), talent acquisition"),
    ("sinal_crescimento", "Boreal Showcases Real-World Edge AI Capabilities at COMPUTEX"),
    ("employer_branding", "Boreal – Computadores industriais, computadores embarcados, automacao"),
    ("multi_localidade", "Somos uma industria fundada em 1982 com mais de 1.200 colaboradores em"),
]
CERTOS = [
    ("colaboradores", "27 Countries 9000+ Employees"),
    ("colaboradores", "mais de 1.200 colaboradores"),
    ("rh_estruturado", "Boreal's HR team includes business partners(BP), talent acquisition(TA)"),
    ("rh_estruturado", "Vaga: Analista de Beneficios Pleno - area de Recursos Humanos."),
    ("beneficios", "backed by a collaborative culture and comprehensive benefits."),
    ("employer_branding", "Discover what Borealers say about working at Boreal"),
    ("employer_branding", "Fomos certificados Great Place to Work em 2025."),
    ("multi_localidade", "Matriz +55 51 3000 0004 Filial SP +55 11 3000 0005"),
    ("multi_localidade", "FILIAL Rua das Acacias, 100 sala 1 - Sao Paulo/SP - 01000-000"),
    ("multi_localidade", "em 4 fabricas, em SP, MG e RS"),
]


@pytest.mark.parametrize("campo,trecho", ERRADOS)
def test_trecho_que_nao_sustenta_o_campo_e_derrubado(campo, trecho):
    assert extrator.pertinente(campo, trecho) is False


@pytest.mark.parametrize("campo,trecho", CERTOS)
def test_trecho_que_sustenta_o_campo_passa(campo, trecho):
    assert extrator.pertinente(campo, trecho) is True


def test_escopo_vira_grupo_quando_o_trecho_fala_do_mundo():
    """O Qwen marcou "9000+ Employees" como Brasil. O trecho diz "27 Countries":
    o codigo corrige para grupo, sem depender do julgamento do modelo."""
    assert extrator.escopo_pelo_trecho("27 Countries 9000+ Employees", "brasil") == "grupo"
    assert extrator.escopo_pelo_trecho("mais de 1.200 colaboradores no Brasil", "indefinido") == "indefinido"


def test_extrair_descarta_o_que_nao_e_pertinente_e_diz_por_que():
    pagina = "=== https://x.com.br/ ===\nVaga: Analista de Beneficios Pleno - area de Recursos Humanos."
    r = extrator.extrair(pagina, "X", chamar=lambda s, u: _resposta(
        beneficios={"encontrado": True, "valor": "sim",
                    "trecho": "Vaga: Analista de Beneficios Pleno - area de Recursos Humanos."}))
    assert "beneficios" not in r["campos"]
    assert r["descartados"][0]["motivo"] == "trecho nao sustenta o campo"


# --- auditoria do lote das 306 -------------------------------------------------

def test_trecho_longo_e_descartado():
    """O modelo devolveu paragrafos e blocos de pagina como "trecho". Trecho
    longo prova pouco e carrega nome de pessoa: e por ele que entravam."""
    longo = "mais de 1.200 colaboradores " + "texto " * 80
    pagina = "=== https://x.com.br/ ===\n" + longo
    r = extrator.extrair(pagina, "X", chamar=lambda s, u: _resposta(
        colaboradores={"encontrado": True, "valor": "1200", "trecho": longo.strip()}))
    # Desde a V2 o trecho longo e recortado na parte que sustenta o campo.
    c = r["campos"]["colaboradores"]
    assert c["recortado"] is True and len(c["trecho"]) <= extrator.TRECHO_MAX
    assert "1.200 colaboradores" in c["trecho"]


def test_campo_encontrado_com_valor_descritivo_e_verdadeiro():
    """Bug do lote: "conclui processo de aquisicao" saiu crescimento FALSO,
    porque so valor comecando com "s" contava como sim."""
    pagina = "=== https://x.com.br/ ===\nPadtec conclui processo de aquisicao da LEV Brasil."
    r = extrator.extrair(pagina, "X", chamar=lambda s, u: _resposta(
        sinal_crescimento={"encontrado": True, "valor": "Aquisicao da LEV Brasil em 2026",
                           "trecho": "conclui processo de aquisicao da LEV Brasil"}))
    assert r["campos"]["sinal_crescimento"]["valor"] is True


def test_valor_explicitamente_negativo_continua_falso():
    pagina = "=== https://x.com.br/ ===\nNao ha filiais: operamos apenas em Curitiba."
    r = extrator.extrair(pagina, "X", chamar=lambda s, u: _resposta(
        multi_localidade={"encontrado": True, "valor": "nao", "escopo": "brasil",
                          "trecho": "operamos apenas em Curitiba"}))
    if "multi_localidade" in r["campos"]:
        assert r["campos"]["multi_localidade"]["valor"] is False



# --- nome de pessoa na evidencia (opcao C) ----------------------------------------
#
# O desenho deixa decisor nominal fora do pipeline. O trecho literal e a prova,
# e pode conter nome: cargo fica, nome vira [nome]. URL e ancora (posicao e hash)
# ficam sempre, para reconferir a pagina sem guardar o nome.

def _det(nomes):
    return lambda trecho: [n for n in nomes if n in trecho]


def _extrair_com(pagina, campo, trecho, valor, detector):
    return extrator.extrair(pagina, "X", anonimizar=detector, chamar=lambda s, u: _resposta(
        **{campo: {"encontrado": True, "valor": valor, "trecho": trecho, "escopo": "brasil"}}))


def test_nome_vira_marcador_e_o_cargo_fica():
    t = "Diretora de Recursos Humanos Fulana Exemplo de Tal Teste"
    r = _extrair_com("=== https://x.com.br/ ===\n" + t, "rh_estruturado", t, "sim",
                     _det(["Fulana Exemplo de Tal Teste"]))
    c = r["campos"]["rh_estruturado"]
    assert c["trecho"] == "Diretora de Recursos Humanos [nome]"
    assert c["trecho_mascarado"] is True
    assert "Fulana" not in repr(r)


def test_nome_de_rua_nao_e_mascarado():
    """O Qwen marcou "Rua Jacinto Prado" e "Av. Joao Pereira" como pessoa."""
    t = "Fabrica - Rua Jacinto Prado, 100 - Cidade Exemplo - RS Filial Av. Joao Pereira, 200 - Vila Exemplo"
    r = _extrair_com("=== https://x.com.br/ ===\n" + t, "multi_localidade", t, "sim",
                     _det(["Jacinto Prado", "Joao Pereira"]))
    assert r["campos"]["multi_localidade"]["trecho"] == t
    assert r["campos"]["multi_localidade"]["trecho_mascarado"] is False


def test_detector_fora_do_ar_omite_o_texto_e_guarda_a_ancora():
    """Falha fechada: sem detector, nao se guarda texto que pode ter nome."""
    def fora(trecho):
        raise ConnectionRefusedError("modelo local parado")
    t = "mais de 1.200 colaboradores"
    r = _extrair_com(PAGINA, "colaboradores", t, "1200", fora)
    c = r["campos"]["colaboradores"]
    assert c["trecho"] is None and c["trecho_omitido"].startswith("detector")
    assert c["ancora"]["sha256"] and c["url"] == "https://www.exemplo.com.br/sobre"


def test_ancora_reconfere_a_pagina_sem_guardar_o_nome():
    t = "Bénédicte Exemplaire VP Executivo de Recursos Humanos"
    pagina = "=== https://x.com.br/lideranca ===\nLideranca: " + t + ". Outros."
    r = _extrair_com(pagina, "rh_estruturado", t, "sim", _det(["Bénédicte Exemplaire"]))
    ancora = r["campos"]["rh_estruturado"]["ancora"]
    corpo = pagina.split("===\n", 1)[1]
    assert extrator.confere_ancora(corpo, ancora) is True
    assert extrator.confere_ancora(corpo.replace("Exemplaire", "Outra"), ancora) is False


def test_prompt_pede_trecho_sem_nome_de_pessoa():
    assert "sem nome de pessoa" in extrator.SISTEMA


# --- o que fica guardado ---------------------------------------------------------

def test_descartado_nao_guarda_o_texto_do_trecho():
    """O trecho descartado nao passa pelo detector de nomes: guardar o texto dele
    reabriria a porta que a mascara fecha. Fica o tamanho e o motivo."""
    pagina = "=== https://x.com.br/ ===\nFale com Maria Souza, Analista de Beneficios."
    for item in ({"valor": "sim", "trecho": "Fale com Maria Souza, Analista de Beneficios."},
                 {"valor": "sim", "trecho": "Maria Souza lidera o RH desde 2010"}):
        r = extrator.extrair(pagina, "X", chamar=lambda s, u: _resposta(
            beneficios={"encontrado": True, **item}))
        assert "Maria" not in repr(r["descartados"]), r["descartados"]
        assert r["descartados"][0]["tamanho"] == len(item["trecho"])


def test_fonte_nomeia_o_modelo_que_respondeu():
    """O lote local saiu com "lido por claude-opus-5-5": a fonte mentia."""
    uso = {"modelo": "/modelos/Qwen3.5-9B-GGUF/Qwen3.5-9B-Q4_K_M.gguf"}
    r = extrator.extrair(PAGINA, "X", anonimizar=lambda t: [], chamar=lambda s, u: (_resposta(
        colaboradores={"encontrado": True, "valor": "1200", "trecho": "mais de 1.200 colaboradores"}),
        uso))
    assert r["campos"]["colaboradores"]["fonte"] == "site da empresa, lido por Qwen3.5-9B-Q4_K_M"


def test_texto_que_estoura_o_contexto_e_reenviado_pela_metade():
    """O modelo local recusou com 400 paginas de 46 mil tokens contra 32 mil de contexto."""
    import urllib.error
    tamanhos = []

    def chamar(sistema, usuario):
        tamanhos.append(len(usuario))
        if len(tamanhos) == 1:
            raise urllib.error.HTTPError("http://llm/v1", 400, "Bad Request", {}, None)
        return _resposta(colaboradores={"encontrado": True, "valor": "1200",
                                        "trecho": "mais de 1.200 colaboradores"})

    r = extrator.extrair(PAGINA * 3, "X", chamar=chamar, anonimizar=lambda t: [])
    assert len(tamanhos) == 2 and tamanhos[1] < tamanhos[0]
    assert r["truncado"] is True and r["campos"]["colaboradores"]["valor"] == 1200


def test_erro_que_nao_e_400_nao_e_mascarado_por_reenvio():
    import urllib.error

    def chamar(sistema, usuario):
        raise urllib.error.HTTPError("http://llm/v1", 500, "erro", {}, None)

    with pytest.raises(urllib.error.HTTPError):
        extrator.extrair(PAGINA, "X", chamar=chamar, anonimizar=lambda t: [])


def test_valor_que_nao_confere_com_o_trecho_vem_do_trecho():
    """O modelo devolveu 3 para "our 3,000+ employees worldwide": o trecho e o
    texto conferido na pagina, o valor do modelo nao."""
    pagina = "=== https://x.com/ ===\nWe are proud of our 3,000+ employees worldwide"
    r = extrator.extrair(pagina, "X", anonimizar=lambda t: [], chamar=lambda s, u: _resposta(
        colaboradores={"encontrado": True, "valor": "3", "trecho": "our 3,000+ employees worldwide",
                       "escopo": "grupo"}))
    assert r["campos"]["colaboradores"]["valor"] == 3000


@pytest.mark.parametrize("trecho,esperado", [
    ("RH Tel.: (11) 3000-0001 / (11) 3000-0002 E-mail: rh@fabrica.exemplo",
     "RH Tel.: [telefone] / [telefone] E-mail: rh@fabrica.exemplo"),
    ("fale com joao.silva@empresa.com.br ou +55 (19) 3000-0003", "fale com [e-mail] ou [telefone]"),
    ("envie CV para talentos@comandos.exemplo", "envie CV para talentos@comandos.exemplo"),
    ("mais de 1.200 colaboradores desde 2010", "mais de 1.200 colaboradores desde 2010"),
])
def test_telefone_e_email_pessoal_sao_mascarados_e_caixa_de_funcao_fica(trecho, esperado):
    assert extrator.mascarar_contato(trecho) == esperado


def test_extrair_mascara_contato_no_trecho_gravado():
    t = "Trabalhe conosco: joao.silva@exemplo.com.br, Recursos Humanos"
    pagina = "=== https://x.com.br/ ===\n" + t
    r = extrator.extrair(pagina, "X", anonimizar=lambda t: [], chamar=lambda s, u: _resposta(
        rh_estruturado={"encontrado": True, "valor": "sim", "trecho": t}))
    c = r["campos"]["rh_estruturado"]
    assert "joao" not in c["trecho"] and c["trecho_mascarado"] is True


# --- trecho longo: recortar em vez de descartar ------------------------------------
#
# 115 dos 225 descartes do lote v2 foram "trecho longo demais". O texto longo
# nao e guardado (privacidade), entao o recorte acontece na hora: a menor parte
# que ainda sustenta o campo, e que continua tendo de existir na pagina.

_LONGO_RH = ("Trabalhe conosco. Nossa empresa valoriza as pessoas e acredita no desenvolvimento continuo. "
             "Ha mais de quarenta anos atendemos clientes no Brasil inteiro com solucoes de automacao. "
             "Nossa area de Recursos Humanos cuida do recrutamento e da selecao. "
             "Envie seu curriculo e acompanhe as vagas abertas em nossas unidades de todo o pais, "
             "sempre com transparencia e respeito.")


def test_recorta_a_frase_que_sustenta_o_campo():
    r = extrator.recortar(_LONGO_RH, "rh_estruturado")
    assert r == "Nossa area de Recursos Humanos cuida do recrutamento e da selecao."


def test_recorta_lista_sem_pontuacao_em_volta_do_termo():
    blob = ("Menu Inicio Empresa Produtos Solucoes Noticias Contato Carreiras " * 6 +
            "Beneficios Vale Alimentacao Plano de Saude Plano Odontologico Seguro de Vida " +
            "Rodape Politica de Privacidade Termos de Uso Mapa do Site " * 6)
    r = extrator.recortar(blob, "beneficios")
    assert r is not None and len(r) <= extrator.TRECHO_MAX
    assert "Plano de Saude" in r and r in blob


def test_recorte_de_colaboradores_leva_o_numero():
    t = ("Fundada em 1975, a empresa e referencia em energia. " * 4 +
         "Hoje contamos com mais de 1.200 colaboradores em tres fabricas. " + "Qualidade e nosso lema. " * 8)
    r = extrator.recortar(t, "colaboradores")
    assert "1.200 colaboradores" in r and len(r) <= extrator.TRECHO_MAX


def test_trecho_longo_sem_nada_pertinente_continua_descartado():
    assert extrator.recortar("Qualidade e nosso lema. " * 30, "rh_estruturado") is None


def test_extrair_aproveita_o_recorte_e_marca():
    pagina = "=== https://x.com.br/carreiras ===\n" + _LONGO_RH
    r = extrator.extrair(pagina, "X", anonimizar=lambda t: [], chamar=lambda s, u: _resposta(
        rh_estruturado={"encontrado": True, "valor": "sim", "trecho": _LONGO_RH}))
    c = r["campos"]["rh_estruturado"]
    assert c["trecho"].startswith("Nossa area de Recursos Humanos") and c["recortado"] is True
    assert r["descartados"] == []
    assert extrator.confere_ancora(pagina.split("===\n", 1)[1], c["ancora"])


# --- auditoria dos recortes do lote v3 (empresas fora da amostra de teste) ---------

@pytest.mark.parametrize("trecho,esperado", [
    ("rh@papeis.exemplo ou whatsapp: 9 9000 0000 .", "rh@papeis.exemplo ou whatsapp: [telefone] ."),
    ("Ligue 99000-0000 para falar com o RH", "Ligue [telefone] para falar com o RH"),
    ("Em 2018 2019 e 2020 crescemos", "Em 2018 2019 e 2020 crescemos"),
    ("CEP 01.234-560 e 3285 m2", "CEP 01.234-560 e 3285 m2"),
    ("2019-2021 Expansao global para mais de 60 paises", "2019-2021 Expansao global para mais de 60 paises"),
])
def test_telefone_sem_ddd_tambem_e_mascarado(trecho, esperado):
    assert extrator.mascarar_contato(trecho) == esperado


def test_texto_de_exemplo_nao_sustenta_campo():
    assert not extrator.pertinente(
        "rh_estruturado", "Oportunidade 3 Recursos Humanos Lorem ipsum dolor sit amet, consectetur adipiscing")


@pytest.mark.parametrize("trecho,ok", [
    ("Great Place to Work® é uma consultoria global que apoia organizações", False),
    ("Empresa certificada Great Place to Work com foco no bem-estar", True),
    ("Somos GPTW pelo terceiro ano", False),
    ("Fomos reconhecidos pelo GPTW como uma das melhores empresas para trabalhar", True),
    ("Porque trabalhar na Nansen?", True),
])
def test_citar_o_gptw_nao_e_ter_o_selo(trecho, ok):
    assert extrator.pertinente("employer_branding", trecho) is ok


@pytest.mark.parametrize("valor,esperado", [("nao", False), ("não", False), ("no", False), ("false", False),
                                            ("nao informado", False), ("sim", True), ("yes", True),
                                            ("conclui processo de aquisicao", True), ("nanotecnologia", True)])
def test_sim_reconhece_o_negativo(valor, esperado):
    """Um caractere de controle no lugar de \\b fazia _sim devolver True para tudo, "nao" inclusive."""
    assert extrator._sim(valor) is esperado
