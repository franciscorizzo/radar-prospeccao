# -*- coding: utf-8 -*-
"""Score de oportunidade: regra fixa, com justificativa e confianca.

Os 10 criterios e pesos sao os da aba `Regras_Score_Exemplo` do cliente. O modelo
de linguagem nao pontua nada: ele so extrai evidencia (extrator.py). Aqui a
mesma evidencia da sempre o mesmo score, e cada ponto vem com a linha que o
explica e a fonte de onde saiu -- o briefing pede "evidencias que expliquem por
que cada empresa recebeu determinada classificacao".

Duas medidas, separadas de proposito:

  - score: soma dos pontos dos criterios COM evidencia. Criterio sem evidencia
    nao ganha ponto e nao e imputado.
  - confianca: quanto do peso total tinha evidencia para ser avaliado. Score 60
    com confianca 0,9 e outra coisa que score 60 com confianca 0,4. O caso CV-15
    do cliente pede exatamente isso: "sinalizar baixa confianca, nao inventar".

O criterio "segmento com historico de ganho" e a retroalimentacao: a taxa de
vitoria por segmento vem dos negocios ganhos e perdidos (calibracao.py), e
muda quando entram negocios novos.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

CRITERIOS = ("porte", "rh", "multi_regiao", "crescimento", "employer_branding",
             "dor_retencao", "renovacao", "sinal_recente", "decisor", "segmento")


@dataclass(frozen=True)
class Icp:
    """O ICP e entrada, nao constante: pesos, faixa de porte, minimo e cargos de decisor.

    O padrao e o do cliente (icp/exemplo.json). Outro cliente troca o arquivo, nao o codigo.
    """
    nome: str
    pesos: dict
    porte: tuple = (200, 5000)
    porte_minimo: int = 80
    cargos_decisor: tuple = ()

    def __post_init__(self):
        if set(self.pesos) != set(CRITERIOS):
            raise ValueError(f"pesos precisam cobrir exatamente {CRITERIOS}")
        if sum(self.pesos.values()) != 100:
            raise ValueError("pesos precisam somar 100")


def carregar_icp(caminho: str | Path) -> Icp:
    d = json.loads(Path(caminho).read_text(encoding="utf-8"))
    return Icp(d["nome"], d["pesos"], tuple(d["porte"]), d["porte_minimo"],
               tuple(d.get("cargos_decisor", ())))


ICP_PADRAO = carregar_icp(Path(__file__).parent / "icp" / "exemplo.json")
PESOS = ICP_PADRAO.pesos

FAIXAS = ((75, "Prioridade A"), (55, "Prioridade B"), (35, "Prioridade C"), (0, "Baixa prioridade"))
CONFIANCA_MINIMA = 0.6


@dataclass
class Evidencia:
    valor: object
    fonte: str
    tipo: str = "observado"        # observado | extraido | estimado | calibrado
    url: str | None = None
    detalhe: str | None = None


@dataclass
class Resultado:
    empresa: str
    score: float
    confianca: float
    prioridade: str
    desqualificada: str | None
    linhas: list = field(default_factory=list)       # (pontos, criterio, texto, evidencia)
    sem_evidencia: list = field(default_factory=list)
    alertas: list = field(default_factory=list)
    canal: dict | None = None
    teto: float | None = None    # o score se todo criterio sem evidencia viesse favoravel


def _nivel(v) -> str | None:
    if v is None:
        return None
    t = str(v).strip().lower()
    return {"alto": "alto", "alta": "alto", "médio": "medio", "medio": "medio", "média": "medio",
            "media": "medio", "baixo": "baixo", "baixa": "baixo"}.get(t)


def _milhar(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _pontos(criterio: str, valor, taxas_segmento: dict | None, icp: Icp = ICP_PADRAO) -> tuple[float, str]:
    """Pontos e a frase que os explica. Regra fixa, sem estado."""
    PESOS = icp.pesos
    if criterio == "porte":
        n, (de, ate), peso = int(valor), icp.porte, PESOS["porte"]
        if de <= n <= ate:
            return peso, f"{_milhar(n)} colaboradores, dentro da faixa principal do ICP ({_milhar(de)} a {_milhar(ate)})"
        if n > ate:
            return round(peso * 0.7, 1), f"{_milhar(n)} colaboradores, acima da faixa principal"
        return round(peso * 0.4, 1), f"{_milhar(n)} colaboradores, abaixo da faixa principal"
    if criterio in ("rh", "multi_regiao"):
        sim, nao = {"rh": ("RH estruturado", "sem RH estruturado"),
                    "multi_regiao": ("opera em mais de uma regiao", "opera numa regiao so")}[criterio]
        return (PESOS[criterio], sim) if valor else (0, nao)
    if criterio in ("crescimento", "employer_branding", "dor_retencao"):
        n = _nivel(valor)
        fator = {"alto": 1.0, "medio": 0.5}.get(n, 0.0)
        nome = {"crescimento": "sinal de crescimento", "employer_branding": "employer branding",
                "dor_retencao": "dor de retencao"}[criterio]
        return PESOS[criterio] * fator, f"{nome} {n or valor}"
    if criterio == "renovacao":
        p = PESOS["renovacao"] * {"0-3 meses": 1, "4-6 meses": 1, "7-12 meses": 3 / 8}.get(valor, 0)
        return p, f"renovacao provavel em {valor}"
    if criterio == "sinal_recente":
        forca, dias = valor["forca"], valor["dias"]
        base = PESOS["sinal_recente"] * {"alto": 1.0, "medio": 0.6}.get(_nivel(forca), 0)
        decaimento = max(0.0, 1 - dias / 365)
        return round(base * decaimento, 1), f"sinal publico {_nivel(forca)} ha {dias} dias (peso cai com a idade)"
    if criterio == "decisor":
        return {"cargo": (PESOS["decisor"], "decisor identificado pelo cargo"),
                "canal": (PESOS["decisor"] * 0.6, "sem decisor identificado, mas com canal corporativo publico")}.get(
            valor, (0, "sem decisor nem canal"))
    if criterio == "segmento":
        taxa = (taxas_segmento or {}).get(valor)
        if taxa is None:
            return 0, f"segmento {valor} sem historico de negocio"
        maior = max(taxas_segmento.values()) or 1
        return round(PESOS["segmento"] * taxa / maior, 1), f"segmento {valor}: {taxa:.0%} de vitoria no historico"
    raise ValueError(criterio)


def pontuar(empresa: str, ev: dict[str, Evidencia | None], taxas_segmento: dict | None = None,
            ativa: bool = True, canal: dict | None = None,
            fontes_publicas: int | None = None, icp: Icp = ICP_PADRAO) -> Resultado:
    """`fontes_publicas`: quantas fontes publicas independentes sustentam o perfil.

    E uma medida diferente da confianca. A confianca diz quanto do peso foi
    avaliado; esta diz em quantas fontes isso se apoia. A empresa M091 da base
    tem 9 de 10 campos preenchidos e um unico sinal publico -- o caso CV-15 pede
    que isso seja sinalizado.
    """
    linhas, sem, alertas = [], [], []
    avaliado = 0
    for criterio, peso in icp.pesos.items():
        e = ev.get(criterio)
        if e is None or e.valor is None:
            sem.append(criterio)
            continue
        avaliado += peso
        p, texto = _pontos(criterio, e.valor, taxas_segmento, icp)
        linhas.append((p, criterio, texto, e))

    score = round(sum(p for p, *_ in linhas), 1)
    confianca = round(avaliado / 100, 2)

    desq = None
    porte = ev.get("porte")
    if porte is not None and porte.valor is not None and int(porte.valor) < icp.porte_minimo:
        desq = f"D01: menos de {icp.porte_minimo} colaboradores"
    if not ativa:
        desq = "D04: empresa inativa"
    if ev.get("renovacao") is not None and ev["renovacao"].valor == ">12 meses" and score >= 55:
        alertas.append("Renovacao provavel so daqui a mais de 12 meses: bom fit, timing fraco")

    if fontes_publicas is not None and fontes_publicas <= 1:
        alertas.append(f"Evidencia publica escassa: {fontes_publicas} fonte(s) independente(s); "
                       "conferir antes de abordar")
    if confianca < CONFIANCA_MINIMA:
        alertas.append(f"Baixa confianca: so {confianca:.0%} do peso tem evidencia; revisar antes de abordar")
    # Faixa so quando a evidencia decide. Com pouca evidencia, se o que falta
    # pudesse mudar a faixa, ela fica em aberto: ausencia de evidencia nao e
    # sinal negativo. O score e a ordem do ranking continuam valendo.
    teto = round(score + sum(icp.pesos[c] for c in sem), 1)
    faixa = _faixa(score)
    if desq:
        prioridade = "Desqualificada"
    elif confianca < CONFIANCA_MINIMA and _faixa(teto) != faixa:
        prioridade = "Inconclusiva"
    else:
        prioridade = faixa
    return Resultado(empresa, score, confianca, prioridade, desq, linhas, sem, alertas, canal, teto)


def _faixa(score: float) -> str:
    return next(nome for corte, nome in FAIXAS if score >= corte)


def justificativa(r: Resultado) -> str:
    partes = [f"{r.empresa}: {r.prioridade}, score {r.score:g} com {r.confianca:.0%} de confianca"]
    if r.desqualificada:
        partes.append(f"  desqualificada ({r.desqualificada})")
    for p, criterio, texto, e in sorted(r.linhas, key=lambda x: -x[0]):
        origem = e.fonte + (f" <{e.url}>" if e.url else "")
        partes.append(f"  {p:+5.1f}  {texto}  [{e.tipo}: {origem}]")
        if e.detalhe:
            partes.append(f"         {e.detalhe}")
    if r.sem_evidencia:
        partes.append("  sem evidencia: " + ", ".join(r.sem_evidencia)
                      + (f" (com evidencia favoravel, pode chegar a {r.teto:g})" if r.teto is not None else ""))
    for a in r.alertas:
        partes.append(f"  ! {a}")
    if r.canal:
        partes.append(f"  canal: {r.canal.get('descricao')}")
    return "\n".join(partes)
