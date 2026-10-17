# -*- coding: utf-8 -*-
"""Dossie e ranking com dado coletado de verdade.

    python -m dossie [--icp icp/exemplo.json] [--top 10]

Entrada: o ICP (icp/*.json) e uma lista publica de empresas -- hoje o diretorio
de lista de exemplo (ficticia). Para cada empresa da lista, junta:

  - CNPJ, pelo casamento do nome com a base da Receita (receita_base/casamento.py)
  - Receita Federal, no indice local: UFs com estabelecimento ativo, filial
    aberta nos ultimos 24 meses, CNAE principal, porte declarado
  - site da empresa, lido pelo modelo local (extrator.py, lote_extracao.py)
  - cargo do contato institucional publicado na lista de origem

e devolve os seis campos do briefing: empresa, segmento, score, evidencias de
fit, justificativa e decisor ou canal publico. O score e o mesmo motor que roda
sobre a base do cliente (score.py); aqui as evidencias sao observadas, nao dadas.

O que nao entra, de proposito:
  - nome de pessoa: so o cargo (o contato da lista de origem vem com nome; ele e
    descartado na coleta, coleta da lista)
  - telefone e e-mail: o canal e o site e o diretorio, que sao institucionais
  - porte estimado: criterio sem evidencia nao pontua; o porte declarado na
    Receita (ME/EPP) vira alerta, nao numero
"""
from __future__ import annotations

import argparse
import os
import html
import json
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path

import base_exemplo
import calibracao
import cobertura
import revisao
from score import ICP_PADRAO, Evidencia, Icp, carregar_icp, justificativa, pontuar

AQUI = Path(__file__).resolve().parent
# Dados de entrada: dados-exemplo/ (ficticios) ou outra pasta no mesmo formato.
DADOS = Path(os.environ.get("RADAR_DADOS") or AQUI / "dados-exemplo")
LISTA = DADOS
# Arquivos da Receita baixados por receita_base.importar.
RECEITA = AQUI / "dados-receita"
COMPETENCIA = "2026-09"

FONTE_RECEITA = f"Receita Federal, dados abertos CNPJ (competencia {COMPETENCIA})"
FONTE_LISTA = "lista de origem (exemplo ficticio)"
FONTE_HISTORICO = "historico de negocios de exemplo (ficticio), por segmento"

# Divisao CNAE (dois primeiros digitos) -> segmento da base do cliente.
# Comercio atacadista (46) fica sem segmento: a base do cliente nao tem um que
# corresponda, e chamar distribuidor de "Varejo" seria inventar historico.
_SEGMENTOS = [
    (range(5, 10), "Indústria"), (range(10, 34), "Indústria"), (range(35, 36), "Energia"),
    (range(41, 44), "Construção"), (range(47, 48), "Varejo"), (range(49, 54), "Logística"),
    (range(61, 62), "Telecom"), (range(58, 61), "Tecnologia"), (range(62, 64), "Tecnologia"),
    (range(64, 67), "Serviços financeiros"), (range(70, 71), "Consultoria"),
    (range(69, 70), "Serviços empresariais"), (range(71, 83), "Serviços empresariais"),
    (range(85, 86), "Educação"), (range(86, 89), "Saúde"),
]
PORTE_RECEITA = {"01": "Microempresa", "03": "Empresa de Pequeno Porte", "05": "Demais"}


def segmento_por_cnae(cnae: str | None) -> str | None:
    if not cnae:
        return None
    divisao = int(str(cnae)[:2])
    return next((seg for faixa, seg in _SEGMENTOS if divisao in faixa), None)


