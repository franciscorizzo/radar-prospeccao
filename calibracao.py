# -*- coding: utf-8 -*-
"""Retroalimentacao: o que os negocios ganhos e perdidos ensinam ao score.

A aba `Oportunidades_Historico` tem 70 negocios: 28 ganhos, 30 perdidos e 12 em
negociacao. E pouco para treinar modelo, e suficiente para calibrar. Dois usos:

  1. Taxa de vitoria por segmento, que alimenta o criterio "segmento com
     historico de ganho" do score. Muda sozinha quando entram negocios novos.
  2. Relatorio de quanto cada criterio separa ganho de perda (lift), para uma
     pessoa decidir se ajusta peso. O ajuste de peso nao e automatico de
     proposito: com 58 negocios fechados, um peso mexido sozinho seria ruido
     tratado como aprendizado.

Negocio em negociacao fica de fora: ainda nao tem resultado.
"""
from __future__ import annotations

from collections import defaultdict


def fechados(oportunidades: list[dict]) -> list[dict]:
    return [o for o in oportunidades if o["Resultado"] in ("Ganha", "Perdida")]


def taxas_por_segmento(oportunidades: list[dict], segmento_de: dict[str, str]) -> dict[str, float]:
    """Taxa de vitoria por segmento, suavizada (Laplace): (ganhos+1)/(fechados+2).

    A suavizacao evita que um segmento com 1 negocio ganho vire 100%.
    """
    ganhos, total = defaultdict(int), defaultdict(int)
    for o in fechados(oportunidades):
        seg = segmento_de.get(o["ID Empresa"])
        if seg is None:
            continue
        total[seg] += 1
        ganhos[seg] += o["Resultado"] == "Ganha"
    return {s: (ganhos[s] + 1) / (total[s] + 2) for s in total}


def auc(pontos_ganhos: list[float], pontos_perdidos: list[float]) -> float:
    """Probabilidade de um negocio ganho ter score maior que um perdido.

    0,5 e moeda; 1,0 separa perfeitamente. Empate conta meio.
    """
    if not pontos_ganhos or not pontos_perdidos:
        return float("nan")
    soma = 0.0
    for g in pontos_ganhos:
        for p in pontos_perdidos:
            soma += 1.0 if g > p else 0.5 if g == p else 0.0
    return soma / (len(pontos_ganhos) * len(pontos_perdidos))


def lift_por_criterio(oportunidades: list[dict], favoravel: dict[str, dict[str, bool]]) -> dict[str, dict]:
    """Para cada criterio: taxa de vitoria quando favoravel e quando nao.

    `favoravel[criterio][id_empresa]` diz se a empresa atende o criterio.
    """
    saida = {}
    fech = fechados(oportunidades)
    for criterio, mapa in favoravel.items():
        com = [o for o in fech if mapa.get(o["ID Empresa"]) is True]
        sem = [o for o in fech if mapa.get(o["ID Empresa"]) is False]
        tx = lambda xs: (sum(o["Resultado"] == "Ganha" for o in xs) / len(xs)) if xs else None
        saida[criterio] = {"com": tx(com), "sem": tx(sem), "n_com": len(com), "n_sem": len(sem)}
    return saida


if __name__ == "__main__":
    # python -m calibracao: o que o historico do cliente diz hoje, para uma pessoa decidir.
    import base_exemplo

    prospects = {p["ID Empresa"]: p for p in base_exemplo.tabela("Prospects")}
    ops = base_exemplo.tabela("Oportunidades_Historico")
    fech = fechados(ops)
    print(f"{len(ops)} negocios, {len(fech)} fechados "
          f"({sum(o['Resultado'] == 'Ganha' for o in fech)} ganhos)\n")
    print("Taxa de vitoria por segmento, suavizada (entra no score):")
    for seg, t in sorted(taxas_por_segmento(ops, {k: v["Segmento"] for k, v in prospects.items()}).items(),
                         key=lambda x: -x[1]):
        print(f"  {seg:24} {t:.0%}")
    favoravel = {
        "porte 200 a 5.000": {k: 200 <= int(v["Colaboradores"]) <= 5000 for k, v in prospects.items()},
        "RH estruturado": {k: v["RH estruturado"] == "Sim" for k, v in prospects.items()},
        "multi-regiao": {k: v["Multi-região"] == "Sim" for k, v in prospects.items()},
        "crescimento alto": {k: v["Sinal crescimento"] == "Alto" for k, v in prospects.items()},
        "employer branding alto": {k: v["Employer branding"] == "Alto" for k, v in prospects.items()},
        "renovacao em ate 6 meses": {k: v["Renovação provável"] in ("0-3 meses", "4-6 meses")
                                     for k, v in prospects.items()},
    }
    print("\nQuanto cada criterio separa ganho de perda (nao muda peso sozinho):")
    for crit, l in lift_por_criterio(ops, favoravel).items():
        print(f"  {crit:26} ganha {l['com']:.0%} com (n={l['n_com']}) x {l['sem']:.0%} sem (n={l['n_sem']})")
