# -*- coding: utf-8 -*-
"""Extrator: texto corrido do site da empresa vira campo do ICP, com prova.

E o unico lugar do prototipo com modelo de linguagem, e por um motivo: cada
empresa escreve do seu jeito ("mais de 1.200 colaboradores", "time de 1,2 mil
pessoas", "presentes em 4 estados"), e regra escrita a mao nao generaliza para
centenas de sites. E onde a IA faz o que planilha nao faz.

**O modelo extrai, o codigo confere.** Cada campo volta com o trecho literal
que o sustenta, e `extrair` verifica se esse trecho esta de fato na pagina. Se
nao estiver, o campo e descartado e o descarte fica registrado. Uma invencao do
modelo nao chega ao dossie: ou tem prova na pagina, ou nao entra.

O modelo nao pontua nada. Score e regra fixa, em outro modulo.
"""
from __future__ import annotations

import html as _html
import json
import os
import re
import unicodedata
from pathlib import Path

MODELO = "claude-opus-5-5"
# Extracao com esquema fechado nao precisa de raciocinio longo. Esforco e o
# controle de custo do Opus 5.5 (o pensamento nao desliga); o padrao dele e
# "medium", e aqui fica "low" de proposito, para medir se a qualidade se mantem.
ESFORCO = "low"
LIMITE_CARACTERES = 60_000
# O prompt pede ate 200 caracteres; o modelo nem sempre obedece, entao o codigo
# impoe. No lote das 306, vieram paragrafos e blocos de pagina como "trecho",
# e era por eles que entrava nome de pessoa: depoimento de funcionario,
# avaliacao do Google, diretoria.
TRECHO_MAX = 300

CAMPOS = (
    "colaboradores",      # numero de pessoas, como a empresa publica
    "rh_estruturado",     # existe area ou funcao de RH / beneficios
    "beneficios",         # a empresa oferece pacote de beneficios
    "sinal_crescimento",  # contratacao em volume, nova unidade, expansao, M&A
    "employer_branding",  # premio de clima, EVP, programa de engajamento
    "multi_localidade",   # opera em mais de uma cidade ou estado
    "dor_retencao",       # fala em turnover, retencao, dificuldade de atrair
)
BOOLEANOS = set(CAMPOS) - {"colaboradores"}

_CAMPO = {
    "type": "object",
    "properties": {
        "encontrado": {"type": "boolean"},
        "valor": {"type": "string"},
        "trecho": {"type": "string"},
    },
    "required": ["encontrado", "valor", "trecho"],
    "additionalProperties": False,
}
# Colaboradores e multi-localidade levam escopo: subsidiaria de multinacional
# publica numero do grupo. No site da Boreal Brasil, "9000+ Employees" e "27
# Countries" sao do grupo de Taiwan, e o trecho existe na pagina -- a conferencia
# literal passa. Sem escopo, o numero do grupo viraria porte do CNPJ brasileiro.
ESCOPOS = ("brasil", "grupo", "indefinido")
_CAMPO_COM_ESCOPO = {
    "type": "object",
    "properties": {**_CAMPO["properties"], "escopo": {"type": "string", "enum": list(ESCOPOS)}},
    "required": _CAMPO["required"] + ["escopo"],
    "additionalProperties": False,
}
COM_ESCOPO = {"colaboradores", "multi_localidade"}
ESQUEMA = {
    "type": "object",
    "properties": {c: (_CAMPO_COM_ESCOPO if c in COM_ESCOPO else _CAMPO) for c in CAMPOS},
    "required": list(CAMPOS),
    "additionalProperties": False,
}

