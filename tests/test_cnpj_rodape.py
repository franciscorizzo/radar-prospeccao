# -*- coding: utf-8 -*-
"""CNPJ achado no texto de uma pagina, com digito verificador conferido.

Numero de 14 digitos aparece em pagina por muitos motivos: telefone colado,
codigo de pedido, CEP com mais coisa. So conta como CNPJ se os dois digitos
verificadores baterem.
"""
from fontes import site


def test_valida_digito_verificador():
    assert site.cnpj_valido("47960950000121") is True      # Magazine Luiza, conferido na Receita
    assert site.cnpj_valido("47960950000122") is False
    assert site.cnpj_valido("11111111111111") is False      # repeticao passa no calculo e nao existe


def test_acha_cnpj_formatado_no_rodape():
    html = "<footer>Magazine Luiza S/A - CNPJ 47.960.950/0001-21 - Franca/SP</footer>"
    assert site.cnpjs_na_pagina(html) == ["47960950000121"]


def test_ignora_numero_que_nao_fecha_o_digito():
    html = "<p>Pedido 47.960.950/0001-22</p><p>Tel 1199999999999</p>"
    assert site.cnpjs_na_pagina(html) == []


def test_acha_sem_pontuacao_e_nao_repete():
    html = "CNPJ: 47960950000121 | cnpj 47.960.950/0001-21"
    assert site.cnpjs_na_pagina(html) == ["47960950000121"]
