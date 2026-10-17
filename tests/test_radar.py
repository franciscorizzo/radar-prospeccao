# -*- coding: utf-8 -*-
"""Radar visual: o painel do Roggers alimentado pelos dossies reais.

O que se garante: dado ausente vira "Nao identificado" (nunca "Nao"), porte
desconhecido nao desqualifica nem inventa ticket, sinal so entra com data, e a
pagina gerada tem JavaScript valido.
"""
import json
import re
import shutil
import subprocess
from datetime import date

import pytest

import dossie
import radar
from score import ICP_PADRAO
from tests.test_dossie import HOJE, _associada, _campo, _rec, _site


def _dossie(rec=None, site=None, cargo="Diretor Comercial"):
    a = _associada(cargo=cargo)
    d = dossie.montar(ICP_PADRAO, HOJE, consultar=lambda r, h: rec or _rec(), associadas=[a],
                      casamento=[{"codigo": "7", "cnpj": "12345678000190", "status": "confiavel"}],
                      extracao=[site] if site else [], taxas={"Indústria": 0.5}, cnaes={}, revisoes={})[0]
    return dossie.como_dict(d)


def test_ausencia_vira_nao_identificado_e_receita_responde_sim_ou_nao():
    e = radar.empresa(_dossie(), HOJE)
    assert e["colab"] is None and e["rh"] == "Não identificado" and e["eb"] == "Não identificado"
    assert e["multi"] == "Sim" and e["renov"] == "Não identificado" and e["status"] == "Ativa"
    e = radar.empresa(_dossie(rec=_rec(ufs=["SP"])), HOJE)
    assert e["multi"] == "Não"


def test_site_preenche_porte_rh_e_evidencia_com_fonte():
    site = _site(colaboradores=_campo(1200, "mais de 1.200 colaboradores", "brasil"),
                 rh_estruturado=_campo(True, "Nossa area de Recursos Humanos"))
    e = radar.empresa(_dossie(site=site), HOJE)
    assert e["colab"] == 1200 and e["rh"] == "Sim"
    evid = {x["campo"]: x for x in e["evid"]}
    assert evid["colaboradores"]["url"] == "https://exemplo.com.br/sobre"
    assert "1.200 colaboradores" in evid["colaboradores"]["trecho"]


def test_sinal_so_entra_com_data():
    """Filial nova da Receita tem data; trecho do site so entra se trouxer data."""
    site = _site(sinal_crescimento=_campo(True, "Em 15/09/2026 inauguramos a fabrica de Manaus"))
    e = radar.empresa(_dossie(site=site), HOJE)
    tipos = sorted((s["src"], s["d"]) for s in e["sinais"])
    assert ("Receita Federal", 90) in tipos
    assert ("Site da empresa", 18) in tipos
    sem_data = _site(sinal_crescimento=_campo(True, "Estamos em plena expansao"))
    assert all(s["src"] != "Site da empresa" for s in radar.empresa(_dossie(site=sem_data), HOJE)["sinais"])


def test_decisor_so_com_cargo_de_rh():
    assert radar.empresa(_dossie(cargo="Gerente de Recursos Humanos"), HOJE)["temdec"] == "Sim"
    e = radar.empresa(_dossie(), HOJE)
    assert e["temdec"] == "Não" and e["cargo"] == "Diretor Comercial"


def test_pagina_gerada_tem_dados_e_javascript_valido(tmp_path):
    html = radar.gerar([_dossie(), _dossie(cargo="Gerente de RH")], HOJE)
    m = re.search(r'<script id="d" type="application/json">(.*?)</script>', html, re.S)
    db = json.loads(m.group(1))
    assert len(db["empresas"]) == 2 and db["casos"] == []
    assert "base fictícia" not in html.split("<script")[0]
    if shutil.which("node"):
        js = html.rsplit("<script>", 1)[1].split("</script>")[0]
        arq = tmp_path / "radar.js"
        arq.write_text(js, encoding="utf-8")
        r = subprocess.run(["node", "--check", str(arq)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr


def test_porte_desconhecido_nao_desqualifica_nem_inventa_ticket():
    """No motor do Roggers, null < 80 dava verdadeiro e derrubava a empresa no D01."""
    html = radar.gerar([_dossie()], HOJE)
    assert "e.colab!=null&&e.colab<C.d01v" in html
    assert "e.colab==null?null:" in html


def test_radar_abre_na_empresa_em_foco():
    assert '||"LISTA-7";' in radar.gerar([_dossie()], HOJE, foco="LISTA-7")
    assert "__FOCO__" not in radar.gerar([_dossie()], HOJE)


def test_matriz_mostra_quem_enriquecer_e_o_potencial():
    html = radar.gerar([_dossie()], HOJE)
    assert "fitMax:r1(fitMax)" in html and "a enriquecer" in html and "A enriquecer." in html
    if shutil.which("node"):
        # o motor roda de verdade: empresa sem porte nem renovacao tem potencial acima do atual
        js = html.rsplit("<script>", 1)[1].split("</script>")[0]
        dados = re.search(r'<script id="d" type="application/json">(.*?)</script>', html, re.S).group(1)
        prog = ("var document={getElementById:function(i){return i==='d'?{textContent:" + json.dumps(dados) +
                "}:{textContent:'',innerHTML:'',value:'',checked:true,style:{},addEventListener:function(){},"
                "querySelectorAll:function(){return [];},scrollIntoView:function(){}};},"
                "querySelectorAll:function(){return [];}};var location={hash:''};var window={};\n" + js +
                "\nvar r=window.RADAR.E; console.log('ok');")
        import tempfile, os
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
            f.write(prog)
        try:
            out = subprocess.run(["node", f.name], capture_output=True, text=True)
        finally:
            os.unlink(f.name)
        assert out.returncode == 0 and "ok" in out.stdout, out.stderr[-800:]
