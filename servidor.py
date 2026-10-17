# -*- coding: utf-8 -*-
"""Radar ao vivo: o painel no navegador, com uma caixa para analisar empresa nova.

    python -m servidor            # abre http://127.0.0.1:8770

Digita-se o nome ou o CNPJ (e o site, se a empresa nao estiver na lista da
lista de origem). O servidor faz na hora o que o lote faz: acha o CNPJ, consulta a
Receita no indice local, le o site com o modelo local, pontua e devolve a
empresa para o painel, que a poe na matriz e abre a ficha. Cada passo aparece
na tela enquanto acontece.

So escuta em 127.0.0.1: nada sai desta maquina alem da leitura do site da
empresa (com robots.txt). Sem o modelo local, o site nao e lido ao vivo; entra
a leitura gravada, se houver, e a tela diz.
"""
from __future__ import annotations

import json
import re
import threading
import urllib.parse
import urllib.request
import uuid
import webbrowser
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import demo
import dossie
import radar

PORTA = 8770
ANALISADAS = dossie.LISTA / "analisadas.jsonl"


# --- resolver a empresa ---------------------------------------------------------

class Confirmar(LookupError):
    """O nome achou um candidato; a analise so roda com o CNPJ."""


def _dominio(site: str | None) -> str | None:
    if not site or not site.strip():
        return None
    s = re.sub(r"^https?://", "", site.strip().lower())
    return s.split("/")[0].removeprefix("www.") or None


def resolver(consulta: str, site: str | None, associadas: list[dict], casamento: list[dict],
             razao_por_cnpj=None, buscar_nome=None, por_site=None, por_agente=None,
             mostrar=None, marca: str | None = None, por_dominio=None) -> tuple[dict, dict]:
    """(associada, casamento) para a consulta: da lista da lista de origem, ou empresa nova.

    Empresa nova por CNPJ (a razao social vem da Receita), em geral escolhida na
    lista do painel. Por nome, em camadas (resolucao.py): CNPJ publicado no site;
    agente de busca com verificacao pelo codigo; e, se nada fechar, a busca por
    nome so sugere e levanta Confirmar. Empresa nova sem site digitado ganha o
    site descoberto (site_oficial.py), ou segue sem site e a tela diz.
    """
    mostrar = mostrar or (lambda titulo, linhas: None)
    a, cas = _resolver(consulta, site, associadas, casamento, razao_por_cnpj, buscar_nome, por_site,
                       por_agente, mostrar)
    if cas["codigo"].startswith("NOVA-") and not a["campos"].get("dominio"):
        achado = (por_dominio or _site_oficial)(marca, cas["cnpj"])
        if achado and achado.get("dominio"):
            a = {**a, "campos": {**a["campos"], "dominio": achado["dominio"]}}
            mostrar("0. Site da empresa: descoberto", [f"{achado['dominio']}  ({achado['origem']})",
                                                       f"titulo da pagina: {achado.get('titulo') or '-'}"])
        elif achado and achado.get("indicado"):
            mostrar("0. Site da empresa: indicado, nao confirmado",
                    [f"o Claude indicou {achado['indicado']}, mas a pagina nao abriu para leitura automatica "
                     "ou nao cita a empresa", "a analise segue so com a Receita; nada foi lido de um site nao conferido"])
        else:
            mostrar("0. Site da empresa: nao achado",
                    ["nem palpite pelo nome nem busca na web confirmaram; a analise segue so com a Receita",
                     "digite o site no campo 'Site' para ler"])
    return a, cas