def _sem_acento(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")


def cargo_de_decisor(cargo: str | None, icp: Icp) -> bool:
    """O cargo e de quem decide beneficio? Palavra inteira, sem acento."""
    if not cargo:
        return False
    t = _sem_acento(cargo)
    return any(re.search(rf"\b{re.escape(_sem_acento(p))}\b", t) for p in icp.cargos_decisor)


# --- Receita ------------------------------------------------------------------------

def receita(cnpj_basico: str, hoje: date, requisicao=None) -> dict:
    """O que a base da Receita no indice local diz sobre a raiz do CNPJ."""
    if requisicao is None:
        from receita_base.indice import requisicao
    corte = date(hoje.year - 2, hoje.month, min(hoje.day, 28)).isoformat()
    r = requisicao("POST", "/cnpj-estabelecimentos/_search", {
        "size": 0,
        "query": {"term": {"cnpj_basico": cnpj_basico}},
        "aggs": {
            "ufs": {"terms": {"field": "uf", "size": 40}},
            "matriz": {"filter": {"term": {"matriz": True}}, "aggs": {"doc": {"top_hits": {
                "size": 1, "_source": ["cnae_principal", "uf", "municipio"]}}}},
            "recentes": {"filter": {"bool": {"filter": [
                {"term": {"matriz": False}},
                {"range": {"data_inicio_atividade": {"gte": corte}}}]}},
                "aggs": {"ultima": {"top_hits": {
                    "size": 1, "sort": [{"data_inicio_atividade": "desc"}],
                    "_source": ["data_inicio_atividade", "uf", "municipio"]}}}},
        },
    })
    a = r["aggregations"]
    matriz = [h["_source"] for h in a["matriz"]["doc"]["hits"]["hits"]]
    ultima = [h["_source"] for h in a["recentes"]["ultima"]["hits"]["hits"]]
    e = requisicao("POST", "/cnpj-empresas/_search", {
        "size": 1, "query": {"term": {"cnpj_basico": cnpj_basico}}})["hits"]["hits"]
    empresa = e[0]["_source"] if e else {}
    return {
        "estabelecimentos": r["hits"]["total"]["value"],
        "ufs": sorted(b["key"] for b in a["ufs"]["buckets"] if b["key"] != "EX"),
        "uf_matriz": matriz[0]["uf"] if matriz else None,
        "cnae_principal": matriz[0]["cnae_principal"] if matriz else None,
        "abertos_24m": a["recentes"]["doc_count"],
        "filial_mais_recente": ultima[0] if ultima else None,
        "razao_social": empresa.get("razao_social"),
        "porte_receita": empresa.get("porte"),
    }


# --- evidencias -------------------------------------------------------------------

_EB_FORTE = re.compile(r"great place|gptw|melhores empresas|top employer|lugares para trabalhar|"
                       r"melhor(es)? lugar(es)? para (se )?trabalhar", re.I)
_NIVEIS = (None, "Médio", "Alto")


def _do_site(campo: dict, valor=None) -> Evidencia:
    return Evidencia(campo["valor"] if valor is None else valor, campo["fonte"], tipo="extraido",
                     url=campo["url"], detalhe=campo.get("trecho") or "(trecho omitido; ancora guardada)")


def evidencias(associada: dict, rec: dict | None, site: dict | None, icp: Icp,
               hoje: date) -> tuple[dict, dict, list[str], set[str]]:
    """Evidencias por criterio, canal, alertas de coleta e fontes que sustentam o fit."""
    campos = (site or {}).get("campos") or {}
    ev, alertas, fontes = {}, [], set()
    # A empresa pode vir de uma lista publica (lista de origem) ou ser digitada por quem usa.
    fonte_lista = associada.get("fonte_lista", FONTE_LISTA)
    url_lista = ((associada.get("proveniencia") or {}).get("razao_social") or {}).get("url")
    site_url = f"https://{associada['campos']['dominio']}" if associada["campos"].get("dominio") else None

    # porte: so numero do site com escopo Brasil (ou sem escopo dito)
    col = campos.get("colaboradores")
    if col and col.get("escopo") in ("brasil", "indefinido"):
        ev["porte"] = _do_site(col)
        fontes.add("site")
    elif col:
        alertas.append(f"Site informa {col['valor']} colaboradores no grupo, nao no Brasil: porte nao pontua")
    if "porte" not in ev and rec and rec.get("porte_receita") in ("01", "03"):
        alertas.append(f"Receita classifica como {PORTE_RECEITA[rec['porte_receita']]} "
                       "(faturamento ate R$ 4,8 mi): porte provavelmente abaixo do ICP")

    # RH: o site, ou o proprio contato institucional ser de RH
    cargo = associada["campos"].get("contato_cargo")
    if "rh_estruturado" in campos:
        ev["rh"] = _do_site(campos["rh_estruturado"])
        fontes.add("site")
    elif cargo_de_decisor(cargo, icp):
        ev["rh"] = Evidencia(True, fonte_lista, url=url_lista, detalhe=f"contato institucional: {cargo}")
        fontes.add("lista")

    if rec and rec["estabelecimentos"]:
        fontes.add("receita")
        ufs = rec["ufs"]
        ev["multi_regiao"] = Evidencia(len(ufs) > 1, FONTE_RECEITA,
                                       detalhe=f"estabelecimentos ativos em {len(ufs)} UF: {', '.join(ufs)}")

    # crescimento: padrao de filiais abertas (Receita), reforcado pelo site
    nivel = 0
    detalhes, origem = [], []
    if rec and rec.get("abertos_24m"):
        nivel = 2 if rec["abertos_24m"] >= 2 else 1
        detalhes.append(f"{rec['abertos_24m']} filial(is) aberta(s) nos ultimos 24 meses")
        origem.append(FONTE_RECEITA)
    s = campos.get("sinal_crescimento")
    anos = [int(x) for x in re.findall(r"\b(?:19|20)\d{2}\b", (s or {}).get("trecho") or "")]
    if s and s["valor"] and anos and max(anos) < hoje.year - 2:
        alertas.append(f"Sinal de crescimento do site e de {max(anos)}: antigo demais, nao pontua")
        s = None
    if s and s["valor"]:
        nivel = min(2, nivel + 1)
        detalhes.append(f"site: \"{s.get('trecho') or 'trecho omitido'}\"")
        origem.append(s["fonte"])
        fontes.add("site")
    if nivel:
        ev["crescimento"] = Evidencia(_NIVEIS[nivel], " + ".join(origem),
                                      url=s["url"] if s and s["valor"] else None, detalhe="; ".join(detalhes))

    eb = campos.get("employer_branding")
    if eb and eb["valor"]:
        ev["employer_branding"] = _do_site(eb, "Alto" if _EB_FORTE.search(eb.get("trecho") or "") else "Médio")
        fontes.add("site")
    dor = campos.get("dor_retencao")
    if dor and dor["valor"]:
        ev["dor_retencao"] = _do_site(dor, "Médio")
        fontes.add("site")

    # sinal datado mais recente: a filial nova, com data da Receita
    f = (rec or {}).get("filial_mais_recente")
    if f:
        dias = (hoje - datetime.strptime(f["data_inicio_atividade"], "%Y-%m-%d").date()).days
        if 0 <= dias <= 365:
            ev["sinal_recente"] = Evidencia({"forca": "Médio", "dias": dias}, FONTE_RECEITA,
                                            detalhe=f"filial aberta em {f['municipio']}/{f['uf']} "
                                                    f"em {f['data_inicio_atividade']}")

    # decisor: cargo de RH publicado, ou o canal institucional
    if url_lista:
        ev["decisor"] = Evidencia("cargo" if cargo_de_decisor(cargo, icp) else "canal", fonte_lista,
                                  url=url_lista, detalhe=f"contato institucional: {cargo or 'sem cargo'}")
    elif site_url:
        ev["decisor"] = Evidencia("canal", "site da empresa", url=site_url, detalhe="canal institucional no site")
    canais = [f"site institucional: https://{associada['campos']['dominio']}"] \
        if associada["campos"].get("dominio") else []
    carreiras = next((p["url"] for p in (site or {}).get("paginas", [])
                      if p.get("resultado") == "ok" and re.search(r"carreir|trabalhe|vagas|career", p["url"], re.I)),
                     None)
    if carreiras:
        canais.append(f"pagina de carreiras: {carreiras}")
    if url_lista:
        canais.append(f"{'lista de origem' if fonte_lista == FONTE_LISTA else 'lista de origem'}: {url_lista}")
    canal = {"cargo": cargo, "descricao": "; ".join(canais)}

    seg = segmento_por_cnae((rec or {}).get("cnae_principal"))
    if seg:
        ev["segmento"] = Evidencia(seg, FONTE_HISTORICO, tipo="calibrado")
    return ev, canal, alertas, fontes


# --- montagem ---------------------------------------------------------------------

def _jsonl(caminho: Path) -> list[dict]:
    if not caminho.exists():
        return []
    return [json.loads(l) for l in caminho.read_text(encoding="utf-8").splitlines() if l.strip()]


def taxas_historico() -> dict:
    prospects = {p["ID Empresa"]: p["Segmento"] for p in base_exemplo.tabela("Prospects")}
    return calibracao.taxas_por_segmento(base_exemplo.tabela("Oportunidades_Historico"), prospects)


def consultar_padrao():
    """Receita de exemplo (CNPJ ficticio) quando houver; senao, o indice local."""
    arq = DADOS / "receita-exemplo.json"
    exemplo = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}
    return lambda raiz, hoje: exemplo[raiz] if raiz in exemplo else receita(raiz, hoje)