SISTEMA = """Voce le paginas publicas do site de uma empresa brasileira e extrai fatos para qualificar a empresa como cliente de beneficios corporativos.

Para cada campo, responda so com o que o texto afirma. Se o texto nao afirma, encontrado=false, valor e trecho vazios. Nao deduza de indicios: "temos uma fabrica em Manaus" nao prova multi_localidade; "fabricas em Manaus e em Sao Paulo" prova.

trecho e uma copia literal e curta (ate 200 caracteres) do texto que sustenta o valor, sem reescrever, traduzir nem juntar pedacos distantes. Ele sera conferido letra por letra contra a pagina. Havendo opcao, prefira um trecho sem nome de pessoa.

Campos:
- colaboradores: numero de pessoas que trabalham na empresa, como publicado (ex.: "1.200", "mais de 3 mil"). escopo "brasil" se o numero e da operacao no Brasil, "grupo" se e do grupo ou da operacao mundial, "indefinido" se o texto nao deixa claro.
- rh_estruturado: "sim" se ha area, cargo ou vaga de RH, gente e gestao, ou beneficios.
- beneficios: "sim" se a empresa diz oferecer beneficios aos funcionarios.
- sinal_crescimento: "sim" se ha contratacao em volume, nova unidade, expansao, aquisicao ou crescimento recente; inclua a data no valor se o texto der.
- employer_branding: "sim" se ha premio de lugar para trabalhar, proposta de valor ao empregado ou programa de engajamento. Programa de estagio ou trainee sozinho nao conta: e recrutamento.
- multi_localidade: "sim" se a empresa opera em mais de uma cidade ou estado. escopo "brasil" se as localidades sao no Brasil, "grupo" se o texto fala de paises ou da presenca mundial do grupo, "indefinido" se nao da para saber.
- dor_retencao: "sim" se o texto fala de rotatividade, retencao ou dificuldade de contratar."""


class Recusa(Exception):
    """O modelo recusou a requisicao (stop_reason refusal), mesmo com fallback."""


# --- texto ------------------------------------------------------------------

def texto_de_html(html: str) -> str:
    sem = re.sub(r"<(script|style|noscript|template)\b.*?</\1>", " ", html, flags=re.S | re.I)
    sem = re.sub(r"<[^>]+>", " ", sem)
    return " ".join(_html.unescape(sem).split())


def _normal(texto: str) -> str:
    t = unicodedata.normalize("NFKD", _html.unescape(texto)).encode("ascii", "ignore").decode()
    return " ".join(t.lower().split())


def _segmentos(texto: str) -> list[tuple[str, str]]:
    """Separa o texto pelos cabecalhos "=== URL ===" que montam a entrada."""
    partes = re.split(r"^=== (\S+) ===$", texto, flags=re.M)
    if len(partes) == 1:
        return [("", texto)]
    return [(partes[i], partes[i + 1]) for i in range(1, len(partes) - 1, 2)]


def _onde_esta(trecho: str, segmentos: list[tuple[str, str]]) -> tuple[str, str] | None:
    alvo = _normal(trecho)
    if not alvo:
        return None
    for url, corpo in segmentos:
        if alvo in _normal(corpo):
            return url, corpo
    return None


# --- valores ----------------------------------------------------------------

def numero(valor: str) -> int | None:
    """'mais de 1.200' -> 1200; 'cerca de 3 mil' -> 3000; faixa -> o menor."""
    m = re.search(r"\d[\d.,]*", valor or "")
    if not m:
        return None
    bruto = m.group(0).rstrip(".,")
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", bruto):
        n = int(re.sub(r"[.,]", "", bruto))
    else:
        n = float(bruto.replace(",", "."))
    if re.match(r"\s*mil\b", (valor or "")[m.end():], re.I):
        n *= 1000
    return int(n)


def _sim(valor: str) -> bool:
    """Campo encontrado e verdadeiro, salvo negacao explicita.

    A primeira versao so aceitava valor comecando com "s". O modelo as vezes
    responde com uma frase ("Aquisicao da LEV Brasil em 2026"), e no lote das
    306 isso inverteu o valor de campos certos.
    """
    return not re.match(r"(nao|no|false|falso)\b", _normal(valor))


# --- chamada ao modelo --------------------------------------------------------