def _resolver(consulta, site, associadas, casamento, razao_por_cnpj, buscar_nome, por_site, por_agente,
              mostrar) -> tuple[dict, dict]:
    try:
        a = demo.achar(consulta, associadas, casamento)
        cas = next(c for c in casamento if c["codigo"] == a["codigo"])
        if site and not a["campos"].get("dominio"):
            a = {**a, "campos": {**a["campos"], "dominio": _dominio(site)}}
        return a, cas
    except demo.Ambiguo:
        raise
    except LookupError:
        pass
    digitos = re.sub(r"\D", "", consulta)
    if len(digitos) == 14:
        cnpj = digitos
        razao = (razao_por_cnpj or _razao_na_receita)(cnpj[:8])
        if not razao:
            raise LookupError(f"CNPJ {consulta} nao esta entre os ativos da base da Receita")
        status = "informado"
        origem = "informado na tela"
    else:
        achado = _por_marca(consulta, _dominio(site), por_site or _cnpj_no_site, por_agente or _agente, mostrar)
        if achado:
            cnpj, razao, origem = achado
            codigo = f"NOVA-{cnpj[:8]}"
            a = {"codigo": codigo, "fonte_lista": "informada na tela",
                 "campos": {"razao_social": razao, "dominio": _dominio(site), "contato_cargo": None}}
            return a, {"codigo": codigo, "cnpj": cnpj, "status": "informado", "origem": origem}
        r = (buscar_nome or _buscar_na_receita)(consulta)
        if r["status"] == "ambiguo":
            raise demo.Ambiguo(f"mais de uma empresa casa com '{consulta}': informe o CNPJ "
                               f"({', '.join(r.get('candidatos', [])[:5])})")
        if r["status"] not in ("confiavel", "provavel"):
            raise LookupError(f"nenhuma empresa ativa casa com '{consulta}' na base da Receita; "
                              "informe o CNPJ")
        # Fora da lista, o nome so sugere: sem cidade nao ha como confirmar, e nome
        # curto engana ("dasa" casou com um motel no Amapa, nao com a Diagnosticos
        # da America). A analise roda com o CNPJ.
        c = r["candidato"]
        cnpj = r["cnpj"]
        raise Confirmar(f"Pelo nome, achei {c['razao_social']} ({c.get('municipio', '').title()}/{c.get('uf', '')}), "
                        f"CNPJ {_cnpj_fmt(cnpj)}. Se for ela, "
                        "digite o CNPJ para analisar; se nao for, procure o CNPJ certo (a Receita guarda a razao "
                        "social, nao a marca).")
    codigo = f"NOVA-{cnpj[:8]}"
    a = {"codigo": codigo, "fonte_lista": "informada na tela",
         "campos": {"razao_social": razao, "dominio": _dominio(site), "contato_cargo": None}}
    return a, {"codigo": codigo, "cnpj": cnpj, "status": status, "origem": origem}


_ROTULO_ACAO = {"buscar_nome": "busca por nome", "buscar_cnae": "busca do ramo na tabela CNAE",
                "maiores_por_cnae": "maiores empresas do CNAE", "detalhes": "detalhes do CNPJ",
                "responder": "resposta do modelo", "erro": "erro"}


def _por_marca(marca: str, dominio: str | None, por_site, por_agente, mostrar):
    """(cnpj, razao, origem) pelo site ou pelo agente, ja verificado; ou None."""
    if dominio:
        achado = por_site(dominio)
        if achado:
            mostrar("0. Quem e a empresa: CNPJ publicado no proprio site",
                    [f"CNPJ {achado['cnpj']} em {achado['url']}", f"razao social: {achado['razao']}"])
            return achado["cnpj"], achado["razao"], f"publicado no site ({achado['url']})"
    r = por_agente(marca, dominio)
    linhas = [f"{_ROTULO_ACAO.get(p['acao'], p['acao'])}: {p['argumento']}"
              + (f"  ({p['motivo']})" if p.get("motivo") else "") for p in r.get("caminho", [])]
    if r.get("raiz"):
        c, v = r["candidato"], r["verificacao"]
        sinais = [n for n, ok in (("nome ou sigla", v["nome"]), ("ramo do site", v["ramo"]),
                                  ("porte", v["porte"])) if ok]
        linhas.append(f"→ {c['razao']} ({c['estab']} estabelecimentos), conferido pelo codigo: {', '.join(sinais)}")
        mostrar("0. Quem e a empresa: agente de busca na Receita", linhas)
        return c["cnpj"], c["razao"], "achado pelo agente de busca e conferido"
    if linhas:
        mostrar("0. Quem e a empresa: agente de busca na Receita",
                linhas + ["nenhum candidato passou na conferencia do codigo"])
    s = r.get("sugerido")
    if s and s.get("cnpj"):
        raise Confirmar(f"O agente achou {s['razao']} ({'/'.join(s.get('ufs', [])[:3])}), CNPJ {_cnpj_fmt(s['cnpj'])}, "
                        "mas o codigo nao conseguiu conferir pelo ramo nem pelo porte. Se for ela, digite o CNPJ "
                        "para analisar; informar o site tambem ajuda a conferir.")
    return None


