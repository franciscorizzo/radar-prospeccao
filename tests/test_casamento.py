# -*- coding: utf-8 -*-
"""Casar o nome que uma fonte publica com a razao social da Receita.

Casos tirados da primeira prova, com 8 lista de exemplo (ficticia): 5 certas, 1
errada (APB casou com CMV) e 2 nao encontradas por abreviacao.
"""
from receita_base import casamento as c


def test_tokens_tira_acento_caixa_e_palavra_societaria():
    assert c.tokens("ALTUS SISTEMAS DE AUTOMAÇÃO S/A") == ["altus", "sistemas", "automacao"]
    assert c.tokens("ABB AUTOMACAO LTDA") == ["abb", "automacao"]


def test_abreviacao_casa_como_prefixo():
    """A lista de origem escreve IND, EQUIP, INDUST; a Receita pode escrever por extenso."""
    a = c.tokens("ALTRA IND MOTION DO BR EQUIP INDUST LTDA")
    b = c.tokens("ALTRA INDUSTRIAL MOTION DO BRASIL EQUIPAMENTOS INDUSTRIAIS LTDA")
    assert c.similaridade(a, b) == 1.0


def test_nome_distinto_nao_casa_mesmo_com_palavra_comum():
    """O falso positivo da primeira prova: so 'automacao' em comum."""
    assert c.similaridade(c.tokens("APB AUTOMACAO S/A"), c.tokens("CMV AUTOMACAO S/A.")) < 1.0


def _cand(cnpj, nome, mun, uf):
    return {"cnpj": cnpj, "razao_social": nome, "municipio": mun, "uf": uf}


def test_um_candidato_com_nome_e_cidade_e_confiavel():
    r = c.decidir("ABB AUTOMACAO LTDA", "Sorocaba", "SP",
                  [_cand("33449965000115", "ABB AUTOMACAO LTDA", "SOROCABA", "SP")])
    assert r["status"] == "confiavel" and r["cnpj"] == "33449965000115"


def test_cidade_batendo_nao_salva_nome_errado():
    r = c.decidir("APB AUTOMACAO S/A", "Sao Paulo", "SP",
                  [_cand("07813996000101", "CMV AUTOMACAO S/A.", "SAO PAULO", "SP")])
    assert r["status"] == "nao_encontrado"


def test_nome_certo_em_outra_cidade_e_provavel():
    """A lista de origem pode publicar o endereco de uma filial."""
    r = c.decidir("BCM ENGENHARIA LTDA", "Canoas", "RS",
                  [_cand("87237830000115", "BCM ENGENHARIA LTDA", "PORTO ALEGRE", "RS")])
    assert r["status"] == "provavel"


def test_dois_nomes_iguais_na_mesma_cidade_e_ambiguo_e_nao_chute():
    r = c.decidir("ALFA TEC LTDA", "Sao Paulo", "SP", [
        _cand("11111111000111", "ALFA TEC LTDA", "SAO PAULO", "SP"),
        _cand("22222222000122", "ALFA TEC LTDA", "SAO PAULO", "SP")])
    assert r["status"] == "ambiguo" and r.get("cnpj") is None


def test_consulta_recupera_por_prefixo_curto_de_cada_palavra():
    """A consulta so RECUPERA candidatos, com prefixo de 3 letras, para pegar
    abreviacao que pula letras ("maqs" -> "maq" -> "maquinas"). Quem decide e
    decidir(): o teste do APB contra CMV continua valendo la."""
    q = c.consulta("APB AUTOMACAO S/A")
    prefixos = [p["prefix"]["razao_social"] for p in q["bool"]["should"] if "prefix" in p]
    assert prefixos == ["apb", "aut"]
    assert q["bool"]["minimum_should_match"] == 2


# --- casos da medicao nas 323 associadas (v2 -> v3) --------------------------

