# -*- coding: utf-8 -*-
"""Lote de extracao: retoma de onde parou, e uma empresa quebrada nao derruba o lote."""
import json

import lote_extracao as lote
from tests.test_extrator import PAGINA, _resposta


def _associada(codigo, dominio="x.com.br"):
    return {"codigo": codigo, "campos": {"razao_social": f"EMPRESA {codigo}", "dominio": dominio}}


def test_pula_quem_ja_foi_feito_e_quem_nao_tem_site(tmp_path):
    entrada = tmp_path / "a.jsonl"
    entrada.write_text("\n".join(json.dumps(a) for a in [
        _associada("1"), _associada("2"), _associada("3", dominio=None)]), encoding="utf-8")
    saida = tmp_path / "s.jsonl"
    saida.write_text(json.dumps({"codigo": "1"}) + "\n", encoding="utf-8")
    n = lote.rodar(entrada, saida, chamar=lambda s, u: _resposta(),
                   paginas=lambda d: (PAGINA, []), log=lambda m: None)
    assert n == 1
    assert [json.loads(l)["codigo"] for l in saida.read_text(encoding="utf-8").splitlines()] == ["1", "2"]


def test_falha_numa_empresa_vira_linha_com_erro(tmp_path):
    def quebra(dominio):
        raise ConnectionError("site fora do ar")
    r = lote.processar(_associada("9"), paginas=quebra)
    assert r["erro"].startswith("ConnectionError")


def test_site_sem_texto_legivel_e_registrado():
    r = lote.processar(_associada("9"), paginas=lambda d: ("", [{"url": "x", "resultado": "Bloqueado"}]))
    assert r["erro"] == "nenhuma pagina legivel"
    assert r["paginas"][0]["resultado"] == "Bloqueado"


def test_normalizar_registro_antigo():
    import lote_extracao
    r = {"campos": {
        "rh_estruturado": {"valor": True, "trecho": "RH Tel.: (11) 3000-0001 E-mail: rh@x.com.br",
                           "trecho_mascarado": False},
        "colaboradores": {"valor": 3, "trecho": "our 3,000+ employees worldwide", "escopo": "grupo"}}}
    n = lote_extracao.normalizar(r)
    assert n["campos"]["rh_estruturado"]["trecho"] == "RH Tel.: [telefone] E-mail: rh@x.com.br"
    assert n["campos"]["rh_estruturado"]["trecho_mascarado"] is True
    assert n["campos"]["colaboradores"]["valor"] == 3000


def test_normalizar_tira_o_que_a_pertinencia_de_hoje_recusa():
    import lote_extracao
    r = {"campos": {"employer_branding": {"valor": True, "trecho": "Great Place to Work e uma consultoria global"},
                    "beneficios": {"valor": True, "trecho": "oferecemos plano de saude e outros beneficios"}}}
    n = lote_extracao.normalizar(r)
    assert list(n["campos"]) == ["beneficios"]
    assert n["descartados"][0]["motivo"] == "trecho nao sustenta o campo (regra posterior)"
    assert "trecho" not in n["descartados"][0]