def _cnpj_fmt(c: str) -> str:
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}"


def _cnpj_no_site(dominio: str):
    import resolucao
    r = resolucao.cnpj_no_site(dominio)
    if not r:
        return None
    return {**r, "razao": _razao_na_receita(r["cnpj"][:8]) or "?"}


def _agente(marca: str, dominio: str | None) -> dict:
    import extrator
    import resolucao
    from fontes import site as fonte_site
    texto = ""
    if dominio:
        try:
            texto = extrator.texto_de_html(fonte_site.baixar(f"https://www.{dominio}/"))
        except Exception:
            texto = ""
    return resolucao.agente(marca, dominio, texto, resolucao.Indice())


def _site_oficial(marca: str | None, cnpj: str) -> dict | None:
    import resolucao
    import site_oficial
    c = resolucao.Indice().detalhes(cnpj[:8])
    if not c:
        return None
    try:   # sem rede ou API fora do ar: a analise segue sem site, nao cai
        return site_oficial.descobrir(marca, c["razao"], c["fantasias"], c.get("municipio") or "",
                                      ",".join(c["ufs"][:1]), cnpj, cnae=c.get("cnae_desc") or "",
                                      natureza=c.get("natureza"))
    except Exception:
        return None


def _razao_na_receita(raiz: str) -> str | None:
    from receita_base.indice import requisicao
    h = requisicao("POST", "/cnpj-empresas/_search", {"size": 1, "query": {"term": {"cnpj_basico": raiz}}})
    h = h["hits"]["hits"]
    return h[0]["_source"]["razao_social"] if h else None


def _buscar_na_receita(nome: str) -> dict:
    from receita_base import casamento
    return casamento.buscar(nome, "", "")


# --- trabalhos em andamento -------------------------------------------------------