def test_abreviacao_que_nao_e_prefixo_casa_por_subsequencia():
    """INDS, MAQS, ELETROMETALURGS: a abreviacao pula letras."""
    a = c.tokens("LORENZETTI S/A INDS BRAS ELETROMETALURGS")
    b = c.tokens("LORENZETTI S.A. INDUSTRIAS BRASILEIRAS ELETROMETALURGICAS")
    assert c.similaridade(a, b) == 1.0


def test_subsequencia_nao_vira_coringa():
    """Precisa comecar pelas mesmas duas letras: APB nao e AUTOMACAO."""
    assert c.similaridade(["apb"], ["automacao"]) == 0.0


def test_siglas_pontuadas_viram_uma_palavra():
    assert c.tokens("J.M. FONTANA & CIA LTDA") == ["jm", "fontana"]
    assert c.tokens("A/V SOLUCOES") == ["av", "solucoes"]


def test_nome_de_uma_palavra_so_prefere_quem_nao_sobra_palavra():
    """HARTING casou com HARTING FASHION na v2. Havendo HARTING sem sobra, e ele."""
    r = c.decidir("HARTING LTDA", "Sao Paulo", "SP", [
        _cand("11111111000111", "HARTING FASHION LTDA", "SAO PAULO", "SP"),
        _cand("22222222000122", "HARTING LTDA", "JUNDIAI", "SP")])
    assert r.get("cnpj") == "22222222000122"


def test_nome_de_uma_palavra_com_sobra_nao_e_confiavel():
    """Uma palavra distintiva so, e a Receita tem mais: no maximo provavel."""
    r = c.decidir("HARTING LTDA", "Sao Paulo", "SP",
                  [_cand("11111111000111", "HARTING FASHION LTDA", "SAO PAULO", "SP")])
    assert r["status"] != "confiavel"


def test_marca_depois_do_travessao_e_tentada_sem_ela():
    assert c.variantes("LEGRAND BRASIL LTDA \u2013 GL") == ["LEGRAND BRASIL LTDA \u2013 GL", "LEGRAND BRASIL LTDA"]
    assert c.variantes("ABB AUTOMACAO LTDA") == ["ABB AUTOMACAO LTDA"]


# --- erros novos da v3, medidos nas 323 associadas ---------------------------

def test_marca_nao_pode_ser_a_palavra_que_falta():
    """VOICEINTERACTION casou com BROTHERTEC na v3: a tolerancia de uma palavra
    faltando derrubou justo a marca."""
    r = c.decidir("VOICEINTERACTION DO BR – SERV DE TI", "Lisboa", "XX",
                  [_cand("11111111000111", "BROTHERTEC SERVICOS DE TI LTDA", "SAO PAULO", "SP")])
    assert r["status"] == "nao_encontrado"


def test_sigla_de_duas_letras_nao_casa_como_prefixo():
    """S&C virou "sc" e casou com SCHNEIDER na v3."""
    assert c.similaridade(c.tokens("S&C ELECTRIC DO BRASIL LTDA"),
                          c.tokens("SCHNEIDER ELECTRIC BRASIL LTDA")) < 1.0
    assert c.similaridade(c.tokens("S&C ELECTRIC DO BRASIL LTDA"),
                          c.tokens("S & C ELECTRIC DO BRASIL LTDA")) == 1.0


def test_marca_curta_so_casa_exata():
    """ITB casou com ITBF na v3."""
    r = c.decidir("ITB EQUIPAMENTOS ELETRICOS LTDA", "Birigui", "SP",
                  [_cand("11111111000111", "ITBF COMERCIO E REPARACAO DE EQUIPAMENTOS ELETRICOS LTDA",
                         "SAO PAULO", "SP")])
    assert r["status"] == "nao_encontrado"