def montar(icp: Icp = ICP_PADRAO, hoje: date | None = None, consultar=None,
           associadas: list | None = None, casamento: list | None = None,
           extracao: list | None = None, taxas: dict | None = None, cnaes: dict | None = None,
           revisoes: dict | None = None) -> list[dict]:
    hoje = hoje or date.today()
    consultar = consultar or consultar_padrao()
    # Revisoes do arquivo so na rodada real; com lista injetada (teste), so as injetadas.
    revisoes = revisoes if revisoes is not None else (revisao.carregar() if associadas is None else {})
    associadas = associadas if associadas is not None else _jsonl(LISTA / "lista.jsonl")
    casamento = casamento if casamento is not None else \
        json.loads((LISTA / "casamento.json").read_text(encoding="utf-8"))
    extracao = extracao if extracao is not None else _jsonl(LISTA / "extracao.jsonl")
    taxas = taxas if taxas is not None else taxas_historico()
    cnaes = cnaes if cnaes is not None else _cnaes()
    cnpj_de = {c["codigo"]: c for c in casamento}
    site_de = {e["codigo"]: e for e in extracao}

    saida = []
    for a in associadas:
        codigo = a["codigo"]
        cas = cnpj_de.get(codigo, {})
        if cas.get("status") not in ("confiavel", "provavel", "informado"):
            continue
        rec = consultar(cas["cnpj"][:8], hoje)
        site = site_de.get(codigo)
        ev, canal, alertas, fontes = evidencias(a, rec, site, icp, hoje)
        ev, recusas = revisao.aplicar(codigo, ev, revisoes)
        alertas = recusas + alertas
        r = pontuar(rec.get("razao_social") or a["campos"]["razao_social"], ev, taxas,
                    ativa=bool(rec["estabelecimentos"]), canal=canal,
                    fontes_publicas=len(fontes - {"lista"}), icp=icp)
        if cas["status"] == "provavel":
            r.alertas.append("CNPJ achado por casamento provavel do nome: conferir antes de abordar")
        if site is None:
            r.alertas.append("Site ainda nao lido")
        elif site.get("erro"):
            r.alertas.append(f"Site nao lido: {site['erro']}")
        r.alertas.extend(alertas)
        cnae = rec.get("cnae_principal")
        saida.append({
            "codigo_lista": codigo, "cnpj": cas["cnpj"], "casamento": cas["status"],
            "empresa": r.empresa, "uf_matriz": rec.get("uf_matriz"),
            "segmento": (ev["segmento"].valor if "segmento" in ev else "sem segmento correspondente"),
            "cnae": f"{cnae} {cnaes.get(cnae, '')}".strip() if cnae else None,
            "cobertura_icp": cobertura.pontos(cobertura.criterios(rec, site)),
            "site_lido": bool(site and not site.get("erro")),
            "resultado": r,
        })
    saida.sort(key=lambda d: (d["resultado"].prioridade == "Desqualificada", -d["resultado"].score))
    return saida