class Base:
    """Lista, casamento, leituras gravadas e o que ja foi analisado na tela."""

    def __init__(self, hoje: date):
        self.hoje = hoje
        self.associadas = dossie._jsonl(dossie.LISTA / "lista.jsonl")
        self.casamento = json.loads((dossie.LISTA / "casamento.json").read_text(encoding="utf-8"))
        self.gravados = {r["codigo"]: r for r in dossie._jsonl(dossie.LISTA / "extracao.jsonl")
                         if not r.get("erro")}
        self.cnaes = dossie._cnaes()
        self.taxas = dossie.taxas_historico()
        arq = dossie.LISTA / f"dossie-{hoje.isoformat()}.json"
        if not arq.exists():
            dossie.main(["--top", "0"])
        self.dossies = {d["codigo_lista"]: d for d in json.loads(arq.read_text(encoding="utf-8"))}
        for d in dossie._jsonl(ANALISADAS):
            self.dossies[d["codigo_lista"]] = d
        self.trabalhos: dict[str, dict] = {}
        self.trava = threading.Lock()

    def pagina(self) -> str:
        lista = sorted(self.dossies.values(), key=lambda d: -d["score"])
        return radar.gerar(lista, self.hoje).replace("</body>", PAINEL + "</body>")

    def buscar(self, texto: str) -> dict:
        """Associada da lista, se for; senao, a lista de candidatos na Receita para escolher."""
        try:
            return {"associada": demo.achar(texto, self.associadas, self.casamento)["codigo"], "candidatos": []}
        except LookupError:
            pass
        if not hasattr(self, "indice"):
            import resolucao
            self.indice = resolucao.Indice()
        cands = self.indice.lista(texto)
        return {"associada": None, "candidatos": [
            {k: c.get(k) for k in ("cnpj", "razao", "fantasias", "municipio", "ufs", "estab", "porte", "cnae_desc")}
            for c in cands if c.get("cnpj")]}

    def analisar(self, consulta: str, site: str | None, executar=demo.executar, resolver_=resolver,
                 marca: str | None = None) -> str:
        tid = uuid.uuid4().hex[:10]
        t = {"status": "rodando", "passos": [], "erro": None, "empresa": None}
        self.trabalhos[tid] = t

        def mostrar(titulo, linhas):
            t["passos"].append({"titulo": titulo, "linhas": linhas})

        def rodar():
            try:
                extra = {"marca": marca} if marca else {}
                a, cas = resolver_(consulta, site, self.associadas, self.casamento, mostrar=mostrar, **extra)
                d = executar(cas["cnpj"], [a], [cas], self.hoje, gravados=self.gravados,
                             taxas=self.taxas, cnaes=self.cnaes, mostrar=mostrar)
                dd = dossie.como_dict(d)
                with self.trava:
                    self.dossies[dd["codigo_lista"]] = dd
                    with open(ANALISADAS, "a", encoding="utf-8") as f:
                        f.write(json.dumps(dd, ensure_ascii=False) + "\n")
                t["empresa"] = radar.empresa(dd, self.hoje)
                t["status"] = "pronto"
            except Exception as e:
                t["erro"] = str(e) if isinstance(e, LookupError) else f"{type(e).__name__}: {e}"
                t["status"] = "erro"

        threading.Thread(target=rodar, daemon=True).start()
        return tid


def estado_servicos() -> dict:
    def ok(url):
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                return r.status == 200
        except Exception:
            return False
    from extrator import LOCAL_URL
    from receita_base.indice import URL
    return {"receita": ok(URL + "/_cluster/health"), "modelo": ok(LOCAL_URL + "/health")}


# --- HTTP -------------------------------------------------------------------------

def criar_servidor(base: Base, porta: int = PORTA) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def _json(self, obj, codigo=200):
            corpo = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                corpo = base.pagina().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(corpo)))
                self.end_headers()
                self.wfile.write(corpo)
            elif self.path.startswith("/trabalho/"):
                t = base.trabalhos.get(self.path.rsplit("/", 1)[-1])
                self._json(t or {"status": "erro", "erro": "trabalho desconhecido"}, 200 if t else 404)
            elif self.path == "/servicos":
                self._json(estado_servicos())
            elif self.path.startswith("/buscar?"):
                q = (urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("q") or [""])[0].strip()
                if not q:
                    return self._json({"erro": "informe o nome"}, 400)
                try:
                    self._json(base.buscar(q))
                except demo.Ambiguo as e:
                    self._json({"associada": None, "candidatos": [], "erro": str(e)})
            else:
                self._json({"erro": "nao encontrado"}, 404)

        def do_POST(self):
            if self.path != "/analisar":
                return self._json({"erro": "nao encontrado"}, 404)
            n = int(self.headers.get("Content-Length") or 0)
            pedido = json.loads(self.rfile.read(n) or b"{}")
            consulta = (pedido.get("consulta") or "").strip()
            if not consulta:
                return self._json({"erro": "informe o nome ou o CNPJ"}, 400)
            marca = (pedido.get("marca") or "").strip() or None
            self._json({"id": base.analisar(consulta, pedido.get("site"), **({"marca": marca} if marca else {}))})

        def log_message(self, *args):
            pass

    return ThreadingHTTPServer(("127.0.0.1", porta), Handler)