def test_marca_com_tolerancia_continua_valendo_para_o_resto():
    """INSTRAMED: a marca casa, 'medica' e 'medico' tem o mesmo radical."""
    r = c.decidir("INSTRAMED IND MEDICA HOSPITALAR LTDA", "Porto Alegre", "RS", [
        _cand("11111111000111", "ALRA MEDICAL IND E COMERCIO DE PRODUTOS HOSPITALARES LTDA", "PORTO ALEGRE", "RS"),
        _cand("22222222000122", "INSTRAMED INDUSTRIA MEDICO HOSPITALAR LTDA", "PORTO ALEGRE", "RS")])
    assert r.get("cnpj") == "22222222000122"


# --- erros da v4: o radical de 5 letras casou marca com marca -----------------

def test_radical_nao_vale_para_a_marca():
    """SIEMENS ficou ambiguo com SIEMEX na v4."""
    r = c.decidir("SIEMENS BRASIL LTDA", "Sao Paulo", "SP", [
        _cand("11111111000111", "SIEMEX BRASIL S/A", "SAO PAULO", "SP"),
        _cand("22222222000122", "SIEMENS BRASIL LTDA", "SAO PAULO", "SP")])
    assert r["status"] == "confiavel" and r["cnpj"] == "22222222000122"


def test_marca_identica_ganha_de_marca_que_comeca_igual():
    """DIGITRO e prefixo de DIGITRONIX: os dois casam, so um e identico."""
    r = c.decidir("DIGITRO TECNOLOGIA S/A", "Florianopolis", "SC", [
        _cand("11111111000111", "DIGITRONIX TECNOLOGIA LTDA", "FLORIANOPOLIS", "SC"),
        _cand("22222222000122", "DIGITRO TECNOLOGIA S.A.", "FLORIANOPOLIS", "SC")])
    assert r["cnpj"] == "22222222000122"


def test_letra_solta_que_e_marca_nao_some():
    assert c.tokens("T SERVICES ENGENHARIA E COMERCIO LTDA")[0] == "t"
    r = c.decidir("T SERVICES ENGENHARIA E COMERCIO LTDA", "Sao Paulo", "SP", [
        _cand("11111111000111", "SERVIT ENGENHARIA E COMERCIO LTDA", "SAO PAULO", "SP"),
        _cand("22222222000122", "T SERVICES ENGENHARIA E COMERCIO LTDA", "SAO PAULO", "SP")])
    assert r["status"] == "confiavel" and r["cnpj"] == "22222222000122"


def test_marca_pula_palavra_generica():
    """Em "FAB PAPELAO TIMBO" a marca e "papelao": "fab" e so fabrica."""
    assert c.marca(c.tokens("S/A FAB PAPELAO TIMBO")) == "papelao"
    r = c.decidir("S/A FAB PAPELAO TIMBO", "Timbo", "SC",
                  [_cand("11111111000111", "S.A FABRICA DE PAPELAO TIMBO", "TIMBO", "SC")])
    assert r["status"] == "confiavel"


# --- erros da v5 ---------------------------------------------------------------

def test_marca_identica_desempata_mas_nao_atropela_sobra():
    """GRUPO MULTI foi para GRUPO FG MULTI SERVICOS na v5, porque "multi" e
    identico la. A certa e GRUPO MULTILASER: nao sobra palavra."""
    r = c.decidir("GRUPO MULTI S/A", "Extrema", "MG", [
        _cand("11111111000111", "GRUPO FG MULTI SERVICOS LTDA", "SAO PAULO", "SP"),
        _cand("22222222000122", "GRUPO MULTILASER S.A.", "SAO PAULO", "SP")])
    assert r["cnpj"] == "22222222000122"


def test_marca_curta_casa_com_palavra_longa_que_ela_abrevia():
    """NAC e abreviacao de NACIONAL; ITB nao e abreviacao de ITBF."""
    r = c.decidir("CENTRO NAC TECN ELE AVANC S/A-CEITEC", "Porto Alegre", "RS", [
        _cand("11111111000111", "CENTRO NACIONAL DE TECNOLOGIA ELETRONICA AVANCADA S.A", "PORTO ALEGRE", "RS")])
    assert r["status"] == "confiavel"