def _garantir_chave() -> None:
    """Usa ANTHROPIC_API_KEY do ambiente; se faltar, le do .env do agente-pessoal.

    A chave nunca e copiada para este repositorio nem impressa.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    env = Path(os.environ.get("ITA_ENV_ANTHROPIC", r"C:\AI-Projects\Agents\agente-pessoal\.env"))
    for linha in env.read_text(encoding="utf-8").splitlines():
        if linha.startswith("ANTHROPIC_API_KEY="):
            os.environ["ANTHROPIC_API_KEY"] = linha.split("=", 1)[1].strip()
            return
    raise RuntimeError("ANTHROPIC_API_KEY nao encontrada")


_cliente = None


def _chamar_claude(sistema: str, usuario: str):
    """Uma chamada, saida em JSON validado pelo esquema.

    Fallback de recusa ligado: se o classificador de seguranca recusar, a API
    refaz no modelo que a Anthropic recomenda para a categoria. O SDK instalado
    (0.99) ainda nao tem o parametro, entao ele vai como campo extra.
    """
    global _cliente
    import anthropic
    if _cliente is None:
        _garantir_chave()
        _cliente = anthropic.Anthropic()
    r = _cliente.beta.messages.create(
        model=MODELO,
        max_tokens=4000,
        betas=["server-side-fallback-2026-07-01"],
        system=[{"type": "text", "text": sistema, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": usuario}],
        output_config={"effort": ESFORCO, "format": {"type": "json_schema", "schema": ESQUEMA}},
        extra_body={"fallbacks": "default"},
    )
    if r.stop_reason == "refusal":
        categoria = getattr(getattr(r, "stop_details", None), "category", None)
        raise Recusa(f"categoria {categoria}")
    if r.stop_reason == "max_tokens":
        raise RuntimeError("resposta cortada em max_tokens")
    texto = next(b.text for b in r.content if b.type == "text")
    u = r.usage
    uso = {"modelo": r.model, "entrada": u.input_tokens, "saida": u.output_tokens,
           "cache_lido": getattr(u, "cache_read_input_tokens", 0) or 0}
    return texto, uso


# --- extracao -----------------------------------------------------------------

def _descarte(campo: str, item: dict, motivo: str) -> dict:
    """Descarte sem o texto: ele nao passou pelo detector de nomes."""
    return {"campo": campo, "valor": item.get("valor"), "tamanho": len(item.get("trecho") or ""),
            "motivo": motivo}


def _quem_leu(uso: dict | None) -> str:
    """O modelo que de fato respondeu, pelo nome do arquivo quando e local."""
    modelo = (uso or {}).get("modelo") or MODELO
    return modelo.replace("\\", "/").rsplit("/", 1)[-1].removesuffix(".gguf")


def extrair(texto: str, empresa: str, chamar=None, anonimizar=None) -> dict:
    """Campos do ICP extraidos do texto, so os que tem trecho literal na pagina.

    `chamar(sistema, usuario)` devolve o JSON (ou JSON e uso); e injetavel para
    teste sem rede e sem custo.
    """
    chamar = chamar or _chamar_claude
    truncado = len(texto) > LIMITE_CARACTERES
    texto = texto[:LIMITE_CARACTERES]
    saida = {"campos": {}, "descartados": [], "truncado": truncado, "erro": None, "uso": None}

    # Pagina densa passa do contexto do modelo local (46 mil tokens em 60 mil
    # caracteres) e o servidor devolve 400. Reenvia com metade, ate duas vezes.
    for tentativa in range(3):
        usuario = f"Empresa: {empresa}\n\nPaginas (cada uma comeca com === URL ===):\n\n{texto}"
        try:
            resposta = chamar(SISTEMA, usuario)
            break
        except Recusa as e:
            saida["erro"] = f"recusa: {e}"
            return saida
        except Exception as e:
            if getattr(e, "code", None) != 400 or tentativa == 2:
                raise
            texto = texto[:len(texto) // 2]
            saida["truncado"] = True
    if isinstance(resposta, tuple):
        resposta, saida["uso"] = resposta
    dados = json.loads(resposta)

    segmentos = _segmentos(texto)
    for campo in CAMPOS:
        item = dados.get(campo) or {}
        if not item.get("encontrado"):
            continue
        recortado = False
        if len(item.get("trecho", "")) > TRECHO_MAX:
            parte = recortar(item["trecho"], campo)
            if parte is None:
                # So o tamanho: o texto longo e justamente o que pode carregar nome.
                saida["descartados"].append({"campo": campo, "tamanho": len(item.get("trecho", "")),
                                             "motivo": "trecho longo demais"})
                continue
            item = {**item, "trecho": parte}
            recortado = True
        achado = _onde_esta(item.get("trecho", ""), segmentos)
        url, segmento = achado if achado else (None, None)
        if url is None:
            saida["descartados"].append(_descarte(campo, item, "trecho nao esta na pagina"))
            continue
        if not pertinente(campo, item["trecho"]):
            saida["descartados"].append(_descarte(campo, item, "trecho nao sustenta o campo"))
            continue
        valor = _sim(item["valor"]) if campo in BOOLEANOS else numero(item["valor"])
        if campo not in BOOLEANOS:
            valor = _confere_com_trecho(valor, item["trecho"])
        if valor is None:
            saida["descartados"].append(_descarte(campo, item, "valor sem numero"))
            continue
        registro = {"valor": valor, "url": url, "ancora": _ancora(item["trecho"], segmento),
                    "recortado": recortado,
                    "tipo": "extraido", "fonte": f"site da empresa, lido por {_quem_leu(saida['uso'])}"}
        try:
            nomes = (anonimizar or pessoas_no_trecho)(item["trecho"])
            texto_mascarado, com_nome = mascarar(item["trecho"], nomes)
            registro["trecho"] = mascarar_contato(texto_mascarado)
            registro["trecho_mascarado"] = com_nome or registro["trecho"] != texto_mascarado
        except Exception as e:  # falha fechada: sem detector, sem texto
            registro["trecho"] = None
            registro["trecho_omitido"] = f"detector de nomes indisponivel ({type(e).__name__})"
        if campo in COM_ESCOPO:
            escopo = item.get("escopo")
            escopo = escopo if escopo in ESCOPOS else "indefinido"
            registro["escopo"] = escopo_pelo_trecho(item["trecho"], escopo)
        saida["campos"][campo] = registro
    return saida


def paginas_do_site(dominio: str, baixar=None, maximo: int = 4) -> tuple[str, list[dict]]:
    """Home, carreiras e institucional do dominio, como texto com cabecalho por URL.

    Devolve o texto e o registro do que foi tentado: o que o robots negou, o que
    caiu, o que veio vazio. Pagina que nao veio nao some sem rastro.
    """
    from fontes import site
    baixar = baixar or site.baixar
    tentativas, partes = [], []
    home = None
    for base in (f"https://www.{dominio}/", f"https://{dominio}/"):
        try:
            html = baixar(base)
            home = base
            break
        except (site.Bloqueado, site.Indisponivel, site.RobotsIndisponivel) as e:
            tentativas.append({"url": base, "resultado": type(e).__name__})
    if home is None:
        return "", tentativas
    achados = site.classificar_links(html, dominio, home)
    origem = {t: ("menu" if achados[t] else "nao achado") for t in ("carreiras", "institucional")}
    # Menu sem link reconhecivel: sitemap primeiro, depois caminhos de praxe.
    if not (achados["carreiras"] and achados["institucional"]):
        pelo_sitemap = site.paginas_pelo_sitemap(dominio, baixador=baixar)
        for tipo in ("carreiras", "institucional"):
            if not achados[tipo] and pelo_sitemap[tipo]:
                achados[tipo] = pelo_sitemap[tipo]
                origem[tipo] = "sitemap"
    raiz = home.rstrip("/")
    for tipo in ("carreiras", "institucional"):
        if achados[tipo]:
            continue
        for caminho in site.CAMINHOS_DE_PRAXE[tipo][:4]:
            try:
                corpo = baixar(raiz + caminho)
            except (site.Bloqueado, site.Indisponivel, site.RobotsIndisponivel):
                continue
            if len(texto_de_html(corpo)) > 300:
                achados[tipo] = [raiz + caminho]
                origem[tipo] = "caminho de praxe"
                break
    tentativas.append({"url": home, "resultado": "descoberta", "origem": origem})
    urls = [home] + achados["carreiras"][:2] + achados["institucional"][:2]
    vistos = set()
    for url in urls[:maximo]:
        if url in vistos:
            continue
        vistos.add(url)
        try:
            corpo = html if url == home else baixar(url)
        except (site.Bloqueado, site.Indisponivel, site.RobotsIndisponivel) as e:
            tentativas.append({"url": url, "resultado": type(e).__name__})
            continue
        texto = texto_de_html(corpo)
        tentativas.append({"url": url, "resultado": "ok", "caracteres": len(texto)})
        if texto:
            partes.append(f"=== {url} ===\n{texto}")
    return "\n".join(partes), tentativas


# --- modelo local, na GPU, pelo LM Studio ---------------------------------------
#
# Alternativa sem custo por chamada ao Claude: um modelo aberto rodando na RTX
# 3060 da maquina, servido pelo LM Studio numa API no formato da OpenAI. A
# precisao continua protegida pelo mesmo mecanismo -- o trecho literal e
# conferido pelo codigo, nao pelo modelo -- entao o que pode cair com um modelo
# menor e a cobertura e o julgamento (escopo, employer branding), nao a verdade
# do que entra.

# Container "llm" do compose. O LM Studio desta maquina (porta 1234) nao tem
# motor para modelo de texto, so de embeddings.
LOCAL_URL = os.environ.get("ITA_LLM_LOCAL", "http://127.0.0.1:8081")
LOCAL_MODELO = os.environ.get("ITA_LLM_LOCAL_MODELO", "qwen2.5-7b-instruct")


def _local_host() -> None:
    from urllib.parse import urlsplit
    if urlsplit(LOCAL_URL).hostname not in {"127.0.0.1", "localhost", "llm"}:
        raise RuntimeError(f"Recusado: {LOCAL_URL} nao e local. O modelo local e so desta maquina.")


def corpo_local(sistema: str, usuario: str, modelo: str = None, esquema: dict = None,
                nome_esquema: str = "icp") -> dict:
    """Requisicao no formato OpenAI, com o mesmo esquema estrito do Claude."""
    return {
        "model": modelo or LOCAL_MODELO,
        "temperature": 0,
        "messages": [{"role": "system", "content": sistema},
                     {"role": "user", "content": usuario}],
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": nome_esquema, "strict": True,
                                            "schema": esquema or ESQUEMA}},
        # Qwen3 em diante pensam antes de responder; com a saida presa ao esquema,
        # o raciocinio nao tem onde ir. Modelo que nao conhece a chave a ignora.
        "chat_template_kwargs": {"enable_thinking": False},
    }


def chamar_local(sistema: str, usuario: str, postar=None, esquema: dict = None,
                 nome_esquema: str = "icp"):
    """Chama o modelo local. `postar(url, corpo) -> dict` e injetavel para teste."""
    import urllib.request
    _local_host()

    def _postar(url, corpo):
        req = urllib.request.Request(url, data=json.dumps(corpo).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.load(r)

    r = (postar or _postar)(f"{LOCAL_URL}/v1/chat/completions",
                            corpo_local(sistema, usuario, esquema=esquema, nome_esquema=nome_esquema))
    escolha = r["choices"][0]
    if escolha.get("finish_reason") == "length":
        raise RuntimeError("resposta do modelo local cortada por tamanho")
    u = r.get("usage") or {}
    uso = {"modelo": r.get("model", LOCAL_MODELO), "entrada": u.get("prompt_tokens", 0),
           "saida": u.get("completion_tokens", 0), "cache_lido": 0}
    return escolha["message"]["content"], uso


# --- pertinencia: o trecho existe, mas sustenta o campo? ------------------------
#
# A conferencia literal garante que a pagina diz aquilo, nao que aquilo prova o
# campo. Com o Qwen2.5-7B local, o titulo do site virou employer branding e uma
# feira de tecnologia virou sinal de crescimento -- textos literais, e
# irrelevantes. Esta segunda conferencia e regra fixa, vale para qualquer modelo,
# e so pode derrubar campo, nunca criar.

_PESSOAS = r"(colaborador|funcionari|empregad|pessoas|profissionais|trabalhador|employees|staff|people|headcount)"
_TERMOS = {
    "colaboradores": _PESSOAS,
    "rh_estruturado": r"(\brh\b|recursos humanos|gente e gest|gestao de pessoas|departamento pessoal|\bhr\b|human resources|people team|benef)",
    "beneficios": r"benef",
    "sinal_crescimento": r"(expan|nova unidade|novas unidades|nova fabrica|inaugur|amplia|contrata|aquisi|adquir|incorpor|cresc|abertura|investiment|acquisi|expansion|hiring|growth|new plant|new facility)",
    "employer_branding": r"(great place|gptw|lugar para trabalhar|melhores empresas para|employer|engajamento|clima organizacional|working at|life at|best places|trabalhar (na|no|conosco|aqui)|depoimento|valor ao empregado|proposta de valor)",
    "multi_localidade": r"(filia|unidade|fabrica|planta|escritorio|matriz|estados|cidades|paises|countries|offices|presenca em|presente em|\b(sp|rj|mg|rs|pr|sc|ba|pe|ce|go|df|es|am|pa)\b.*\b(sp|rj|mg|rs|pr|sc|ba|pe|ce|go|df|es|am|pa)\b)",
    "dor_retencao": r"(turnover|rotatividade|retenc|reter talentos|dificuldade de contrat|escassez de|retention|attrition)",
}
# "Analista de Beneficios" e cargo, nao oferta de beneficio.
_CARGO_BENEFICIO = r"(analista|coordenador|coordenadora|gerente|especialista|assistente|supervisor|supervisora)\w* (de |em )?benef\w*"
_MUNDO = r"(countries|paises|worldwide|global|no mundo|around the world|internacional|world)"


_GPTW = r"(great place|gptw)"
_SELO = r"(certific|reconhec|premi|eleit|selo|conquist|award|certified|ranking|melhores empresas|best places)"


def pertinente(campo: str, trecho: str) -> bool:
    texto = _normal(trecho)
    if "lorem ipsum" in texto:   # texto de exemplo do tema do site, nao da empresa
        return False
    if campo == "employer_branding" and re.search(_GPTW, texto) and not re.search(_SELO, texto):
        # Citar o GPTW nao e ter o selo: "Great Place to Work e uma consultoria global".
        sem_gptw = re.sub(_GPTW, " ", texto)
        return re.search(_TERMOS[campo], sem_gptw) is not None
    if campo == "beneficios":
        texto = re.sub(_CARGO_BENEFICIO, " ", texto)
    if campo == "colaboradores" and not re.search(r"\d", texto):
        return False
    return re.search(_TERMOS[campo], texto) is not None


def escopo_pelo_trecho(trecho: str, escopo_do_modelo: str) -> str:
    """Trecho que fala de paises ou do mundo e do grupo, diga o modelo o que disser."""
    return "grupo" if re.search(_MUNDO, _normal(trecho)) else escopo_do_modelo


# --- nome de pessoa na evidencia ------------------------------------------------
#
# O desenho deixa decisor nominal fora do pipeline automatizado, e o trecho
# literal -- que e a prova de cada campo -- pode conter nome: "Diretora de
# Recursos Humanos Fulana ...", depoimento de funcionario, avaliacao assinada.
#
# Medido em 130 trechos curtos do lote da lista de origem: 4 tinham nome de pessoa. O
# Presidio (spaCy, portugues) achou 3 e deu falso alarme em 12 (ruas, empresas,
# "Nossa"); o Qwen local achou 3 e errou em 4, todos nome de rua. Qwen mais a
# regra de rua: 3 de 4, nenhum falso alarme.
#
# O cargo fica, porque e o que prova o campo e diz onde mora a decisao. O nome
# vira [nome]. Sem detector, falha fechada: o texto nao e guardado, so a ancora.

_RUA = (r"(^|[\s,;:-])(rua|r\.|av\.?|avenida|al\.?|alameda|travessa|tv\.|estrada|estr\.|rod\.|"
        r"rodovia|praca|pca\.?|largo)"
        r"(\s+(cel|cap|dr|eng|gen|maj|prof|dep|des|min|pres|sen|gov)\.?"
        r"|\s+(coronel|doutor|deputado|presidente|governador|senador|professor|engenheiro))?\s*$")

_SISTEMA_NOMES = (
    "Voce identifica nomes de pessoas fisicas num trecho de site de empresa. "
    "Liste so nomes de pessoas (ex.: funcionario, diretor, cliente que assina avaliacao). "
    "NAO conta: nome de rua ou avenida mesmo que seja nome de pessoa, nome de empresa, "
    "marca, produto, cidade, palavra comum. Copie cada nome exatamente como aparece.")
_ESQUEMA_NOMES = {"type": "object",
                  "properties": {"pessoas": {"type": "array", "items": {"type": "string"}}},
                  "required": ["pessoas"], "additionalProperties": False}


def pessoas_no_trecho(trecho: str, postar=None) -> list[str]:
    """Nomes de pessoa no trecho, segundo o modelo local, so os que existem literalmente."""
    texto, _ = chamar_local(_SISTEMA_NOMES, trecho, postar=postar, esquema=_ESQUEMA_NOMES,
                            nome_esquema="pessoas")
    return [n for n in json.loads(texto)["pessoas"] if n and n in trecho]


def _depois_de_rua(trecho: str, nome: str) -> bool:
    i = trecho.find(nome)
    antes = _normal(trecho[:i])[-40:] if i >= 0 else ""
    return re.search(_RUA, antes) is not None


def mascarar(trecho: str, nomes: list[str]) -> tuple[str, bool]:
    reais = [n for n in nomes if not _depois_de_rua(trecho, n)]
    for n in sorted(reais, key=len, reverse=True):
        trecho = trecho.replace(n, "[nome]")
    return trecho, bool(reais)


def _ancora(trecho: str, segmento: str) -> dict:
    import hashlib
    alvo, corpo = _normal(trecho), _normal(segmento)
    i = corpo.find(alvo)
    return {"inicio": i, "fim": i + len(alvo), "sha256": hashlib.sha256(alvo.encode()).hexdigest()}


def confere_ancora(segmento: str, ancora: dict) -> bool:
    """A pagina ainda diz a mesma coisa naquela posicao? Sem precisar do texto guardado."""
    import hashlib
    pedaco = _normal(segmento)[ancora["inicio"]:ancora["fim"]]
    return hashlib.sha256(pedaco.encode()).hexdigest() == ancora["sha256"]


# --- telefone e e-mail no trecho ------------------------------------------------
#
# A auditoria do lote achou telefone e e-mail nos trechos aceitos. Telefone nao
# prova campo nenhum: sai sempre. E-mail de caixa de funcao (rh@, vagas@) e canal
# institucional e e o que prova que o RH existe: fica. Qualquer outro e-mail pode
# ser de pessoa (joao.silva@): sai.

CAIXAS_DE_FUNCAO = {"rh", "talentos", "vagas", "carreiras", "carreira", "trabalheconosco", "curriculo",
                    "curriculos", "recrutamento", "selecao", "dp", "pessoas", "people", "hr", "jobs",
                    "careers", "contato", "comercial", "sac", "atendimento", "vendas", "info", "rh.sp"}
_EMAIL = re.compile(r"\b([\w.+-]+)@[\w-]+(\.[\w-]+)+\b")
_TELEFONE = re.compile(r"(\+\d{2}\s*)?\(?\b\d{2}\)?\s*\d{4,5}[-\s.]?\d{4}\b")


# Sem DDD: com hifen ou ponto sempre; so com espaco quando o texto diz que e
# telefone ("whatsapp: 9 9000 0000"), para nao pegar "2018 2019".
_TELEFONE_SEM_DDD = re.compile(r"\b9?\s?(?!(?:19|20)\d{2}[-.](?:19|20)\d{2}\b)\d{4}[-.]\d{4}\b")
_TELEFONE_DITO = re.compile(r"((whats\w*|tel\w*|fone|cel\w*|ligue|contato)\W{0,4})(9?\s?\d{4}\s\d{4})\b", re.I)


def mascarar_contato(trecho: str) -> str:
    trecho = _EMAIL.sub(lambda m: m.group(0) if m.group(1).lower() in CAIXAS_DE_FUNCAO else "[e-mail]", trecho)
    trecho = _TELEFONE.sub("[telefone]", trecho)
    trecho = _TELEFONE_DITO.sub(lambda m: m.group(1) + "[telefone]", trecho)
    return _TELEFONE_SEM_DDD.sub("[telefone]", trecho)


def _numeros(trecho: str) -> list[int]:
    """Cada numero do trecho, lido como numero() le (com milhar e "mil")."""
    return [numero(trecho[m.start():]) for m in re.finditer(r"(?<![\d.,])\d[\d.,]*", trecho)]


def _confere_com_trecho(valor: int | None, trecho: str) -> int | None:
    """O trecho foi conferido na pagina; o valor do modelo, nao. Se o valor nao
    aparece no trecho, vale o maior numero do trecho ("3" para "3,000+ employees")."""
    achados = [n for n in _numeros(trecho) if n is not None]
    if not achados or valor in achados:
        return valor
    return max(achados)


# --- recorte de trecho longo ----------------------------------------------------

_FIM_DE_FRASE = re.compile(r"(?<=[.!?;])\s+")
CONTEXTO_RECORTE = 200   # ate onde a janela cresce em volta do termo, quando nao ha frase


def recortar(trecho: str, campo: str, limite: int = TRECHO_MAX) -> str | None:
    """A menor parte do trecho longo que ainda sustenta o campo.

    Primeiro por frase. Se nenhuma frase serve (menu, lista sem pontuacao),
    a menor sequencia de palavras que passa na pertinencia, aumentada dos dois
    lados ate CONTEXTO_RECORTE caracteres. Devolve None se nada sustenta o campo.
    """
    frases = [f.strip() for f in _FIM_DE_FRASE.split(trecho) if f.strip()]
    boas = [f for f in frases if len(f) <= limite and pertinente(campo, f)]
    if boas:
        return boas[0]
    palavras = trecho.split()
    if not palavras or not pertinente(campo, trecho):
        return None
    # Acrescentar palavra nunca tira a pertinencia: da para buscar por bissecao.
    lo, hi = 1, len(palavras)              # menor fim com palavras[:fim] pertinente
    while lo < hi:
        meio = (lo + hi) // 2
        lo, hi = (lo, meio) if pertinente(campo, " ".join(palavras[:meio])) else (meio + 1, hi)
    fim = lo
    lo, hi = 0, fim - 1                    # maior inicio com palavras[ini:fim] pertinente
    while lo < hi:
        meio = (lo + hi + 1) // 2
        lo, hi = (meio, hi) if pertinente(campo, " ".join(palavras[meio:fim])) else (lo, meio - 1)
    ini = lo
    while True:
        cresceu = False
        for novo_ini, novo_fim in ((ini - 1, fim), (ini, fim + 1)):
            if 0 <= novo_ini and novo_fim <= len(palavras) and \
                    len(" ".join(palavras[novo_ini:novo_fim])) <= min(limite, CONTEXTO_RECORTE):
                ini, fim, cresceu = novo_ini, novo_fim, True
        if not cresceu:
            break
    janela = " ".join(palavras[ini:fim])
    return janela if len(janela) <= limite else None