PAINEL = r"""
<style>
#vivo{position:fixed;right:18px;bottom:18px;width:430px;max-height:78vh;overflow:auto;z-index:50;
 background:#fff;border:2px solid #0E4A52;border-radius:12px;box-shadow:0 10px 30px rgba(0,0,0,.18);
 font:13px/1.45 'IBM Plex Sans',system-ui,sans-serif;color:#1d1d1b}
#vivo h4{margin:0;padding:10px 14px;background:#0E4A52;color:#fff;font:600 13px Archivo,sans-serif;letter-spacing:.04em;
 display:flex;justify-content:space-between;align-items:center;cursor:pointer}
#vivo .corpo{padding:12px 14px}
#vivo input{width:100%;box-sizing:border-box;margin:0 0 6px;padding:7px 9px;border:1px solid #c9ccd6;border-radius:6px;font:inherit}
#vivo button{width:100%;padding:8px;border:0;border-radius:6px;background:#1F9D74;color:#fff;font:600 13px inherit;cursor:pointer}
#vivo button:disabled{background:#9aa;cursor:wait}
#vivo .svc{font:11px 'IBM Plex Mono',monospace;color:#555;margin-bottom:8px}
#vivo .svc b.ok{color:#1F9D74} #vivo .svc b.off{color:#b4532a}
#vivo .passo{border-left:3px solid #0E4A52;margin:10px 0 0;padding:2px 0 2px 9px;animation:surge .35s ease}
#vivo .passo .t{font-weight:700;font-size:12px;color:#0E4A52}
#vivo .passo div{white-space:pre-wrap;word-break:break-word;font-size:12px}
#vivo .erro{color:#b42a2a;margin-top:8px}
#vivo .rodando:after{content:' ⏳'}
#vivo .cand{margin:6px 0 0;padding:7px 9px;border:1px solid #c9ccd6;border-radius:6px;cursor:pointer;font-size:12px}
#vivo .cand:hover{border-color:#0E4A52;background:#F6F4EE}
#vivo .cand .m{font:11px 'IBM Plex Mono',monospace;color:#555}
@keyframes surge{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
</style>
<div id="vivo"><h4 id="vivoh"><span>ANALISAR EMPRESA AO VIVO</span><span id="vivom">—</span></h4>
<div class="corpo" id="vivoc">
 <div class="svc" id="svc">verificando serviços…</div>
 <input id="vq" placeholder="Nome da empresa ou CNPJ">
 <input id="vs" placeholder="Site (opcional, ex.: empresa.com.br)">
 <button id="vb">Analisar</button>
 <div id="vlog"></div>
</div></div>
<script>
(function(){
 var $=function(i){return document.getElementById(i);};
 function esc(t){return String(t==null?'':t).replace(/&/g,'&amp;').replace(/</g,'&lt;');}
 fetch('/servicos').then(function(r){return r.json();}).then(function(s){
   $('svc').innerHTML='Receita (índice local) <b class="'+(s.receita?'ok">● no ar':'off">● fora')+'</b> · '+
     'Modelo local <b class="'+(s.modelo?'ok">● no ar':'off">● desligado (usa leitura gravada)')+'</b>';
 }).catch(function(){ $('svc').textContent='servidor indisponível'; });
 $('vivoh').onclick=function(){ var c=$('vivoc'); c.style.display=c.style.display==='none'?'':'none'; };
 function vista(t){
   var h='';
   (t.passos||[]).forEach(function(p){
     h+='<div class="passo"><div class="t">'+esc(p.titulo)+'</div>'+p.linhas.map(function(l){return '<div>'+esc(l)+'</div>';}).join('')+'</div>';
   });
   if(t.status==='rodando') h+='<div class="passo"><div class="t rodando">trabalhando</div></div>';
   if(t.erro) h+='<div class="erro">'+esc(t.erro)+'</div>';
   $('vlog').innerHTML=h; var c=$('vivo'); c.scrollTop=c.scrollHeight;
 }
 function acompanhar(id,t0){
   fetch('/trabalho/'+id).then(function(r){return r.json();}).then(function(t){
     vista(t); $('vivom').textContent=Math.round((Date.now()-t0)/1000)+' s';
     if(t.status==='rodando') return setTimeout(function(){acompanhar(id,t0);},700);
     $('vb').disabled=false;
     if(t.status==='pronto'&&window.RADAR){
       var E=RADAR.E, i=E.findIndex(function(e){return e.id===t.empresa.id;});
       if(i>=0) E[i]=t.empresa; else E.push(t.empresa);
       RADAR.calcular(); RADAR.abrir(t.empresa.id);
       document.getElementById('ficha').scrollIntoView({behavior:'smooth'});
     }
   });
 }
 function analisar(consulta,marca){
   $('vb').disabled=true; $('vlog').innerHTML=''; var t0=Date.now();
   fetch('/analisar',{method:'POST',headers:{'Content-Type':'application/json'},
     body:JSON.stringify({consulta:consulta,site:$('vs').value.trim(),marca:marca||''})})
   .then(function(r){return r.json();}).then(function(r){
     if(r.erro){ vista({erro:r.erro}); $('vb').disabled=false; return; }
     acompanhar(r.id,t0);
   });
 }
 function fmt(c){ return c.slice(0,2)+'.'+c.slice(2,5)+'.'+c.slice(5,8)+'/'+c.slice(8,12)+'-'+c.slice(12); }
 function escolher(q,cs){
   if(!cs.length){ vista({erro:'Nenhuma empresa ativa na Receita com "'+q+'". Tente outro nome ou digite o CNPJ.'}); return; }
   var h='<div class="passo"><div class="t">Qual destas? ('+cs.length+' na Receita)</div></div>';
   cs.forEach(function(c,i){
     h+='<div class="cand" data-i="'+i+'"><b>'+esc((c.fantasias&&c.fantasias[0])||c.razao)+'</b>'+
        ((c.fantasias&&c.fantasias[0])?'<div>'+esc(c.razao)+'</div>':'')+
        '<div class="m">'+esc(fmt(c.cnpj))+' · '+esc((c.municipio||'').toLowerCase())+'/'+esc((c.ufs||[])[0]||'')+
        ' · '+c.estab+' estab. · '+esc(c.cnae_desc||'')+'</div></div>';
   });
   $('vlog').innerHTML=h;
   [].forEach.call(document.querySelectorAll('#vivo .cand'),function(el){
     el.onclick=function(){ analisar(cs[+el.getAttribute('data-i')].cnpj,q); };
   });
 }
 function iniciar(){
   var q=$('vq').value.trim(); if(!q) return;
   if(q.replace(/\D/g,'').length===14) return analisar(q);
   $('vb').disabled=true; $('vlog').innerHTML='<div class="passo"><div class="t rodando">buscando na Receita</div></div>';
   fetch('/buscar?q='+encodeURIComponent(q)).then(function(r){return r.json();}).then(function(r){
     $('vb').disabled=false;
     if(r.associada) return analisar(q);
     if(r.erro) return vista({erro:r.erro});
     escolher(q,r.candidatos||[]);
   }).catch(function(){ $('vb').disabled=false; vista({erro:'falha na busca'}); });
 }
 $('vb').onclick=iniciar;
 $('vq').addEventListener('keydown',function(e){ if(e.key==='Enter') iniciar(); });
})();
</script>
"""


def main():
    base = Base(date.today())
    srv = criar_servidor(base)
    url = f"http://127.0.0.1:{PORTA}/"
    print(f"Radar ao vivo em {url}  (Ctrl+C para parar)")
    webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