def resumo_m1(dossies: list[dict]) -> dict:
    """M1 da Semana 2: pontos de peso do ICP com evidencia, partindo so do nome na lista."""
    pts = sorted(d["cobertura_icp"] for d in dossies)
    lidos = [d["cobertura_icp"] for d in dossies if d["site_lido"]]
    n = len(pts)
    return {"empresas": n, "media": round(sum(pts) / n, 1) if n else 0, "mediana": pts[n // 2] if n else 0,
            "maximo": pts[-1] if n else 0, "teto": cobertura.TETO,
            "com_70_ou_mais": sum(p >= 70 for p in pts),
            "site_lido": len(lidos), "media_com_site": round(sum(lidos) / len(lidos), 1) if lidos else None}


def _cnaes() -> dict:
    from receita_base.leitura import tabela_codigos
    z = RECEITA / COMPETENCIA / "Cnaes.zip"
    if z.exists():
        return tabela_codigos(z)
    ex = DADOS / "cnaes-exemplo.json"
    return json.loads(ex.read_text(encoding="utf-8")) if ex.exists() else {}


def como_dict(d: dict) -> dict:
    r = d["resultado"]
    return {
        **{k: v for k, v in d.items() if k != "resultado"},
        "score": r.score, "confianca": r.confianca, "prioridade": r.prioridade,
        "desqualificada": r.desqualificada,
        "evidencias": [{"pontos": p, "criterio": c, "texto": t, "valor": e.valor, "fonte": e.fonte, "tipo": e.tipo,
                        "url": e.url, "detalhe": e.detalhe} for p, c, t, e in r.linhas],
        "sem_evidencia": r.sem_evidencia, "alertas": r.alertas,
        "decisor_ou_canal": r.canal, "justificativa": justificativa(r),
    }


# --- relatorio --------------------------------------------------------------------

def relatorio_html(dossies: list[dict], icp: Icp, hoje: date) -> str:
    """Ranking navegavel e filtravel, num arquivo so, sem dependencia externa."""
    e = html.escape
    linhas = []
    for i, d in enumerate(dossies, 1):
        r = d["resultado"]
        evid = "".join(
            f"<li><b>{p:+.1f}</b> {e(t)} <span class=f>[{e(ev.tipo)}: {e(ev.fonte)}]</span>"
            + (f" <a href='{e(ev.url)}' rel=noopener target=_blank>fonte</a>" if ev.url else "")
            + (f"<div class=d>{e(str(ev.detalhe))}</div>" if ev.detalhe else "") + "</li>"
            for p, c, t, ev in sorted(r.linhas, key=lambda x: -x[0]))
        alertas = "".join(f"<li>{e(a)}</li>" for a in r.alertas)
        classe = r.prioridade.split()[-1]
        linhas.append(f"""
<details data-prio="{e(r.prioridade)}" data-seg="{e(d['segmento'])}" data-uf="{e(d['uf_matriz'] or '')}"
 data-site="{int(d.get('site_lido', False))}" data-conf="{r.confianca}" data-busca="{e((d['empresa'] + ' ' + d['cnpj']).lower())}">
<summary><span class=n>{i}</span><span class='p {e(classe)}'>{e(r.prioridade)}</span>
<b class=sc>{r.score:g}</b> <span class=c>{r.confianca:.0%} conf.{f" · até {r.teto:g}" if r.prioridade == "Inconclusiva" else ""}</span> <span class=emp>{e(d['empresa'])}</span>
<span class=s>{e(d['segmento'])} · {e(d['uf_matriz'] or '')}</span></summary>
<div class=corpo><p class=f>CNPJ {e(d['cnpj'])} (casamento {e(d['casamento'])}) · CNAE {e(d['cnae'] or '-')}
 · cobertura do ICP {d.get('cobertura_icp', 0)} de 100
 · revisar: <code>python -m revisao {e(d['codigo_lista'])} &lt;criterio&gt; confirmada|errada</code></p>
<h4>Evidências de fit</h4><ul>{evid or '<li>nenhuma</li>'}</ul>
<p class=f>Sem evidência: {e(', '.join(r.sem_evidencia) or 'nenhum')}</p>
{f'<h4>Alertas</h4><ul class=al>{alertas}</ul>' if alertas else ''}
<h4>Decisor ou canal público</h4><p>{e((r.canal or {}).get('cargo') or 'sem cargo')}: {e((r.canal or {}).get('descricao') or '')}</p>
</div></details>""")
    contagem = {}
    for d in dossies:
        contagem[d["resultado"].prioridade] = contagem.get(d["resultado"].prioridade, 0) + 1
    resumo = " · ".join(f"{k}: {v}" for k, v in sorted(contagem.items()))
    opcoes = lambda vals: "".join(f"<option>{e(v)}</option>" for v in sorted({v for v in vals if v}))
    m1 = resumo_m1(dossies) if dossies and "cobertura_icp" in dossies[0] else None
    linha_m1 = (f" · cobertura média do ICP {m1['media']} de 100 (teto {m1['teto']})" if m1 else "")
    return f"""<!doctype html><html lang=pt-BR><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Ranking de prospecção</title>
<style>
:root{{--bg:#fafaf8;--fg:#1d1d1b;--mut:#6b6b66;--lin:#e2e2dc;--cx:#fff;--a:#1f6f43;--b:#2f5d8a;--c:#8a6d2f;--x:#a33}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{--bg:#151514;--fg:#ececea;--mut:#9a9a94;--lin:#2c2c2a;--cx:#1e1e1c;--a:#6fc493;--b:#82aedb;--c:#d6b46a;--x:#e08080}}}}
*{{box-sizing:border-box}}
body{{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;max-width:980px;margin:0 auto;padding:16px}}
h1{{font-size:1.4em;margin:.2em 0}}
.filtros{{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0;position:sticky;top:0;background:var(--bg);padding:8px 0;border-bottom:1px solid var(--lin)}}
.filtros select,.filtros input{{background:var(--cx);color:var(--fg);border:1px solid var(--lin);border-radius:6px;padding:5px 8px;font:inherit;max-width:100%}}
.filtros input[type=search]{{flex:1;min-width:160px}} .filtros label{{display:flex;align-items:center;gap:4px;color:var(--mut)}}
details{{border-bottom:1px solid var(--lin);padding:6px 0}} summary{{cursor:pointer;overflow-wrap:anywhere}}
.n{{display:inline-block;width:2.4em;color:var(--mut)}} .c,.s,.f{{color:var(--mut);font-size:.9em}}
.p{{display:inline-block;min-width:8em;font-size:.85em}} .A{{color:var(--a)}} .B{{color:var(--b)}} .C{{color:var(--c)}}
.Desqualificada,.prioridade{{color:var(--x)}} .Inconclusiva{{color:var(--mut);font-style:italic}} .d{{color:var(--mut);font-size:.88em;margin-left:1.2em;overflow-wrap:anywhere}}
.corpo{{padding:0 0 8px 2.4em}} h4{{margin:10px 0 4px}} a{{color:var(--b)}} .al li{{color:var(--c)}}
@media (max-width:600px){{.corpo{{padding-left:.5em}} .p{{min-width:0;margin-right:.4em}}}}
</style></head><body>
<h1>Ranking de prospecção · associadas lista de origem</h1>
<p class=f>ICP: {e(icp.nome)} · gerado em {hoje.isoformat()} · {len(dossies)} empresas com CNPJ · {e(resumo)}{e(linha_m1)}</p>
<p class=f>Score de regra fixa: cada ponto mostra a evidência e a fonte. Critério sem evidência não pontua.
"Inconclusiva" é faixa que a evidência ainda não decide: com pouca confiança, o que falta poderia mudá-la; "até" é o score se o que falta viesse favorável.
Nome de pessoa e telefone não entram, e e-mail só de caixa de função (rh@, vagas@); o decisor aparece só pelo cargo.</p>
<div class=filtros>
<input type=search id=q placeholder="empresa ou CNPJ">
<select id=prio><option value="">toda prioridade</option>{opcoes(d["resultado"].prioridade for d in dossies)}</select>
<select id=seg><option value="">todo segmento</option>{opcoes(d["segmento"] for d in dossies)}</select>
<select id=uf><option value="">toda UF</option>{opcoes(d["uf_matriz"] for d in dossies)}</select>
<label><input type=checkbox id=site> só com site lido</label>
<label><input type=checkbox id=conf> confiança ≥ 60%</label>
<span class=f id=total></span>
</div>
<div id=lista>{''.join(linhas)}</div>
<script>
const $=id=>document.getElementById(id);
function filtrar(){{
  const q=$('q').value.trim().toLowerCase(), pr=$('prio').value, sg=$('seg').value, uf=$('uf').value;
  let n=0;
  for(const d of document.querySelectorAll('#lista details')){{
    const ok=(!q||d.dataset.busca.includes(q))&&(!pr||d.dataset.prio===pr)&&(!sg||d.dataset.seg===sg)
      &&(!uf||d.dataset.uf===uf)&&(!$('site').checked||d.dataset.site==='1')&&(!$('conf').checked||+d.dataset.conf>=0.6);
    d.hidden=!ok; if(ok)n++;
  }}
  $('total').textContent=n+' de {len(dossies)}';
}}
for(const id of ['q','prio','seg','uf','site','conf'])$(id).addEventListener('input',filtrar);
filtrar();
</script>
</body></html>"""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--icp", default=None, help="arquivo do ICP (padrao: icp/exemplo.json)")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--saida", default=str(LISTA))
    args = ap.parse_args(argv)
    icp = carregar_icp(args.icp) if args.icp else ICP_PADRAO
    hoje = date.today()
    dossies = montar(icp, hoje)
    saida = Path(args.saida)
    (saida / f"dossie-{hoje.isoformat()}.json").write_text(
        json.dumps([como_dict(d) for d in dossies], ensure_ascii=False, indent=1), encoding="utf-8")
    (saida / f"ranking-{hoje.isoformat()}.html").write_text(relatorio_html(dossies, icp, hoje), encoding="utf-8")
    for d in dossies[:args.top]:
        print(justificativa(d["resultado"]) + "\n")
    m1 = resumo_m1(dossies)
    print(f"{len(dossies)} dossies em {saida}")
    print(f"M1, cobertura do ICP: media {m1['media']} de 100 (teto {m1['teto']}), mediana {m1['mediana']}, "
          f"maximo {m1['maximo']}, {m1['com_70_ou_mais']} com 70 ou mais; "
          f"site lido em {m1['site_lido']}, media {m1['media_com_site']} entre elas")


if __name__ == "__main__":
    main()
