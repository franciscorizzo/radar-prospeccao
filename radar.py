# -*- coding: utf-8 -*-
"""Radar visual: o painel que o Roggers fez (Prospect Radar V1) com os
dossies reais no lugar da base ficticia.

    python -m radar                 # gera dados-exemplo/radar-AAAA-MM-DD.html

O motor, a matriz fit x timing, o roteiro de abordagem e a ficha sao os dele
(radar/Prospect_Radar_V1.html, sem alteracao no arquivo original). Aqui
so muda a entrada, mais quatro ajustes no codigo dele, cada um com o motivo:

  - porte desconhecido: no motor original `null < 80` e verdadeiro, e a empresa
    caia no desqualificador D01 e ganhava ticket da menor faixa;
  - contagens fixas em 120 (o tamanho da base ficticia) passam a ser do total;
  - a ficha ganha o bloco "Evidencias com fonte": trecho e URL de cada campo;
  - a pagina abre na empresa do endereco (#LISTA-codigo), para a demo ao vivo.

Dado ausente vira "Nao identificado", nunca "Nao": o motor do Roggers ja trata
assim e baixa a confianca, que e o comportamento certo.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path

import dossie

AQUI = Path(__file__).resolve().parent
MOLDE = AQUI / "radar" / "Prospect_Radar_V1.html"
NI = "Não identificado"
URL_RECEITA = "https://dados.gov.br/dados/conjuntos-dados/cadastro-nacional-da-pessoa-juridica---cnpj"
MESES = {"janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7,
         "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}
ROTULO = {"porte": "colaboradores", "rh": "RH estruturado", "multi_regiao": "multi-região",
          "crescimento": "crescimento", "employer_branding": "employer branding",
          "dor_retencao": "dor de retenção", "sinal_recente": "sinal recente", "decisor": "decisor/canal",
          "segmento": "segmento"}


def data_no_trecho(trecho: str, hoje: date) -> int | None:
    """Dias desde a data que o trecho traz: dd/mm/aaaa, "dd de mes de aaaa" ou so o ano."""
    t = dossie._sem_acento(trecho or "")
    datas = []
    for d, m, a in re.findall(r"\b(\d{1,2})/(\d{1,2})/((?:19|20)\d{2})\b", t):
        datas.append((int(a), int(m), int(d)))
    for d, mes, a in re.findall(r"\b(\d{1,2}) de (\w+),? (?:de )?((?:19|20)\d{2})\b", t):
        if mes in MESES:
            datas.append((int(a), MESES[mes], int(d)))
    if not datas:
        anos = [int(a) for a in re.findall(r"\b((?:19|20)\d{2})\b", t)]
        datas = [(a, 7, 1) for a in anos if a <= hoje.year]
    dias = []
    for a, m, d in datas:
        try:
            x = (hoje - date(a, m, d)).days
        except ValueError:
            continue
        if x >= 0:
            dias.append(x)
    return min(dias) if dias else None


def _ev(d: dict) -> dict:
    return {e["criterio"]: e for e in d["evidencias"]}


def empresa(d: dict, hoje: date) -> dict:
    """Um dossie no formato de empresa que o motor do Roggers le."""
    ev = _ev(d)
    valor = lambda c: (ev.get(c) or {}).get("valor")
    canal = d.get("decisor_ou_canal") or {}
    descr = canal.get("descricao") or ""
    carreiras = re.search(r"pagina de carreiras: (\S+?);", descr + ";")
    site = re.search(r"site institucional: (\S+?);", descr + ";")

    sinais = []
    s = valor("sinal_recente")
    if s:
        sinais.append({"t": "Expansão", "f": s["forca"], "d": s["dias"], "ev": ev["sinal_recente"]["detalhe"],
                       "src": "Receita Federal", "url": URL_RECEITA})
    for criterio, tipo in (("crescimento", "Expansão"), ("employer_branding", "Prêmio de clima")):
        e = ev.get(criterio)
        if e and e.get("url") and e.get("tipo") == "extraido":
            dias = data_no_trecho(e.get("detalhe") or "", hoje)
            if dias is not None and dias <= 730:
                sinais.append({"t": tipo, "f": "Médio", "d": dias, "ev": (e.get("detalhe") or "")[:240],
                               "src": "Site da empresa", "url": e["url"]})
    c = ev.get("crescimento")
    if c and "site:" in (c.get("detalhe") or "") and c.get("url"):
        trecho = c["detalhe"].split('site: "', 1)[-1].rstrip('"')
        dias = data_no_trecho(trecho, hoje)
        if dias is not None and dias <= 730 and not any(x["src"] == "Site da empresa" and x["t"] == "Expansão"
                                                        for x in sinais):
            sinais.append({"t": "Expansão", "f": "Médio", "d": dias, "ev": trecho[:240],
                           "src": "Site da empresa", "url": c["url"]})

    evid = [{"campo": ROTULO.get(e["criterio"], e["criterio"]), "texto": e["texto"],
             "trecho": e.get("detalhe") or "", "url": e.get("url") or "", "fonte": e["fonte"], "pontos": e["pontos"]}
            for e in d["evidencias"] if e["criterio"] != "segmento"]
    fontes = sorted({("Receita" if "Receita" in e["fonte"] else "site" if "site" in e["fonte"] else "lista de origem")
                     for e in d["evidencias"] if e["criterio"] != "segmento"})
    nivel = lambda v: v if v in ("Alto", "Médio") else NI
    return {
        "id": d["codigo_lista"] if d["codigo_lista"].startswith("NOVA-") else f"LISTA-{d['codigo_lista']}", "nome": d["empresa"], "dom": (site.group(1) if site else ""),
        "seg": d["segmento"], "colab": valor("porte"), "uf": d.get("uf_matriz") or "",
        "rh": "Sim" if valor("rh") else NI,
        "multi": "Sim" if valor("multi_regiao") else ("Não" if valor("multi_regiao") is False else NI),
        "cresc": nivel(valor("crescimento")), "eb": nivel(valor("employer_branding")),
        "dor": nivel(valor("dor_retencao")), "renov": NI,
        "fonte": " + ".join(fontes), "status": "Inativa" if (d.get("desqualificada") or "").startswith("D04") else "Ativa",
        "cargo": canal.get("cargo") or NI, "temdec": "Sim" if valor("decisor") == "cargo" else "Não",
        "canal": (carreiras or site).group(1) if (carreiras or site) else "",
        "tipocanal": "Página de carreiras" if carreiras else "Site institucional",
        "sinais": sinais, "evid": evid, "cnpj": d["cnpj"], "cnae": d.get("cnae") or "",
        "alertas": d.get("alertas") or [],
    }


# --- ajustes no codigo do Roggers ---------------------------------------------------

AJUSTES = [
    # porte desconhecido nao desqualifica, nao pontua e nao ganha ticket
    ("if(C.d01 && e.colab<C.d01v)", "if(C.d01 && e.colab!=null&&e.colab<C.d01v)"),
    ("  if(fp>0){fit+=C.f1*fp;",
     "  if(e.colab==null){fp=0; ef.push(['porte no Brasil não identificado em fonte pública',0]);}\n  if(fp>0){fit+=C.f1*fp;"),
    ("var tk=DB.ticket[faixa(e.colab)]||null;", "var tk=e.colab==null?null:(DB.ticket[faixa(e.colab)]||null);"),
    ("'<div class=\"ev\"><span>ticket de referência da faixa '+faixa(r.colab)+'</span>",
     "'<div class=\"ev\"><span>ticket de referência da faixa '+(r.colab==null?'não identificada':faixa(r.colab))+'</span>"),
    # contagens do tamanho da base, nao 120 fixo
    ("(120-el.length)+' desqualificadas de 120'", "(R.length-el.length)+' desqualificadas de '+R.length"),
    ("L.length+' de 120'", "L.length+' de '+R.length"),
    # segmento sem historico no cliente
    ("DB.segn[e.seg]+' oportunidades)'", "(DB.segn[e.seg]||0)+' oportunidades)'"),
    # validacao: os casos sao da base ficticia
    ("  DB.casos.forEach(function(c){",
     "  if(!DB.casos.length){document.getElementById('vg').innerHTML='';document.getElementById('k5').textContent='—';"
     "document.getElementById('vnote').innerHTML='Os 15 casos de validação são da base fictícia do cliente e rodam no "
     "<span class=\"mono\">avaliar_base</span>: 11 passam, 4 contradizem a própria base, 0 falham. Aqui a entrada é dado "
     "real, sem gabarito; a conferência é a amostra separada da Semana 4.';return;}\n  DB.casos.forEach(function(c){"),
    # ficha: evidencias com fonte e alertas do dossie
    ("  h+='<div class=\"fsec\"><h5>Acesso</h5>';",
     "  if(e.evid&&e.evid.length){h+='<div class=\"fsec\"><h5>Evidências com fonte</h5>';"
     "e.evid.forEach(function(x){h+='<div class=\"sig\"><div class=\"t\">'+esc(x.campo)+' · '+esc(x.texto)+'</div>'"
     "+(x.trecho?'\"'+esc(x.trecho)+'\"':'')+'<div class=\"d\">'+esc(x.fonte)+(x.url?' · <a href=\"'+esc(x.url)+'\" rel=\"noopener\" target=\"_blank\">fonte</a>':'')+'</div></div>';});"
     "if(e.alertas&&e.alertas.length)h+='<ul>'+e.alertas.map(function(a){return '<li class=\"flag\">'+esc(a)+'</li>';}).join('')+'</ul>';"
     "h+='<div class=\"hint\">CNPJ '+esc(e.cnpj)+' · CNAE '+esc(e.cnae)+'</div></div>';}\n"
     "  h+='<div class=\"fsec\"><h5>Acesso</h5>';"),
    # potencial: ate onde fit e timing vao se o dado que falta vier favoravel
    (r'''tim=Math.min(tim/tt*100,100);''',
     r'''tim=Math.min(tim/tt*100,100);
  var fx=0,tx=0,falta=[];
  if(e.colab==null){fx+=C.f1;falta.push('porte');}
  if(e.rh==='Não identificado'){fx+=C.f2;falta.push('RH');}
  if(e.multi==='Não identificado'){fx+=C.f3;falta.push('multi-região');}
  if(e.eb==='Não identificado'){fx+=C.f4;falta.push('employer branding');}
  if(e.renov==='Não identificado'){tx+=C.t1*(1-(JAN['Não identificado']||0));falta.push('renovação');}
  if(e.cresc==='Não identificado'){tx+=C.t3;falta.push('crescimento');}
  if(!e.sinais.length){tx+=C.t2*(1-Math.exp(-1/1.5));falta.push('sinal datado');}
  var fitMax=Math.min(fit+fx/tf*100,100), timMax=Math.min(tim+tx/tt*100,100);'''),
    (r'''fit:r1(fit),tim:r1(tim),''', r'''fit:r1(fit),tim:r1(tim),fitMax:r1(fitMax),timMax:r1(timMax),falta:falta,'''),
    # matriz: ponto vazado = a enriquecer; traco = potencial
    (r'''var rad=3.5+6*Math.sqrt((r.ve||0)/mx), on=sel&&sel.id===r.id;''',
     r'''var rad=3.5+6*Math.sqrt((r.ve||0)/mx), on=sel&&sel.id===r.id, baixa=r.conf<C.cc;
    if(on&&baixa&&(r.fitMax>r.fit||r.timMax>r.tim)){
      s+='<line x1="'+x(r.fit).toFixed(1)+'" y1="'+y(r.tim).toFixed(1)+'" x2="'+x(r.fitMax).toFixed(1)+'" y2="'+y(r.timMax).toFixed(1)+'" stroke="'+(on?'var(--ink)':cvar(r.q))+'" stroke-width="'+(on?1.6:1)+'" stroke-dasharray="3 3" opacity="'+(on?'.9':'.10')+'"/>';
      if(on) s+='<circle cx="'+x(r.fitMax).toFixed(1)+'" cy="'+y(r.timMax).toFixed(1)+'" r="6" fill="none" stroke="var(--ink)" stroke-width="1.5" stroke-dasharray="2 2"><title>potencial: fit '+r.fitMax+' · timing '+r.timMax+'</title></circle>';
    }'''),
    (r'''fill-opacity="'+(on?'.95':'.6')+'"''', r'''fill-opacity="'+(on?'.95':(baixa?'.06':'.6'))+'"'''),
    (r'''  s+='</svg>';''',
     r'''  s+='<text x="'+(M.l+6)+'" y="'+(M.t+30)+'" font-family="IBM Plex Mono,monospace" font-size="9.5" fill="var(--muted)">○ vazado: confiança abaixo de '+C.cc+', a enriquecer</text>';
  s+='<text x="'+(M.l+6)+'" y="'+(M.t+43)+'" font-family="IBM Plex Mono,monospace" font-size="9.5" fill="var(--muted)">- - traço (empresa selecionada): até onde vai se o dado que falta vier a favor</text>';
  s+='</svg>';'''),
    # ficha: o potencial e o que falta
    (r'''  if(r.bloq.length) h+='<div class="note"''',
     r'''  if(r.conf<C.cc&&r.falta.length) h+='<div class="note" style="border-color:var(--warn)"><b>A enriquecer.</b> Confiança '+r.conf+'. Falta: '+esc(r.falta.join(', '))+'. Se vier a favor, fit vai a '+Math.round(r.fitMax)+' e timing a '+Math.round(r.timMax)+(r.fitMax>=C.cf&&r.timMax>=C.ct?' — entraria em Q1.':r.fitMax>=C.cf?' — entraria em Q2.':r.timMax>=C.ct?' — entraria em Q3.':'.')+'</div>';
  if(r.bloq.length) h+='<div class="note"'''),
    # abre na empresa do endereco
    ("bind(); aplicar(); calcular(); abrir(R[0].id);",
     "window.RADAR={E:E,calcular:calcular,abrir:abrir};\n"
     "bind(); aplicar(); calcular();\n"
     "var alvo=decodeURIComponent((location.hash||'').slice(1))||__FOCO__;\n"
     "abrir(R.some(function(r){return r.id===alvo;})?alvo:R[0].id);"),
]

TEXTOS = [
    ("<title>Prospect Radar V1</title>", "<title>Prospect Radar</title>"),
    ("Protótipo V1 · Semana 03", "Protótipo V2"),
    ("Motor roda 100% no navegador, sem envio de dados. Base de exemplo, ficticia.",
     "Motor roda 100% no navegador, sem envio de dados. Entrada: lista de exemplo (ficticia), Receita Federal "
     "(dados abertos do CNPJ) e site de cada empresa lido por modelo local. Motor e painel: Roggers."),
]


def gerar(dossies: list[dict], hoje: date, molde: Path = MOLDE, foco: str | None = None) -> str:
    html = molde.read_text(encoding="utf-8")
    ini = html.index('<script id="d" type="application/json">') + len('<script id="d" type="application/json">')
    fim = html.index("</script>", ini)
    db = json.loads(html[ini:fim])
    empresas = [empresa(d, hoje) for d in dossies]
    novo = {"ref": hoje.isoformat(), "empresas": empresas, "ticket": db["ticket"], "seg": db["seg"],
            "casos": [], "winbase": db["winbase"], "segn": db["segn"]}
    dados = json.dumps(novo, ensure_ascii=False).replace("</", "<\\/")
    html = html[:ini] + dados + html[fim:]
    for velho, novo_txt in AJUSTES + TEXTOS:
        if velho not in html:
            raise ValueError(f"o molde mudou, ajuste nao encontrado: {velho[:60]}")
        html = html.replace(velho, novo_txt)
    html = html.replace("__FOCO__", json.dumps(foco or ""))
    n_sinais = sum(len(e["sinais"]) for e in empresas)
    cab = re.search(r"120 contas · 287 sinais · base fictícia · [\d/]+", html)
    if cab:
        html = html.replace(cab.group(0), f"{len(empresas)} contas · {n_sinais} sinais datados · "
                                          f"{hoje.strftime('%d/%m/%Y')}")
    return html


def main():
    hoje = date.today()
    arq = dossie.LISTA / f"dossie-{hoje.isoformat()}.json"
    dossie.main(["--top", "0"])   # sempre do lote atual: o radar nao le dossie velho
    dossies = json.loads(arq.read_text(encoding="utf-8"))
    destino = dossie.LISTA / f"radar-{hoje.isoformat()}.html"
    destino.write_text(gerar(dossies, hoje), encoding="utf-8")
    print(destino)
    return destino


if __name__ == "__main__":
    main()
