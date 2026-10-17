# -*- coding: utf-8 -*-
"""Retomada da carga: o que ja foi feito nao e baixado nem relido."""
import pytest

from receita_base import importar


def test_conjunto_de_raizes_ida_e_volta(tmp_path):
    c = {0, 47960950, 99999999}
    importar.salvar_conjunto(tmp_path / "x.bin", c)
    assert importar.ler_conjunto(tmp_path / "x.bin") == c
    assert (tmp_path / "x.bin").stat().st_size == 12   # 4 bytes por raiz


def test_arquivo_concluido_nao_e_baixado_de_novo(tmp_path, monkeypatch):
    monkeypatch.setattr(importar, "pasta", lambda comp: tmp_path)
    importar.salvar_conjunto(tmp_path / "ativas-Estabelecimentos0.zip.bin", {1, 2, 3})
    (tmp_path / "feito-B-Estabelecimentos0.zip").touch()

    def nao_pode_baixar(*a, **k):
        raise AssertionError("baixou de novo um arquivo ja concluido")
    monkeypatch.setattr(importar, "baixar", nao_pode_baixar)

    ativas = importar.passada_b("2026-09", ["Estabelecimentos0.zip"], set(), "idx", {})
    assert ativas == {1, 2, 3}


def test_passada_a_reaproveita_o_conjunto_salvo(tmp_path, monkeypatch):
    monkeypatch.setattr(importar, "pasta", lambda comp: tmp_path)
    importar.salvar_conjunto(tmp_path / "raizes-nao-ei.bin", {10, 20})
    monkeypatch.setattr(importar, "baixar", lambda *a, **k: pytest.fail("releu Empresas"))
    assert importar.passada_a("2026-09", ["Empresas0.zip"]) == {10, 20}
