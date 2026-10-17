# -*- coding: utf-8 -*-
"""Os testes normais nao tocam rede nem modelo.

O extrator procura nome de pessoa nos trechos com o modelo local. Nos testes,
esse detector e trocado por um que nao acha nada; teste que precisa de outro
comportamento passa o seu proprio detector em `anonimizar`.
"""
import pytest

import extrator


@pytest.fixture(autouse=True)
def _sem_detector_de_rede(request, monkeypatch):
    if request.node.get_closest_marker("llm") is None:
        monkeypatch.setattr(extrator, "pessoas_no_trecho", lambda trecho, postar=None: [])
