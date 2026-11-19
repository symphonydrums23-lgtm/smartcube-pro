from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query, Request, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from datetime import datetime, timedelta
import json, os, secrets, uuid, csv, io, time, jwt, threading, hashlib, binascii, random
from collections import defaultdict
from dotenv import load_dotenv
load_dotenv()
from zoneinfo import ZoneInfo
BRT = ZoneInfo("America/Sao_Paulo")

# SEM app = FastAPI() aqui
# SEM CORS "*" aqui
# O app único fica lá embaixo, depois do SECRET_JWT

# FILA ESP32 + ANTI-REPLAY
_FILA_ABERTURA = []
_NONCES_USADOS = set()
_NONCES_EXPIRACAO = {}

def now_brt():
    return datetime.now(BRT)

def now_brt_str(fmt="%d/%m/%Y %H:%M:%S"):
    return now_brt().strftime(fmt)

lock_entregas = threading.Lock()

ARQ_COMERCIAL = "comercial.json"
ARQ_CONTRATOS = "contratos.json"
ARQ_CHAMADOS = "chamados.json"
ARQ_RECLAMACOES = "reclamacoes.json"
ARQ_VENDEDORES = "vendedores.json"
ARQ_WHITELABEL = "whitelabel.json"
ARQ_TABLET_STATUS = "tablet_status.json"
ARQ_TABLET_TOKENS = "tablet_tokens.json"

def verificar_tablet_token(request: Request, x_tablet_token: str = Header(None)):
    token = x_tablet_token or ""
    if not token:
        auth = request.headers.get("authorization") or ""
        if "Bearer" in auth:
            token = auth.replace("Bearer ", "").strip()
    if not token:
        raise HTTPException(401, "X-Tablet-Token obrigatório")
    tokens = load_json(ARQ_TABLET_TOKENS, {})
    dados = tokens.get(token)
    if not dados:
        raise HTTPException(401, "Token do tablet inválido")
    request.state.tablet_condominio_id = str(dados.get("condominio_id"))
    request.state.tablet_id = dados.get("tablet_id", "")
    return dados

# ESP32 tem token PRÓPRIO, separado do tablet. Não usa o token do tablet.
def verificar_esp32_token(request: Request, x_device_token: str = Header(None)):
    esperado = os.getenv("ESP32_DEVICE_TOKEN", "")
    token = x_device_token or request.headers.get("X-ESP32-Token") or ""
    if not esperado:
        raise HTTPException(500, "ESP32_DEVICE_TOKEN não configurado no .env")
    if not token or not secrets.compare_digest(token, esperado):
        raise HTTPException(401, "Token do ESP32 inválido")
    cond = str(request.headers.get("x-condominio-id") or "").strip()
    if not cond:
        raise HTTPException(400, "Header x-condominio-id obrigatorio no ESP")
    request.state.esp32_condominio_id = cond
    return True

# PARTE 2 - 1. TRAVA DE PORTA + ANTI-REPLAY
_COMANDOS_ABERTURA = {}  # nonce -> timestamp

SECRET_JWT = os.getenv("SECRET_JWT")

if not SECRET_JWT or len(SECRET_JWT) < 32:
    raise RuntimeError("SECRET_JWT ausente ou fraco (<32 chars). Defina no .env")

ADMIN_USER = os.getenv("SMARTCUBE_USER")
ADMIN_PASS = os.getenv("SMARTCUBE_ADMIN_PASS")
if not ADMIN_USER or not ADMIN_PASS:
    raise RuntimeError("SMARTCUBE_USER e SMARTCUBE_ADMIN_PASS obrigatórios no .env")

ALLOWED_ORIGINS_RAW = os.getenv("ALLOWED_ORIGINS", "")
if ALLOWED_ORIGINS_RAW:
    ALLOWED_ORIGINS = [o.strip() for o in ALLOWED_ORIGINS_RAW.split(",") if o.strip()]
else:
    ALLOWED_ORIGINS = [
        "http://localhost:5000", "http://127.0.0.1:5000",
        "https://localhost:5000",
        "http://localhost:3000",
    ]
ALLOWED_ORIGIN_REGEX = r"https://.*\.github\.io|https://.*\.onrender\.com|https://.*\.vercel\.app|https://.*\.netlify\.app"

app = FastAPI(title="SmartCube API v5.8 - TABLET OCUPA BOX")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=ALLOWED_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")
ALT_TEMPLATES = os.path.join(BASE_DIR, "modelos")
if not os.path.exists(TEMPLATES_DIR) and os.path.exists(ALT_TEMPLATES):
    TEMPLATES_DIR = ALT_TEMPLATES

FILE_LOCK = threading.RLock()
BOX_TABLET_RESERVADO = "03"
BOXES_TABLET_RESERVADOS = {"03"}

# PARTE 2 - 1. TRAVA DE PORTA + ANTI-REPLAY - DEPOIS DO app, SENÃO DÁ NameError
_COMANDOS_ABERTURA = {}  # nonce -> timestamp

@app.post("/api/tablet/abrir-porta")
def tablet_abrir_porta(request: Request, dados: dict, tablet: dict = Depends(verificar_tablet_token)):
    condominio_id = str(request.state.tablet_condominio_id)
    box = normalizar_box(dados.get("box", ""))
    lado = str(dados.get("lado", "") or "").strip().upper()  # F = Frente / V = Verso
    nonce = str(dados.get("nonce", "") or "").strip()
    acao = str(dados.get("acao", "") or "").strip().upper()  # ENTREGA ou RETIRADA

    if not box:
        raise HTTPException(400, "Informe o box")
    if lado not in ("F", "V"):
        raise HTTPException(400, "Lado inválido, use F ou V")
    if not nonce:
        raise HTTPException(400, "Nonce obrigatório")
    if acao not in ("ENTREGA", "RETIRADA"):
        raise HTTPException(400, "Ação inválida")

    # Anti-replay: mesmo nonce não abre 2x em 30s
    agora = time.time()
    for k in list(_COMANDOS_ABERTURA.keys()):
        if agora - _COMANDOS_ABERTURA[k] > 30:
            _COMANDOS_ABERTURA.pop(k, None)
    if nonce in _COMANDOS_ABERTURA:
        raise HTTPException(409, "Comando já usado - anti-replay")
    _COMANDOS_ABERTURA[nonce] = agora

    # Confere se existe entrega ativa nesse box / lado antes de abrir
    with FILE_LOCK:
        dados_arq = load_json(ARQ_DADOS, {"total_boxes":16,"lista":[],"historico":[]})
        tem = False
        for e in dados_arq.get("lista", []):
            if str(e.get("condominio_id")) == condominio_id and normalizar_box(e.get("box","")) == box:
                tem = True
                break
        if acao == "RETIRADA" and not tem:
            raise HTTPException(404, "Nenhuma entrega ativa nesse box")

    _FILA_ABERTURA.append({
        "box": box,
        "condominio_id": condominio_id,
        "nonce": nonce,
        "origem": "ABRIR_PORTA_TABLET",
        "lado": lado,
        "acao": acao,
        "criado_em": now_brt().isoformat(),
    })

    registrar_auditoria("ABRIR_PORTA", detalhes=f"Box {box} Lado {lado} Ação {acao}", condominio_id=condominio_id, request=request)
    return {
        "ok": True,
        "box": box,
        "lado": lado,
        "acao": acao,
        "abrir_por_segundos": 15,
        "comando": f"OPEN:{box}:{lado}",
        "nonce": nonce,
    }

@app.get("/api/tablet/proxima-abertura")
def tablet_proxima_abertura(request: Request, tablet: dict = Depends(verificar_tablet_token)):
    # CORRIGIDO ETAPA 1: Tablet só LÊ status, nunca dá pop.
    # Só o ESP32 executa e consome via /api/esp32/confirmar
    condominio_id = str(request.state.tablet_condominio_id)
    cmds = [c for c in list(_FILA_ABERTURA) if str(c.get("condominio_id")) == condominio_id]
    if not cmds:
        return {"tem_comando": False}
    item = cmds[0]
    return {
        "tem_comando": True,
        "box": item.get("box"),
        "lado": item.get("lado"),
        "acao": item.get("acao"),
        "nonce": item.get("nonce"),
        "comando": f"OPEN:{item.get('box')}:{item.get('lado')}",
        "status": "AGUARDANDO_ESP32",
    }

# PARTE 2 - 2. TIMEOUT + LOG DE PORTA ABERTA / FECHADA
@app.post("/api/tablet/porta-evento")
def tablet_porta_evento(request: Request, dados: dict, tablet: dict = Depends(verificar_tablet_token)):
    condominio_id = str(request.state.tablet_condominio_id)
    box = normalizar_box(dados.get("box", ""))
    lado = str(dados.get("lado", "") or "").strip().upper()
    evento = str(dados.get("evento", "") or "").strip().upper()  # ABERTA ou FECHADA
    motivo = str(dados.get("motivo", "") or "").strip()  # TIMEOUT, MANUAL, COMANDO

    if not box:
        raise HTTPException(400, "Informe o box")
    if lado not in ("F", "V"):
        raise HTTPException(400, "Lado inválido, use F ou V")
    if evento not in ("ABERTA", "FECHADA"):
        raise HTTPException(400, "Evento inválido, use ABERTA ou FECHADA")

    # Se fechou por timeout, registra como TIMEOUT
    if evento == "FECHADA" and not motivo:
        motivo = "TIMEOUT"

    registrar_auditoria(
        f"PORTA_{evento}",
        detalhes=f"Box {box} Lado {lado} Motivo {motivo}",
        condominio_id=condominio_id,
        request=request
    )
    return {"ok": True, "box": box, "lado": lado, "evento": evento, "motivo": motivo}

MODELOS_PRESET = {
    "1_BOX": {"label": "1 Box (Kit)", "fisico": 2, "util": 1, "P": 1, "M": 0, "G": 0, "G_boxes": []},
    "8_BOXES": {"label": "8 Boxes", "fisico": 8, "util": 7, "P": 4, "M": 2, "G": 1, "G_boxes": ["08"]},
    "16_BOXES": {"label": "16 Boxes", "fisico": 16, "util": 15, "P": 9, "M": 4, "G": 2, "G_boxes": ["09","16"]},
    "18_BOXES": {"label": "18 Boxes (Foto)", "fisico": 18, "util": 17, "P": 10, "M": 5, "G": 2, "G_boxes": ["09","18"]},
    "24_BOXES": {"label": "24 Boxes", "fisico": 24, "util": 23, "P": 13, "M": 7, "G": 3, "G_boxes": ["09","18","24"]},
    "32_BOXES": {"label": "32 Boxes", "fisico": 32, "util": 31, "P": 19, "M": 8, "G": 4, "G_boxes": ["09","18","24","32"]},
}

def get_path(nome):
    for base in [TEMPLATES_DIR, STATIC_DIR, BASE_DIR]:
        p = os.path.join(base, nome)
        if os.path.exists(p): return p
    return os.path.join(TEMPLATES_DIR, nome)

templates = Jinja2Templates(directory=TEMPLATES_DIR)
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

def load_json(path, default):
    full_path = os.path.join(BASE_DIR, path)
    if not os.path.exists(full_path): return default
    try:
        with open(full_path,'r',encoding='utf-8') as f: return json.load(f)
    except Exception:
        return default

def save_json(path, data):
    full_path = os.path.join(BASE_DIR, path)
    with FILE_LOCK:
        with open(full_path,'w',encoding='utf-8') as f:
            json.dump(data,f,ensure_ascii=False,indent=2)

ARQ_TOKENS = "tokens.json"; ARQ_DADOS = "dashboard_dados.json"; ARQ_KEYS = "api_keys.json"
ARQ_AUDIT = "auditoria.json"; ARQ_CONDS = "condominios.json"; ARQ_MORS = "moradores.json"
ARQ_APP_USERS = "app_users.json"; ARQ_CACHE_IA = "ia_cache.json"; ARQ_BLOQUEIOS = "ia_bloqueios.json"
ARQ_FRANQUIAS = "franquias.json"

def no_cache_html(path):
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f: content = f.read()
        return HTMLResponse(content=content, headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"})
    return HTMLResponse(f"<h1>Arquivo nao encontrado: {path}</h1>", status_code=404)

def hash_senha(senha: str) -> str:
    salt = secrets.token_bytes(16)
    pwdhash = hashlib.pbkdf2_hmac('sha256', senha.encode('utf-8'), salt, 100000)
    return binascii.hexlify(salt + pwdhash).decode('ascii')

def verificar_senha(stored: str, provided: str) -> bool:
    try:
        if not stored or not provided: return False
        b = binascii.unhexlify(stored.encode('ascii'))
        salt = b[:16]
        stored_hash = b[16:]
        pwdhash = hashlib.pbkdf2_hmac('sha256', provided.encode('utf-8'), salt, 100000)
        return pwdhash == stored_hash
    except Exception:
        return False

TOKENS_VALIDOS = {}
LOGIN_TENTATIVAS = defaultdict(list)

def load_tokens():
    global TOKENS_VALIDOS
    dados = load_json(ARQ_TOKENS, {})
    TOKENS_VALIDOS = {}
    for k, v in dados.items():
        try:
            v["expires"] = datetime.fromisoformat(v["expires"])
            TOKENS_VALIDOS[k] = v
        except Exception:
            pass

def save_tokens():
    to_save = {}
    for k, v in TOKENS_VALIDOS.items():
        to_save[k] = {"user": v["user"],"expires": v["expires"].isoformat(),"ip": v.get("ip","")}
    save_json(ARQ_TOKENS, to_save)

load_tokens()

def is_token_valid(token: str) -> bool:
    if not token: return False
    if token not in TOKENS_VALIDOS: load_tokens()
    dados = TOKENS_VALIDOS.get(token)
    if not dados: return False
    try:
        exp = dados["expires"]
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=BRT)
        if now_brt() > exp:
            TOKENS_VALIDOS.pop(token, None); save_tokens(); return False
    except Exception:
        try:
            if now_brt() > dados["expires"]:
                TOKENS_VALIDOS.pop(token, None); save_tokens(); return False
        except:
            return False
    return True

def requer_auth(request: Request, authorization: str = Header(None)):
    t = ""
    if authorization and "Bearer" in authorization: 
        t = authorization.replace("Bearer ","").strip()
    if not t: 
        t = request.cookies.get("sc_token") or request.headers.get("x-token") or ""
    # REMOVIDO: request.query_params.get("token")
    if not t or not is_token_valid(t):
        raise HTTPException(status_code=401, detail="Token inválido")
    return t

def requer_auth_opcional(request: Request, authorization: str = Header(None)):
    t = ""
    if authorization and "Bearer" in authorization:
        t = authorization.replace("Bearer ","").strip()
    if not t:
        t = request.cookies.get("sc_token") or request.headers.get("x-token") or ""
    if t and not is_token_valid(t):
        raise HTTPException(status_code=401, detail="Token inválido")
    return t or "tablet_public"

def verificar_api_key(request: Request, x_api_key: str = Header(None)):
    if not x_api_key:
        raise HTTPException(401, "X-API-Key obrigatória")
    keys = load_json(ARQ_KEYS, [])
    k = next((x for x in keys if x.get("api_key")==x_api_key), None)
    if not k:
        raise HTTPException(401, "API Key inválida")
    # Se a key tem condomínios permitidos, trava por eles
    conds_permitidos = k.get("condominios", [])
    if conds_permitidos:
        # Pega condominio_id do body/query se tiver, pra validar depois na rota
        request.state.api_key_conds = conds_permitidos
        request.state.api_key_nome = k.get("nome", "")
    else:
        request.state.api_key_conds = []
        request.state.api_key_nome = k.get("nome", "")
    return k

def check_api_key_condominio(request: Request, condominio_id: str):
    # P0-2: Se a key tem condomínios permitidos, trava por eles
    permitidos = getattr(request.state, "api_key_conds", []) or []
    if not permitidos:
        return True  # key sem trava = pode tudo (admin / genérica)
    if str(condominio_id) not in [str(c) for c in permitidos]:
        raise HTTPException(status_code=403, detail="API Key não tem acesso a este condomínio")
    return True

def check_rate_limit(request: Request):
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    LOGIN_TENTATIVAS[ip] = [x for x in LOGIN_TENTATIVAS[ip] if now - x < 900]
    if len(LOGIN_TENTATIVAS[ip]) >= 10:
        raise HTTPException(429, "Muitas tentativas. Aguarde 15 min")
    return ip

def registrar_auditoria(acao, usuario="sistema", detalhes="", condominio_id="", request: Request = None):
    # Nunca apaga log antigo. Nuvem aguenta, arquivo local também até migrar.
    logs = load_json(ARQ_AUDIT, [])
    ip = "sistema"
    user_agent = ""
    metodo = ""
    caminho = ""
    if request:
        if request.client:
            # Se estiver atrás de proxy na nuvem, pega o IP real
            ip = request.headers.get("x-forwarded-for", request.client.host).split(",")[0].strip()
        user_agent = request.headers.get("user-agent", "")[:200]
        metodo = request.method
        caminho = str(request.url.path)

    # Se veio "sistema" mas tem token, tenta identificar quem é
    if usuario in ("sistema", "", None) and request:
        try:
            tok = request.cookies.get("sc_token") or request.headers.get("x-token") or ""
            if tok and tok in TOKENS_VALIDOS:
                usuario = TOKENS_VALIDOS[tok].get("usuario", usuario) or usuario
                if not condominio_id:
                    condominio_id = TOKENS_VALIDOS[tok].get("condominio", "") or ""
        except Exception:
            pass

    registro = {
        "id": str(uuid.uuid4())[:8],
        "data": now_brt().strftime("%d/%m/%Y %H:%M:%S"),
        "timestamp": now_brt().isoformat(),
        "acao": acao,
        "usuario": usuario,
        "detalhes": detalhes,
        "condominio_id": condominio_id,
        "ip": ip,
        "user_agent": user_agent,
        "metodo": metodo,
        "caminho": caminho,
    }
    logs.append(registro)
    save_json(ARQ_AUDIT, logs)
    # Linha pronta pra nuvem (Cloud Logging / CloudWatch lê esse print como JSON)
    print(f"[AUDIT] {registro}", flush=True)
    return registro

def limpar_retencao():
    # 3.3 - LGPD: anonimiza histórico com mais de 90 dias
    try:
        dados = load_json(ARQ_DADOS, {"total_boxes":16,"lista":[],"historico":[]})
        limite = now_brt() - timedelta(days=90)
        mudou = False
        for h in dados.get("historico", []):
            try:
                dt = datetime.fromisoformat(h.get("created_at",""))
            except:
                continue
            if dt < limite and h.get("codigo_retirada"):
                h["codigo_retirada"] = "***"
                h["codigo"] = "***"
                h["qr_code"] = "***"
                h["nome"] = "***"
                mudou = True
        if mudou:
            save_json(ARQ_DADOS, dados)
    except Exception:
        pass
@app.get("/api/health")
def health():
    limpar_retencao()
    return {"ok": True, "status": "online", "versao": "v5.8.5-build-11-11-2026-API-LIVRE-CONDFY", "time": now_brt().isoformat()}
@app.get("/api/auditoria")
def listar_auditoria(request: Request, token: str = Depends(requer_auth), condominio_id: str = "", limite: int = 200):
    # 2.3 - Só admin vê auditoria completa
    info_token = TOKENS_VALIDOS.get(token, {})
    usuario = info_token.get("user", "") or info_token.get("usuario", "")
    if usuario not in ("admin", ADMIN_USER):
        raise HTTPException(status_code=403, detail="Acesso à auditoria restrito ao admin")

    logs = load_json(ARQ_AUDIT, [])
    # Filtra por condomínio se pedir, senão traz tudo mas só pro admin
    if condominio_id:
        logs = [l for l in logs if str(l.get("condominio_id","")) == str(condominio_id)]
    return logs[::-1][:min(limite, 500)]

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response

@app.get("/logo.png")
def serve_logo(): return FileResponse(get_path("logo.png"))
@app.get("/logo.dashboard.png")
def serve_logo2(): return FileResponse(get_path("logo.dashboard.png"))
@app.get("/logo-site.png")
def serve_logo_site(): return FileResponse(get_path("logo-site.png"))
@app.get("/armario_real_laranja.jpg")
def serve_armario_real(): return FileResponse(get_path("armario_real_laranja.jpg"))

@app.get("/", response_class=HTMLResponse)
async def inicio_page(request: Request): return no_cache_html(get_path("inicio.html"))
@app.get("/site", response_class=HTMLResponse)
def site_page(): return no_cache_html(get_path("site.html"))
@app.get("/login", response_class=HTMLResponse)
def login_page(): return no_cache_html(get_path("login.html"))
@app.get("/tablet", response_class=HTMLResponse)
async def tablet_menu_page(request: Request): return no_cache_html(get_path("tablet.html"))
@app.get("/retirada", response_class=HTMLResponse)
async def retirada_page(request: Request): return no_cache_html(get_path("retirada.html"))
@app.get("/entrega", response_class=HTMLResponse)
async def entrega_page(request: Request): return no_cache_html(get_path("entrega.html"))
@app.get("/deposito-interno", response_class=HTMLResponse)
async def deposito_interno_page(request: Request): return no_cache_html(get_path("deposito-interno.html"))
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    auth = request.headers.get("authorization") or ""
    token = auth.replace("Bearer ", "").strip() if auth else ""
    if not token:
        token = request.cookies.get("sc_token") or ""
    if not token or not is_token_valid(token):
        return RedirectResponse(url="/login", status_code=302)
    try:
        return templates.TemplateResponse("dashboard.html", {"request": request})
    except:
        return no_cache_html(get_path("dashboard.html"))

def gerar_boxes_lista(total_util, qtd_p, qtd_m, qtd_g, g_boxes_custom=None, dupla_face=False):
    total_util = int(total_util or 0)
    qtd_p = int(qtd_p or 0)
    qtd_m = int(qtd_m or 0)
    qtd_g = int(qtd_g or 0)
    g_boxes = set()
    if g_boxes_custom:
        for g in g_boxes_custom:
            g_boxes.add(str(g).zfill(2))
    boxes = []
    for i in range(1, total_util + 1):
        b = f"{i:02d}"
        if b in g_boxes:
            tam = "G"
        elif i <= qtd_p:
            tam = "P"
        elif i <= qtd_p + qtd_m:
            tam = "M"
        else:
            tam = "G"
        if dupla_face:
            boxes.append({"numero": b, "tamanho": tam, "face": "dupla", "porta_entrega": "F", "porta_retirada": "V"})
        else:
            boxes.append({"numero": b, "tamanho": tam, "face": "unica"})
    return boxes
def get_box_livre(dados, condominio_id="1", tamanho="P", cond_config=None):
    lista_filtrada = [x for x in dados.get("lista", []) if str(x.get("condominio_id"))==str(condominio_id)] if str(condominio_id)!="1" else dados.get("lista", [])
    ocupados = set()
    for x in lista_filtrada:
        try:
            b = str(x.get("box","")).strip().upper()
            if not b: continue
            try:
                num = int(b)
                ocupados.add(str(num))
                ocupados.add(f"{num:02d}")
            except:
                ocupados.add(b)
        except: pass
    boxes_lista = []
    if cond_config and cond_config.get("boxes_lista"):
        boxes_lista = cond_config["boxes_lista"]
    else:
        total = int(cond_config.get("total_util", cond_config.get("total_boxes", 16))) if cond_config else int(dados.get("total_boxes",16))
        qtd_p = int(cond_config.get("qtd_p", cond_config.get("boxes_config",{}).get("P", total-3))) if cond_config else total
        qtd_m = int(cond_config.get("qtd_m", 0)) if cond_config else 0
        qtd_g = int(cond_config.get("qtd_g", 0)) if cond_config else 0
        boxes_lista = gerar_boxes_lista(total, qtd_p, qtd_m, qtd_g, cond_config.get("G_boxes") if cond_config else None)
    mapa = {"P": [], "M": [], "G": []}
    for bx in boxes_lista:
        num = bx["numero"]
        if num in BOXES_TABLET_RESERVADOS: continue
        mapa[bx["tamanho"]].append(num)
    ordem = []
    tamanho = (tamanho or "P").upper()
    if tamanho=="P": ordem=["P","M","G"]
    elif tamanho=="M": ordem=["M","G"]
    else: ordem=["G"]
    for t in ordem:
        for box_num in mapa.get(t, []):
            if str(box_num) not in ocupados and f"{int(box_num):02d}" not in ocupados and box_num not in ocupados:
                if box_num in BOXES_TABLET_RESERVADOS: continue
                return box_num, t if t!=tamanho else tamanho, t!=tamanho
    return None, tamanho, False

def gerar_codigo_armario(existentes=None):
    if existentes is None:
        conds = load_json(ARQ_CONDS, [])
        existentes = set()
        for c in conds:
            for key in ["codigo_armario", "armario_numero", "armario_id", "codigo"]:
                v = c.get(key)
                if v and str(v).startswith("ARM-"):
                    existentes.add(str(v))
    for _ in range(100):
        novo = f"ARM-{random.randint(10000, 99999)}"
        if novo not in existentes:
            existentes.add(novo)
            return novo
    return f"ARM-{random.randint(10000, 99999)}"

def garantir_codigo_armario(conds_list):
    existentes = set()
    for c in conds_list:
        for key in ["codigo_armario", "armario_numero", "armario_id", "codigo"]:
            v = c.get(key)
            if v and str(v).startswith("ARM-"):
                existentes.add(str(v))
    alterado = False
    for c in conds_list:
        codigo_atual = c.get("codigo_armario") or c.get("armario_numero") or c.get("armario_id") or ""
        if not codigo_atual or not str(codigo_atual).startswith("ARM-"):
            novo = gerar_codigo_armario(existentes)
            c["codigo_armario"] = novo
            c["armario_numero"] = novo
            c["armario_id"] = novo
            alterado = True
        else:
            if not c.get("codigo_armario"): c["codigo_armario"] = codigo_atual
            if not c.get("armario_numero"): c["armario_numero"] = codigo_atual
            if not c.get("armario_id"): c["armario_id"] = codigo_atual
        if "qtd_p" not in c: c["qtd_p"] = c.get("total_boxes",16) -2
        if "qtd_m" not in c: c["qtd_m"] = 1
        if "qtd_g" not in c: c["qtd_g"] = 1
        if "modelo" not in c: c["modelo"] = "18_BOXES"
        if "dupla_face" not in c: c["dupla_face"] = False
        if "blocos" not in c: c["blocos"] = []
        if c.get("total_fisico",0) > 32 and c.get("modelo")=="32_BOXES":
            c["total_fisico"]=32
            c["total_util"]=31 if not c.get("dupla_face") else 30
    if alterado:
        save_json(ARQ_CONDS, conds_list)
    return conds_list

@app.get("/api/condominios")
def listar_conds(token: str = Depends(requer_auth)):
    conds = load_json(ARQ_CONDS, [])
    conds = garantir_codigo_armario(conds)
    # P0-5: Mesmo filtro do GET /{id} - não expõe dado sensível na lista
    saida = []
    for c in conds:
        cc = dict(c)
        cc.pop("cnpj", None)
        cc.pop("valor_mensal", None)
        cc.pop("valor_instalacao", None)
        cc.pop("endereco", None)
        saida.append(cc)
    return saida

@app.get("/api/condominios/modelos")
def listar_modelos(token: str = Depends(requer_auth)):
    return MODELOS_PRESET

@app.get("/api/condominios/public")
def conds_public():
    conds = load_json(ARQ_CONDS, [])
    conds = garantir_codigo_armario(conds)
    return [{"id": c["id"], "nome": c["nome"], "codigo_armario": c.get("codigo_armario")} for c in conds if str(c["id"])!="1"]

@app.get("/api/condominios/{cond_id}")
def get_cond(cond_id: str, token: str = Depends(requer_auth)):
    if str(cond_id) == "1":
        raise HTTPException(status_code=400, detail="Use o id real do condomínio, '1' não é permitido.")
    conds = load_json(ARQ_CONDS, [])
    mors = load_json(ARQ_MORS, [])
    conds = garantir_codigo_armario(conds)
    for c in conds:
        if str(c["id"]) == str(cond_id):
            c = dict(c)
            # 3.2 - Não expõe dado sensível / comercial no GET
            c.pop("cnpj", None)
            c.pop("valor_mensal", None)
            c.pop("valor_instalacao", None)
            c.pop("endereco", None)
            c["qtd_moradores"] = len([m for m in mors if str(m.get("condominio")) == str(cond_id)])
            return c
    raise HTTPException(404, "Condomínio não encontrado")

# FINANCEIRO - só total, nunca devolve CNPJ / valor por condomínio
@app.get("/api/financeiro/resumo")
def financeiro_resumo(token: str = Depends(requer_auth)):
    conds = load_json(ARQ_CONDS, [])
    mrr = 0.0
    instalacao_total = 0.0
    ativos = 0
    total_conds = 0
    por_modelo = {}
    for c in conds:
        if str(c.get("id")) == "1":
            continue
        total_conds += 1
        if str(c.get("status", "ativo")).lower() == "ativo":
            ativos += 1
        try:
            v = float(str(c.get("valor_mensal") or "0").replace("R$", "").replace(".", "").replace(",", ".").strip() or 0)
        except:
            v = 0.0
        try:
            vi = float(str(c.get("valor_instalacao") or "0").replace("R$", "").replace(".", "").replace(",", ".").strip() or 0)
        except:
            vi = 0.0
        mrr += v
        instalacao_total += vi
        modelo = str(c.get("modelo") or "SEM_MODELO")
        por_modelo[modelo] = por_modelo.get(modelo, 0) + 1
    # Ocupação real
    dados = load_json(ARQ_DADOS, {"total_boxes":16,"lista":[],"historico":[]})
    total_util = 0
    for c in conds:
        if str(c.get("id")) == "1":
            continue
        try:
            total_util += int(c.get("total_util") or c.get("total_boxes") or 0)
        except:
            pass
    ocupados = len(dados.get("lista", []))
    livres = max(0, total_util - ocupados)
    taxa = round((ocupados / total_util * 100) if total_util else 0, 1)
    return {
        "ok": True,
        "mrr": round(mrr, 2),
        "mrr_formatado": f"R$ {mrr:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
        "instalacao_total": round(instalacao_total, 2),
        "total_condominios": total_conds,
        "ativos": ativos,
        "total_util": total_util,
        "ocupados": ocupados,
        "livres": livres,
        "taxa_ocupacao": taxa,
        "por_modelo": por_modelo,
        "atualizado": now_brt().isoformat(),
    }

@app.post("/api/tablet/registrar")
def registrar_tablet(payload: dict, request: Request, token: str = Depends(requer_auth)):
    condominio_id = str(payload.get("condominio_id") or payload.get("condominio") or "").strip()
    tablet_id = str(payload.get("tablet_id") or f"tablet-{condominio_id}").strip()
    if not condominio_id or condominio_id == "1":
        raise HTTPException(400, "Informe o condominio_id real. '1' não é permitido.")
    tokens = load_json(ARQ_TABLET_TOKENS, {})
    for k, v in tokens.items():
        if str(v.get("condominio_id")) == condominio_id and str(v.get("tablet_id")) == tablet_id:
            return {"ok": True, "tablet_token": k, "condominio_id": condominio_id, "tablet_id": tablet_id}
    novo_token = "tb_" + secrets.token_urlsafe(32)
    tokens[novo_token] = {
        "condominio_id": condominio_id,
        "tablet_id": tablet_id,
        "criado_em": now_brt().isoformat(),
        "criado_por": TOKENS_VALIDOS.get(token, {}).get("user", "admin")
    }
    save_json(ARQ_TABLET_TOKENS, tokens)
    registrar_auditoria("REGISTROU_TABLET", detalhes=f"Tablet {tablet_id} Cond {condominio_id}", condominio_id=condominio_id, request=request)
    return {"ok": True, "tablet_token": novo_token, "condominio_id": condominio_id, "tablet_id": tablet_id}

@app.get("/api/tablet/info")
def tablet_info(request: Request, tablet: dict = Depends(verificar_tablet_token)):
    # ETAPA 1.4 - Tablet descobre o condomínio pelo TOKEN, nunca pelo localStorage
    condominio_id = str(request.state.tablet_condominio_id or tablet.get("condominio_id") or "")
    conds = load_json(ARQ_CONDS, [])
    cond = next((c for c in conds if str(c.get("id")) == condominio_id), None)
    return {
        "ok": True,
        "condominio_id": condominio_id,
        "tablet_id": tablet.get("tablet_id", ""),
        "condominio_nome": cond.get("nome", "") if cond else "",
        "codigo_armario": cond.get("codigo_armario", "") if cond else "",
        "dupla_face": bool(cond.get("dupla_face") or cond.get("is_dupla_face") or cond.get("dupla") or cond.get("duplaFace") or False) if cond else False,
    }

def get_cond_config(condominio_id):
    conds = load_json(ARQ_CONDS, [])
    c = next((x for x in conds if str(x.get("id")) == str(condominio_id)), None)
    if not c:
        return {
            "total_boxes": 16,
            "total_util": 15,
            "qtd_p": 13,
            "qtd_m": 1,
            "qtd_g": 1,
            "boxes_lista": gerar_boxes_lista(15, 13, 1, 1, ["09"]),
            "G_boxes": ["09"],
            "dupla_face": False
        }
    return c

def normalizar_box(box):
    # "05-F" ou "05-V" viram "05" - mesmo compartimento
    box = str(box or "").strip().upper()
    if "-" in box:
        box = box.split("-")[0]
    return box.zfill(2)

@app.post("/api/tablet/entrega")
async def tablet_entrega(payload: dict, request: Request = None, tablet: dict = Depends(verificar_tablet_token)):
    with FILE_LOCK:
        dados = load_json(ARQ_DADOS, {"total_boxes":16,"lista":[],"historico":[]})
        # ETAPA 1.4 - Condomínio vem do TOKEN do tablet, nunca do payload
        condominio_id = str(getattr(request.state, "tablet_condominio_id", "") or tablet.get("condominio_id") or "").strip()
        if not condominio_id or condominio_id == "1":
            raise HTTPException(status_code=400, detail="Tablet não travado. Configure o condomínio no tablet.")
        tamanho_solicitado = str(payload.get("tamanho","P")).upper() or "P"
        cond_config = get_cond_config(condominio_id)
        box_escolhido, tamanho_final, foi_upgrade = get_box_livre(dados, condominio_id, tamanho_solicitado, cond_config)
        if not box_escolhido:
            raise HTTPException(status_code=409, detail=f"SEM_ESPACO_{tamanho_solicitado}")
        # TRAVA DUPLA FACE: 05 já ocupado = 05 inteiro ocupado, não só F ou V
        box_escolhido = normalizar_box(box_escolhido)
        ocupado = any(normalizar_box(x.get("box")) == box_escolhido for x in dados.get("lista",[]))
        if ocupado:
            raise HTTPException(status_code=409, detail=f"Box {box_escolhido} já ocupado. Aguarde retirada pela porta interna.")
        existentes_cod = set(str(x.get("codigo_retirada","")) for x in dados.get("lista",[]))
        existentes_qr = set(str(x.get("qr_code","")) for x in dados.get("lista",[]))
        codigo_morador = ""
        for _ in range(20):
            codigo_morador = f"{secrets.randbelow(900000)+100000:06d}"
            if codigo_morador not in existentes_cod:
                break
        qr_morador = ""
        for _ in range(20):
            qr_morador = f"SC-RET-{secrets.token_hex(6).upper()}"
            if qr_morador not in existentes_qr:
                break
        # CORRIGIDO: protocolo sempre gerado no servidor, nunca aceita do frontend
        protocolo_entregador = f"SC-ENT-{condominio_id}-{int(time.time())}-{secrets.token_hex(3).upper()}"
        nova = {
            "box": str(box_escolhido).zfill(2),
            "condominio_id": condominio_id,
            "face": "dupla",
            "porta_entrega": "F",
            "porta_retirada": "V",
            "bloco": payload.get("bloco",""),
            "apartamento": payload.get("apartamento") or payload.get("apto",""),
            "codigo": codigo_morador,
            "codigo_retirada": codigo_morador,
            "qr_code": qr_morador,
            "protocolo": protocolo_entregador,
            "data": now_brt().strftime("%d/%m/%Y"),
            "hora": now_brt().strftime("%H:%M"),
            "created_at": now_brt().isoformat(),
            "expira_em": (now_brt()+timedelta(hours=72)).isoformat()
        }
        if foi_upgrade:
            for bx in (cond_config.get("boxes_lista",[]) if cond_config else []):
                if normalizar_box(bx["numero"]) == box_escolhido:
                    nova["tamanho_real"]=bx["tamanho"]
                    break
        else:
            nova["tamanho_real"]=tamanho_solicitado
        dados["lista"].append(nova)
        save_json(ARQ_DADOS, dados)
        registrar_auditoria("ENTREGA_TABLET", detalhes=f"Box {nova['box']} Bloco:{nova['bloco']} Apto:{nova['apartamento']} {tamanho_solicitado}->{nova['tamanho_real']} Prot {nova['protocolo']} Cond {condominio_id}", condominio_id=condominio_id, request=request)
        return {"ok": True, "protocolo": nova["protocolo"], "box": nova["box"], "codigo": codigo_morador, "qr_code": qr_morador, "tamanho_solicitado": tamanho_solicitado, "tamanho_real": nova["tamanho_real"], "upgrade": foi_upgrade, "bloco": nova["bloco"], "apartamento": nova["apartamento"]}

@app.post("/api/tablet/retirada")
async def tablet_retirada(payload: dict, request: Request = None, tablet: dict = Depends(verificar_tablet_token)):
    with FILE_LOCK:
        dados = load_json(ARQ_DADOS, {"total_boxes":16,"lista":[],"historico":[]})
        codigo = str(payload.get("codigo","")).strip()
        if not codigo:
            raise HTTPException(status_code=400, detail="Código obrigatório")
        if codigo.startswith("SC-") and not codigo.startswith("SC-RET-"):
            raise HTTPException(status_code=403, detail="Protocolo de entregador não abre box. Use código do morador.")
        condominio_tablet = str(getattr(request.state, "tablet_condominio_id", "") or tablet.get("condominio_id") or "").strip()
        achado = None
        achado_outro_cond = False
        for item in dados.get("lista",[]):
            if str(item.get("codigo_retirada"))==codigo or str(item.get("codigo"))==codigo or str(item.get("qr_code"))==codigo:
                if str(item.get("condominio_id","")) != condominio_tablet:
                    achado_outro_cond = True
                else:
                    achado = item
        if achado_outro_cond and not achado:
            raise HTTPException(status_code=403, detail="Código pertence a outro condomínio")
        if not achado:
            raise HTTPException(status_code=404, detail="Código não encontrado")
        if achado.get("status") == "AGUARDANDO_CONFIRMACAO_PORTA":
            raise HTTPException(status_code=409, detail="Retirada já em andamento, aguarde confirmação da porta")

        # CORRIGIDO: não tira da lista ainda. Marca como pendente
        # e joga na fila igual o admin faz. Só o /api/esp32/confirmar
        # tira da lista e joga pro histórico.
        achado["status"] = "AGUARDANDO_CONFIRMACAO_PORTA"
        nonce = f"RET-{condominio_tablet}-{achado.get('box')}-{int(time.time())}-{secrets.token_hex(3).upper()}"
        achado["nonce_retirada"] = nonce
        _FILA_ABERTURA.append({
        "box": str(achado.get("box")).zfill(2),
        "condominio_id": condominio_tablet,
        "nonce": nonce,
        "origem": "RETIRADA_TABLET",
        "lado": "V",
        "acao": "RETIRADA",
        "criado_em": now_brt().isoformat(),
    })
        save_json(ARQ_DADOS, dados)
        registrar_auditoria("RETIRADA_TABLET_SOLICITADA", detalhes=f"Box {achado.get('box')} Cond {condominio_tablet} Nonce {nonce} Aguardando porta", condominio_id=condominio_tablet, request=request)
        return {"ok": True, "box": achado.get("box"), "condominio_id": condominio_tablet, "nonce": nonce, "aguardando_confirmacao": True}
# ETAPA 2.1 - DEPÓSITO INTERNO: morador / zelador / síndico devolve encomenda errada pelo lado de dentro
# Sem sair do condomínio. O box continua o mesmo, só troca o destino.

@app.post("/api/tablet/deposito-interno")
def deposito_interno(request: Request, dados: dict, tablet: dict = Depends(verificar_tablet_token)):
    condominio_id = str(request.state.tablet_condominio_id)
    codigo = str(dados.get("codigo", "") or dados.get("codigo_retirada", "")).strip().upper()
    bloco_novo = str(dados.get("bloco", "") or "").strip().upper()
    apto_novo = str(dados.get("apartamento", "") or dados.get("apto", "") or "").strip()

    if not codigo:
        raise HTTPException(400, "Informe o código da encomenda")
    if not bloco_novo or not apto_novo:
        raise HTTPException(400, "Informe bloco e apto correto para reentrega")

    with FILE_LOCK:
        dados_arq = load_json(ARQ_DADOS, {"total_boxes":16,"lista":[],"historico":[]})
        orig = None
        for e in dados_arq.get("lista", []):
            if str(e.get("condominio_id")) != condominio_id:
                continue
            cod_e = str(e.get("codigo_retirada", "") or e.get("codigo", "") or e.get("qr_code", "")).upper()
            if cod_e == codigo:
                orig = e
                break
        if not orig:
            raise HTTPException(404, "Código não encontrado neste condomínio")
        if orig.get("status") == "DEVOLVIDO_INTERNO":
            raise HTTPException(400, "Essa encomenda já foi devolvida pelo lado de dentro")

        # Marca original como devolvida, não como retirada
        orig["status"] = "DEVOLVIDO_INTERNO"
        orig["devolvido_em"] = now_brt().isoformat()
        orig["devolvido_por"] = "INTERNO_LADO_B"

        # Cria nova entrega pro destino correto, NO MESMO BOX FÍSICO
        box_fisico = normalizar_box(orig.get("box", ""))
        novo_codigo = f"{secrets.randbelow(900000)+100000:06d}"
        novo_qr = f"SC-RET-{secrets.token_hex(6).upper()}"
        nova = {
            "box": box_fisico,
            "face": "dupla",
            "porta_entrega": "F",
            "porta_retirada": "V",
            "bloco": bloco_novo,
            "apartamento": apto_novo,
            "codigo": novo_codigo,
            "codigo_retirada": novo_codigo,
            "qr_code": novo_qr,
            "protocolo": f"SC-{secrets.randbelow(900000)+100000}",
            "data": now_brt().strftime("%d/%m/%Y"),
            "hora": now_brt().strftime("%H:%M"),
            "nome": orig.get("nome", ""),
            "created_at": now_brt().isoformat(),
            "condominio_id": condominio_id,
            "tamanho_solicitado": orig.get("tamanho_solicitado", "P"),
            "tamanho_real": orig.get("tamanho_real", "P"),
            "upgrade": False,
            "qr_valido": True,
            "expira_em": (now_brt()+timedelta(hours=72)).isoformat(),
            "origem": "DEVOLUCAO_INTERNA",
            "protocolo_origem": orig.get("protocolo", ""),
        }
        dados_arq["lista"].append(nova)
        # Move original pro histórico como devolvida, tira da lista ativa
        dados_arq["lista"] = [x for x in dados_arq.get("lista", []) if x is not orig]
        dados_arq["historico"].append(orig)
        save_json(ARQ_DADOS, dados_arq)
        registrar_auditoria("DEVOLUCAO_INTERNA", detalhes=f"Box {box_fisico} devolvido interno -> Bloco {bloco_novo} Apto {apto_novo} Orig {orig.get('protocolo')}", condominio_id=condominio_id, request=request)

    return {
        "ok": True,
        "box": f"{box_fisico}-B",
        "box_fisico": box_fisico,
        "lado": "B",
        "mensagem": f"Devolvido pelo lado de dentro. Novo código para Bloco {bloco_novo} Apto {apto_novo}: {novo_codigo}",
        "novo_protocolo": nova["protocolo"],
        "novo_codigo": novo_codigo,
        "bloco": bloco_novo,
        "apartamento": apto_novo,
    }

# === CRIAR CONDOMINIO - CORRIGIDO SEM DUPLICACAO ===
@app.post("/api/condominios")
def criar_cond(payload: dict, request: Request, token: str = Depends(requer_auth)):
    nome = str(payload.get("nome","")).strip()
    if not nome:
        raise HTTPException(status_code=400, detail="Nome do condomínio obrigatório")
    conds = load_json(ARQ_CONDS, [])
    codigo_armario = payload.get("codigo_armario") or payload.get("armario_numero") or gerar_codigo_armario()
    modelo = payload.get("modelo","18_BOXES")
    preset = MODELOS_PRESET.get(modelo, MODELOS_PRESET["18_BOXES"])
    qtd_p = int(payload.get("qtd_p", payload.get("P", preset["P"])))
    qtd_m = int(payload.get("qtd_m", payload.get("M", preset["M"])))
    qtd_g = int(payload.get("qtd_g", payload.get("G", preset["G"])))
    dupla_face = bool(payload.get("dupla_face", False))

    tem_blocos = bool(payload.get("tem_blocos", False))
    qtd_blocos = int(payload.get("qtd_blocos", 0) or 0)
    blocos_raw = payload.get("blocos", payload.get("bloco_lista", ""))
    blocos = []
    if isinstance(blocos_raw, str) and blocos_raw.strip():
        blocos = [b.strip() for b in blocos_raw.split(",") if b.strip()]
    elif isinstance(blocos_raw, list):
        blocos = [str(b).strip() for b in blocos_raw if str(b).strip()]
    
    if tem_blocos and qtd_blocos and not blocos:
        blocos = [chr(65+i) for i in range(qtd_blocos)]

    total_fisico_base = int(payload.get("total_fisico", preset["fisico"]))
    G_boxes = payload.get("G_boxes", preset["G_boxes"])

    if dupla_face:
        total_fisico = total_fisico_base
        total_util = total_fisico - 2
        qtd_p_lado = qtd_p // 2
        qtd_m_lado = qtd_m // 2
        qtd_g_lado = qtd_g // 2
        resto = (qtd_p+qtd_m+qtd_g) - (qtd_p_lado+qtd_m_lado+qtd_g_lado)*2
        if resto>0: qtd_p_lado += resto
        total_util_lado = qtd_p_lado+qtd_m_lado+qtd_g_lado
        label_dupla = f"FRENTE: {total_fisico//2} portas | VERSO: {total_fisico//2} portas = {total_util} úteis"
    else:
        total_fisico = total_fisico_base
        total_util = total_fisico - 1
        total_util_lado = total_util
        qtd_p_lado, qtd_m_lado, qtd_g_lado = qtd_p, qtd_m, qtd_g
        label_dupla = f"{total_util} úteis + 1 Tablet = {total_fisico} | Blocos: {', '.join(blocos) if blocos else 'Único'}"

    boxes_lista = gerar_boxes_lista(total_util_lado, qtd_p_lado, qtd_m_lado, qtd_g_lado, G_boxes)

    novo = {
        "id": str(uuid.uuid4())[:8],
        "nome": nome,
        "modelo": modelo,
        "dupla_face": dupla_face,
        "total_boxes": total_util,
        "total_util": total_util,
        "total_fisico": total_fisico,
        "total_tablets": 2 if dupla_face else 1,
        "tem_blocos": tem_blocos,
        "qtd_blocos": qtd_blocos,
        "blocos": blocos,
        "qtd_p": qtd_p, "qtd_m": qtd_m, "qtd_g": qtd_g,
        "boxes_config": {"P": qtd_p, "M": qtd_m, "G": qtd_g},
        "G_boxes": G_boxes,
        "boxes_lista": boxes_lista,
        "box_tablet": BOX_TABLET_RESERVADO,
        "codigo_armario": codigo_armario,
        "armario_numero": codigo_armario,
        "armario_id": codigo_armario,
        "status": "ativo",
        "criado_em": now_brt().isoformat(),
        "label_dupla": label_dupla,
        "valor_mensal": payload.get("valor_mensal",""),
        "valor_instalacao": payload.get("valor_instalacao",""),
        "periodo": payload.get("periodo","12 meses"),
        "data_inicio": payload.get("data_inicio",""),
        "cnpj": payload.get("cnpj",""),
        "endereco": payload.get("endereco",""),
    }

    conds.append(novo)
    save_json(ARQ_CONDS, conds)
    registrar_auditoria("CRIOU_CONDOMINIO", detalhes=f"{novo['nome']} - {codigo_armario} Blocos:{blocos}", condominio_id=novo["id"], request=request)
    return novo

@app.put("/api/condominios/{cond_id}")
def atualizar_cond(cond_id: str, payload: dict, request: Request = None, token: str = Depends(requer_auth)):
    conds = load_json(ARQ_CONDS, [])
    for c in conds:
        if str(c["id"])==str(cond_id):
            for k in payload:
                if k in ["codigo_armario","armario_numero","armario_id"] and not payload[k]: continue
                if k=="blocos" or k=="bloco_lista":
                    raw = payload[k]
                    if isinstance(raw, str):
                        c["blocos"]=[b.strip() for b in raw.split(",") if b.strip()]
                    else:
                        c["blocos"]=raw
                    continue
                c[k]=payload[k]
            if not c.get("codigo_armario"):
                c["codigo_armario"] = c.get("armario_numero") or gerar_codigo_armario()
                c["armario_numero"] = c["codigo_armario"]
                c["armario_id"] = c["codigo_armario"]
            if any(k in payload for k in ["qtd_p","qtd_m","qtd_g","modelo","dupla_face","blocos","bloco_lista"]):
                modelo = c.get("modelo","18_BOXES")
                preset = MODELOS_PRESET.get(modelo, MODELOS_PRESET["18_BOXES"])
                qtd_p = int(c.get("qtd_p", preset["P"]))
                qtd_m = int(c.get("qtd_m", preset["M"]))
                qtd_g = int(c.get("qtd_g", preset["G"]))
                dupla = bool(c.get("dupla_face", False))
                total_fisico = int(preset["fisico"])
                if dupla:
                    total_util = total_fisico - 2
                    total_util_lado = total_util//2
                    qtd_p_lado = qtd_p//2
                    qtd_m_lado = qtd_m//2
                    qtd_g_lado = qtd_g//2
                    resto = (qtd_p+qtd_m+qtd_g) - (qtd_p_lado+qtd_m_lado+qtd_g_lado)*2
                    if resto>0: qtd_p_lado+=resto
                else:
                    total_util = total_fisico - 1
                    total_util_lado = total_util
                    qtd_p_lado, qtd_m_lado, qtd_g_lado = qtd_p, qtd_m, qtd_g
                c["total_boxes"]=total_util
                c["total_util"]=total_util
                c["total_fisico"]=total_fisico
                c["total_tablets"]=2 if dupla else 1
                c["boxes_config"]={"P":qtd_p,"M":qtd_m,"G":qtd_g}
                c["boxes_lista"]=gerar_boxes_lista(total_util_lado, qtd_p_lado, qtd_m_lado, qtd_g_lado, c.get("G_boxes"))
                c["label_dupla"]=f"FRENTE: {total_fisico//2} portas ({total_util//2} úteis + 1 tablet) | VERSO: {total_fisico//2} portas" if dupla else f"{total_util} úteis + 1 Tablet = {total_fisico} portas"
                c["atualizado_em"]=now_brt().isoformat()
            save_json(ARQ_CONDS, conds)
            return c
    raise HTTPException(404)

def validar_senha_admin(senha_fornecida: str) -> bool:
    if not senha_fornecida: return False
    if senha_fornecida == ADMIN_PASS: return True
    try:
        if verificar_senha(ADMIN_PASS, senha_fornecida): return True
    except: pass
    return False

@app.post("/api/condominios/{cond_id}/excluir")
def excluir_cond_com_senha(cond_id: str, payload: dict, request: Request, token: str = Depends(requer_auth)):
    senha = payload.get("senha") or payload.get("senha_admin") or payload.get("password") or ""
    if not validar_senha_admin(senha):
        raise HTTPException(status_code=401, detail="Senha de admin incorreta. Exclusão não autorizada.")
    conds = load_json(ARQ_CONDS, [])
    cond_alvo = next((c for c in conds if str(c["id"]) == str(cond_id)), None)
    if not cond_alvo:
        raise HTTPException(status_code=404, detail="Condomínio não encontrado")
    conds = [c for c in conds if str(c["id"]) != str(cond_id)]
    save_json(ARQ_CONDS, conds)
    registrar_auditoria("EXCLUIU_CONDOMINIO", detalhes=f"Excluido {cond_alvo.get('nome')} {cond_alvo.get('codigo_armario','')} com senha admin", condominio_id=cond_id, request=request)
    return {"ok": True, "msg": f"Condomínio {cond_alvo.get('nome')} excluído"}

@app.post("/api/usuarios/operador")
def criar_operador(payload: dict, request: Request = None, token: str = Depends(requer_auth)):
    condominio = str(payload.get("condominio") or payload.get("condominio_id") or "").strip()
    bloco = str(payload.get("bloco") or "").strip()
    apto = str(payload.get("apto") or payload.get("apartamento") or "").strip()
    senha = str(payload.get("senha") or "").strip()
    nome = str(payload.get("nome") or f"Operador {bloco}/{apto}").strip()
    if not condominio or not bloco or not apto or not senha:
        raise HTTPException(status_code=400, detail="Condomínio, bloco, apto e senha são obrigatórios")
    users = load_json(ARQ_APP_USERS, [])
    existente = next((u for u in users if str(u.get("condominio"))==condominio and str(u.get("bloco")).lower()==bloco.lower() and str(u.get("apto")).lower()==apto.lower()), None)
    novo_user = {
        "id": existente["id"] if existente else str(uuid.uuid4())[:8],
        "condominio": condominio,
        "bloco": bloco,
        "apto": apto,
        "nome": nome,
        "role": "operador",
        "senha_hash": hash_senha(senha),
        "criado_em": existente.get("criado_em") if existente else now_brt().isoformat(),
        "atualizado_em": now_brt().isoformat()
    }
    if existente:
        users = [u for u in users if not (str(u.get("condominio"))==condominio and str(u.get("bloco")).lower()==bloco.lower() and str(u.get("apto")).lower()==apto.lower())]
    users.append(novo_user)
    save_json(ARQ_APP_USERS, users)
    registrar_auditoria("CRIOU_OPERADOR", detalhes=f"Operador {nome} {bloco}/{apto} Cond {condominio}", condominio_id=condominio, request=request)
    usuario_retorno = {k: v for k, v in novo_user.items() if k != "senha_hash"}
    return {"ok": True, "usuario": usuario_retorno}
@app.get("/api/usuarios")
def listar_usuarios(condominio: str = Query(None), token: str = Depends(requer_auth)):
    users = load_json(ARQ_APP_USERS, [])
    if condominio:
        users = [u for u in users if str(u.get("condominio"))==str(condominio)]
    # P0-4: Nunca devolver senha_hash
    return [{k: v for k, v in u.items() if k != "senha_hash"} for u in users]

@app.get("/api/operadores")
def listar_operadores(token: str = Depends(requer_auth)):
    return load_json(ARQ_FRANQUIAS, [])

@app.post("/api/operadores")
def criar_franquia(payload: dict, request: Request = None, token: str = Depends(requer_auth)):
    nome = str(payload.get("nome") or "").strip()
    if not nome:
        raise HTTPException(400, "Nome do operador obrigatório")
    franqs = load_json(ARQ_FRANQUIAS, [])
    novo = {
        "id": str(uuid.uuid4())[:8],
        "nome": nome,
        "cnpj_cpf": payload.get("cnpj") or payload.get("cnpj_cpf") or "",
        "telefone": payload.get("telefone") or "",
        "cidade": payload.get("cidade") or "",
        "criado_em": now_brt().isoformat()
    }
    franqs.append(novo)
    save_json(ARQ_FRANQUIAS, franqs)
    registrar_auditoria("CRIOU_FRANQUIA", detalhes=f"{nome} {novo['cidade']}", request=request)
    return {"ok": True, "operador": novo}
@app.delete("/api/operadores/{op_id}")
def excluir_operador(op_id: str, request: Request = None, token: str = Depends(requer_auth)):
    franqs = load_json(ARQ_FRANQUIAS, [])
    franqs = [f for f in franqs if str(f["id"]) != str(op_id)]
    save_json(ARQ_FRANQUIAS, franqs)
    return {"ok": True}

@app.post("/api/integracao/gerar")
def gerar_api_key_generica(payload: dict, request: Request, token: str = Depends(requer_auth)):
    nome = str(payload.get("nome","")).strip() or "API-Livre-Generica"
    conds = payload.get("condominios_permitidos", [])
    keys = load_json(ARQ_KEYS, [])
    nova_key = "sc_live_" + secrets.token_urlsafe(24)
    novo = {
        "id": str(uuid.uuid4())[:8],
        "nome": nome,
        "api_key": nova_key,
        "condominios": conds,
        "tipo": "generica_condfy",
        "criado_em": now_brt().isoformat(),
    }
    keys.append(novo)
    save_json(ARQ_KEYS, keys)
    registrar_auditoria("GEROU_API_KEY", detalhes=f"API {nome} - {nova_key[:12]}***", request=request)
    return {"ok": True, "api_key": nova_key, "nome": nome, "integracao": novo}

@app.get("/api/integracao/listar")
def listar_keys_integracao(token: str = Depends(requer_auth)):
    keys = load_json(ARQ_KEYS, [])
    # Nunca devolve a key completa, só preview
    saida = []
    for k in keys:
        saida.append({
            "id": k.get("id"),
            "nome": k.get("nome"),
            "condominios": k.get("condominios", []),
            "tipo": k.get("tipo"),
            "criado_em": k.get("criado_em"),
            "api_key_preview": (k.get("api_key","")[:12] + "***") if k.get("api_key") else ""
        })
    return saida
@app.delete("/api/integracao/{key_id}")
def excluir_key_integracao(key_id: str, request: Request, token: str = Depends(requer_auth)):
    keys = load_json(ARQ_KEYS, [])
    alvo = next((k for k in keys if str(k.get("id")) == str(key_id) or str(k.get("api_key")) == str(key_id)), None)
    keys = [k for k in keys if str(k.get("id")) != str(key_id) and str(k.get("api_key")) != str(key_id)]
    save_json(ARQ_KEYS, keys)
    registrar_auditoria("EXCLUIU_API_KEY", detalhes=f"Excluiu key {alvo.get('nome') if alvo else key_id}", condominio_id=",".join((alvo or {}).get("condominios", [])) if alvo else "", request=request)
    return {"ok": True}
@app.get("/api/moradores")
def listar_mors(condominio: str = Query(...), token: str = Depends(requer_auth)):
    if not condominio or str(condominio) == "1":
        raise HTTPException(status_code=400, detail="Informe o condominio_id. '1' (todos) não é permitido.")
    mors = load_json(ARQ_MORS, [])
    return [m for m in mors if str(m.get("condominio")) == str(condominio)]

@app.post("/api/moradores")
def criar_mor(payload: dict, request: Request = None, token: str = Depends(requer_auth)):
    nome = str(payload.get("nome","")).strip()
    if not nome:
        raise HTTPException(status_code=400, detail="Nome do morador obrigatório")
    mors = load_json(ARQ_MORS, [])
    novo = {"id": str(uuid.uuid4())[:8],"nome": nome,"bloco": payload.get("bloco",""),"apto": payload.get("apto",""),"condominio": payload.get("condominio","1")}
    mors.append(novo); save_json(ARQ_MORS, mors)
    registrar_auditoria("CRIOU_MORADOR", detalhes=f"{nome} {novo['bloco']}/{novo['apto']}", condominio_id=str(novo["condominio"]), request=request)
    return novo

@app.delete("/api/moradores")
def deletar_mor(id: str = Query(...), request: Request = None, token: str = Depends(requer_auth)):
    mors = load_json(ARQ_MORS, [])
    alvo = next((m for m in mors if str(m["id"]) == str(id)), None)
    mors = [m for m in mors if str(m["id"]) != str(id)]
    save_json(ARQ_MORS, mors)
    registrar_auditoria("EXCLUIU_MORADOR", detalhes=f"{alvo.get('nome') if alvo else id} {alvo.get('bloco') if alvo else ''}/{alvo.get('apto') if alvo else ''}", condominio_id=str(alvo.get("condominio","")) if alvo else "", request=request)
    return {"ok": True}
@app.post("/api/moradores/import")
async def import_csv(file: UploadFile = File(...), condominio: str = Form(...), request: Request = None, token: str = Depends(requer_auth)):
    content = (await file.read()).decode('utf-8', errors='ignore')
    delimiter = ';' if content.count(';') > content.count(',') else ','
    reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
    mors = load_json(ARQ_MORS, []); count=0
    for row in reader:
        nome = row.get("nome") or row.get("Nome") or next(iter(row.values()), "")
        if not nome or not str(nome).strip(): continue
        mors.append({"id": str(uuid.uuid4())[:8],"nome": str(nome).strip(),"bloco": str(row.get("bloco","")).strip(),"apto": str(row.get("apto","") or row.get("apartamento","")).strip(),"condominio": condominio})
        count+=1
    save_json(ARQ_MORS, mors)
    registrar_auditoria("IMPORTACAO_CSV", detalhes=f"Importou {count} delim={delimiter}", condominio_id=condominio, request=request)
    return {"importados": count, "delimitador": delimiter}

@app.get("/api/dashboard/dados")
def dashboard_dados(condominio: str = "1", token: str = Depends(requer_auth)):
    raw = load_json(ARQ_DADOS, {"total_boxes":16,"lista":[],"historico":[]})
    conds = load_json(ARQ_CONDS, [])
    lista_all = raw.get("lista", []); hist_all = raw.get("historico", [])
    if str(condominio) == "1": 
        lista=lista_all; historico=hist_all
        total_boxes = raw.get("total_boxes",16)
        try:
            soma = sum(int(c.get("total_util", c.get("total_boxes",0))) for c in conds if str(c.get("id"))!="1")
            if soma>0:
                total_boxes=soma
        except: pass
    else: 
        lista=[x for x in lista_all if str(x.get("condominio_id"))==str(condominio)]
        historico=[x for x in hist_all if str(x.get("condominio_id"))==str(condominio)]
        c_target = next((c for c in conds if str(c["id"])==str(condominio)), None)
        total_boxes = int(c_target.get("total_util", c_target.get("total_boxes",16))) if c_target else int(raw.get("total_boxes",16))
    
    ocupados=len(lista); livres=max(0,int(total_boxes)-ocupados)
    vencidas_lista = []
    agora = now_brt()
    for item in lista:
        try:
            created_str = item.get("created_at","")
            if not created_str:
                continue
            try:
                created = datetime.fromisoformat(created_str)
            except:
                created = datetime.strptime(created_str, "%Y-%m-%dT%H:%M:%S")
            if created.tzinfo is None:
                created = created.replace(tzinfo=BRT)
            if (agora - created).total_seconds() / 3600 > 72:
                vencidas_lista.append(item)
        except:
            pass

    return {
        "total_boxes":int(total_boxes),
        "livres":livres,
        "ocupados":ocupados,
        "lista":lista,
        "historico":historico,
        "vencidas": len(vencidas_lista),
        "vencidas_lista": vencidas_lista,
        "retiradas_total": len(historico),
        "por_hora": raw.get("por_hora", [0]*24),
        "atualizado": now_brt().strftime("%d/%m/%Y %H:%M:%S") + " BRT",
        "timestamp": now_brt().isoformat()
    }

@app.post("/api/auth/login")
def auth_login(payload: dict, request: Request):
    ip = check_rate_limit(request)
    usuario = payload.get("usuario","").strip(); senha = payload.get("senha","")
    if usuario == ADMIN_USER and senha == ADMIN_PASS:
        LOGIN_TENTATIVAS[ip].clear()
        token = "sc_" + secrets.token_urlsafe(32)
        TOKENS_VALIDOS[token] = {"user": usuario,"expires": now_brt() + timedelta(hours=8),"ip": ip}
        save_tokens()
        registrar_auditoria("LOGIN_SUCESSO", usuario=usuario, request=request)
        resp = JSONResponse({"ok": True, "expires_in": 28800})
        resp.set_cookie(key="sc_token", value=token, httponly=True, max_age=28800, samesite="Lax", path="/")
        return resp
    LOGIN_TENTATIVAS[ip].append(time.time())
    registrar_auditoria("LOGIN_FALHA", usuario=usuario, detalhes=f"Tentativa falha IP {ip}", request=request)
    raise HTTPException(401, "Usuário ou senha inválido")

@app.post("/api/auth/logout")
def auth_logout(request: Request):
    t = request.cookies.get("sc_token") or request.headers.get("x-token") or ""
    if t and t in TOKENS_VALIDOS:
        TOKENS_VALIDOS.pop(t, None)
        save_tokens()
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(key="sc_token", path="/")
    return resp

@app.get("/api/auth/verificar")
def auth_verificar(token: str = Depends(requer_auth)):
    dados = TOKENS_VALIDOS.get(token, {})
    return {"ok": True, "user": dados.get("user","admin")}

@app.post("/api/auth/verificar")
def auth_verificar_post(token: str = Depends(requer_auth)):
    dados = TOKENS_VALIDOS.get(token, {})
    return {"ok": True, "user": dados.get("user","admin")}

@app.post("/api/entregas")
async def api_entregas_compat(payload: dict, request: Request = None, api_key: dict = Depends(verificar_api_key)):
    with lock_entregas:
        dados = load_json(ARQ_DADOS, {"total_boxes":16,"lista":[],"historico":[]})
        condominio_id = str(payload.get("condominio_id","1"))
        check_api_key_condominio(request, condominio_id)
        cond_config = get_cond_config(condominio_id)
        tamanho = payload.get("tamanho","P")
        box_req, _, _ = get_box_livre(dados, condominio_id, tamanho, cond_config)
        if not box_req:
            raise HTTPException(status_code=409, detail=f"SEM_ESPACO_{tamanho}")
        existentes_cod = set(str(x.get("codigo_retirada","")) for x in dados.get("lista",[]))
        codigo_morador = ""
        for _ in range(20):
            codigo_morador = f"{secrets.randbelow(900000)+100000:06d}"
            if codigo_morador not in existentes_cod:
                break
        # CORRIGIDO: protocolo sempre gerado no servidor, nunca aceita do frontend
        protocolo_entregador = f"SC-ENT-{condominio_id}-{int(time.time())}-{secrets.token_hex(3).upper()}"
        nova = {
            "box": str(box_req).zfill(2),
            "bloco": payload.get("bloco",""),
            "apartamento": payload.get("apartamento") or payload.get("apto",""),
            "codigo": codigo_morador,
            "codigo_retirada": codigo_morador,
            "qr_code": f"SC-RET-{secrets.token_hex(6).upper()}",
            "protocolo": protocolo_entregador,
            "data": payload.get("data") or now_brt().strftime("%d/%m/%Y"),
            "hora": payload.get("hora") or now_brt().strftime("%H:%M"),
            "created_at": payload.get("data_hora") or now_brt().isoformat(),
            "expira_em": (now_brt() + timedelta(hours=72)).isoformat(),
            "condominio_id": condominio_id,
            "qr_valido": True
        }
        dados["lista"].append(nova)
        save_json(ARQ_DADOS, dados)
        registrar_auditoria("ENTREGA_API", detalhes=nova["protocolo"], request=request)
        return {"ok": True, "protocolo": nova["protocolo"], "box": nova["box"], "bloco": nova["bloco"]}
        
@app.post("/api/retiradas")
async def api_retiradas_compat(payload: dict, request: Request = None, api_key: dict = Depends(verificar_api_key)):
    dados = load_json(ARQ_DADOS, {"total_boxes":16,"lista":[],"historico":[]})
    codigo = str(payload.get("protocolo") or payload.get("codigo") or "").strip()
    if codigo.startswith("SC-") and not codigo.startswith("SC-RET-"):
        raise HTTPException(status_code=403, detail="Protocolo não abre box")
    # PASSO C - Trava se o payload já vier com condominio_id
    cond_payload = str(payload.get("condominio_id","") or "")
    if cond_payload:
        check_api_key_condominio(request, cond_payload)
    achado = None
    for item in dados.get("lista",[]):
        if str(item.get("codigo_retirada"))==codigo or str(item.get("codigo"))==codigo or str(item.get("qr_code"))==codigo:
            achado = item
            break
    if achado:
        # PASSO C - Trava pelo condomínio real da entrega encontrada
        check_api_key_condominio(request, str(achado.get("condominio_id","")))
        # ALTERADO - NÃO tira da lista aqui mais, só joga na fila
        # Quem tira é o ESP32 no /confirmar
        if achado.get("status") == "AGUARDANDO_CONFIRMACAO_PORTA":
            raise HTTPException(status_code=409, detail="Retirada já em andamento, aguarde confirmação da porta")
        achado["status"] = "AGUARDANDO_CONFIRMACAO_PORTA"
        nonce = f"RET-API-{achado.get('condominio_id')}-{achado.get('box')}-{int(time.time())}-{secrets.token_hex(3).upper()}"
        achado["nonce_retirada"] = nonce
        _FILA_ABERTURA.append({
            "box": str(achado.get("box")).zfill(2),
            "condominio_id": str(achado.get("condominio_id")),
            "nonce": nonce,
            "origem": "RETIRADA_API",
            "lado": "V",
            "acao": "RETIRADA",
            "criado_em": now_brt().isoformat(),
        })
        save_json(ARQ_DADOS, dados)
        registrar_auditoria("RETIRADA_API_SOLICITADA", detalhes=f"Box {achado.get('box')} Nonce {nonce}", request=request)
        return {"ok": True, "box": achado["box"], "nonce": nonce, "aguardando_confirmacao": True}
    raise HTTPException(404, "Código não encontrado")

def get_app_users():
    return load_json(ARQ_APP_USERS, [])

def save_app_users(data):
    save_json(ARQ_APP_USERS, data)

def verificar_app_token(request: Request, authorization: str = Header(None)):
    token = ""
    if authorization and "Bearer" in authorization:
        token = authorization.replace("Bearer ","").strip()
    if not token:
        token = request.headers.get("x-token") or ""
    if not token:
        raise HTTPException(401, "Token do App obrigatório")
    try:
        return jwt.decode(token, SECRET_JWT, algorithms=["HS256"])
    except Exception:
        raise HTTPException(401, "Token App inválido")
        
@app.post("/api/app/auth/login")
def app_login(payload: dict, request: Request):
    condominio = str(payload.get("condominio","1"))
    bloco = str(payload.get("bloco","")).strip()
    apto = str(payload.get("apto","")).strip()
    senha = str(payload.get("senha","")).strip()
    mors = load_json(ARQ_MORS, [])
    mor = next((m for m in mors if str(m.get("condominio"))==condominio and str(m.get("bloco")).lower()==bloco.lower() and str(m.get("apto") or m.get("apartamento","")).lower()==apto.lower()), None)
    if not mor:
        raise HTTPException(401, "Morador não encontrado")
    users = get_app_users()
    u = next((x for x in users if x.get("condominio")==condominio and x.get("bloco")==bloco and x.get("apto")==apto), None)
    if not u:
        raise HTTPException(401, "Conta de app não cadastrada. Solicite ao síndico")
    if not u.get("senha_hash") and not u.get("senha"):
        raise HTTPException(401, "Senha não configurada. Solicite reset ao síndico")
    senha_ok = False
    if u.get("senha_hash"):
        senha_ok = verificar_senha(u["senha_hash"], senha)
    elif u.get("senha"):
        senha_ok = u.get("senha") == senha
        if senha_ok:
            u["senha_hash"] = hash_senha(senha)
            del u["senha"]
            save_app_users(users)
    if not senha_ok:
        registrar_auditoria("LOGIN_APP_FALHA", usuario=bloco+"/"+apto, condominio_id=condominio, request=request)
        raise HTTPException(401, "Senha inválida")
    role = u.get("role","morador")
    token = jwt.encode({"sub": f"{condominio}-{bloco}-{apto}", "condominio": condominio, "bloco": bloco, "apto": apto, "role": role, "nome": mor["nome"], "exp": now_brt()+timedelta(days=30)}, SECRET_JWT, algorithm="HS256")
    registrar_auditoria("LOGIN_APP", usuario=mor["nome"], condominio_id=condominio, request=request)
    return {"ok": True, "token": token, "user": {"nome": mor["nome"], "role": role, "condominio": condominio, "bloco": bloco, "apto": apto}}

@app.get("/api/app/relatorios")
def app_relatorios(token_data: dict = Depends(verificar_app_token)):
    dados = load_json(ARQ_DADOS, {"lista":[],"historico":[]})
    bloco=token_data.get("bloco",""); apto=token_data.get("apto","")
    condominio=token_data.get("condominio","")
    role=token_data.get("role","morador")
    todas = dados.get("lista",[])+dados.get("historico",[])
    # SEMPRE filtra por condomínio do token, nunca por parâmetro
    todas = [x for x in todas if str(x.get("condominio_id"))==str(condominio)]
    if role=="morador":
        filtradas=[x for x in todas if str(x.get("bloco","")).lower()==bloco.lower() and str(x.get("apartamento") or "").lower()==apto.lower()]
    else:
        # operador/síndico só vê o próprio condomínio também
        filtradas=todas
    return filtradas[::-1][:200]

@app.get("/app", response_class=HTMLResponse)
def app_page(): return no_cache_html(get_path("app.html"))

def _get_cache_ia(k):
    dados = load_json(ARQ_CACHE_IA, {})
    item = dados.get(k)
    if item and time.time()-item.get("ts",0)<300: return item.get("data")
    return None
def _set_cache_ia(k, data):
    cache = load_json(ARQ_CACHE_IA, {}); cache[k]={"ts":time.time(),"data":data}; save_json(ARQ_CACHE_IA,cache)

@app.get("/api/ia/lotacao-24h")
def ia_lotacao_24h(condominio: str = "1", token: str = Depends(requer_auth_opcional)):
    cached = _get_cache_ia("lotacao_"+condominio)
    if cached:
        return cached
    raw = load_json(ARQ_DADOS, {"lista":[],"historico":[]})
    conds = load_json(ARQ_CONDS, [])
    if str(condominio) == "1":
        lista = raw.get("lista", [])
        total_util = 0
        for c in conds:
            if str(c.get("id")) == "1":
                continue
            try:
                total_util += int(c.get("total_util") or c.get("total_boxes") or 0)
            except:
                pass
        if not total_util:
            total_util = int(raw.get("total_boxes", 16))
    else:
        lista = [x for x in raw.get("lista", []) if str(x.get("condominio_id")) == str(condominio)]
        c_target = next((c for c in conds if str(c.get("id")) == str(condominio)), None)
        total_util = int(c_target.get("total_util") or c_target.get("total_boxes") or 16) if c_target else int(raw.get("total_boxes", 16))
    ocupados = len(lista)
    perc = int(ocupados / total_util * 100) if total_util else 0
    # Atrasados de verdade - mais de 72h sem retirar
    atrasados = []
    alertas = []
    agora = now_brt()
    for item in lista:
        try:
            created_str = item.get("created_at", "")
            if not created_str:
                continue
            try:
                created = datetime.fromisoformat(created_str)
            except:
                created = datetime.strptime(created_str, "%Y-%m-%dT%H:%M:%S")
            if created.tzinfo is None:
                created = created.replace(tzinfo=BRT)
            horas = (agora - created).total_seconds() / 3600
            if horas > 72:
                atrasados.append(item)
                alertas.append({
                    "box": item.get("box"),
                    "bloco": item.get("bloco"),
                    "apartamento": item.get("apartamento"),
                    "horas": round(horas, 1),
                    "protocolo": item.get("protocolo"),
                })
        except:
            pass
    # Previsão real - média simples: se lotou 10% nas últimas 24h, projeta +10%
    # Sem inventar +15. Se não tem histórico, previsão = ocupação atual
    previsao = perc
    try:
        hist = raw.get("historico", [])
        ultimas_24h = 0
        for h in hist:
            try:
                dt = datetime.fromisoformat(h.get("created_at", ""))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=BRT)
                if (agora - dt).total_seconds() < 86400:
                    ultimas_24h += 1
            except:
                pass
        if total_util:
            previsao = min(100, perc + int(ultimas_24h / total_util * 100))
    except:
        pass
    resultado = {
        "condominio": condominio,
        "total_util": total_util,
        "ocupados": ocupados,
        "livres": max(0, total_util - ocupados),
        "ocupacao_percent": perc,
        "previsao_percent": previsao,
        "total_atrasados": len(atrasados),
        "atrasados": atrasados[:20],
        "alertas_24h": alertas[:20],
        "atualizado": now_brt().isoformat(),
        "versao": "v5.8.5-tablet-ocupa-real",
    }
    _set_cache_ia("lotacao_"+condominio, resultado)
    return resultado

@app.post("/api/admin/abrir-box/{box_id}")
def abrir_box_remoto(box_id: str, payload: dict, request: Request, token: str = Depends(requer_auth)):
    box_id = str(box_id).zfill(2)
    if not box_id.isdigit() or not 1 <= int(box_id) <= 32:
        raise HTTPException(400, "Box inválido")
    if box_id in BOXES_TABLET_RESERVADOS:
        raise HTTPException(400, "Box 03 é do tablet, não pode abrir remotamente - trava dupla face")
    # OBRIGATÓRIO - sem isso abre Box de outro condomínio
    condominio_id = str((payload or {}).get("condominio_id") or request.query_params.get("condominio_id") or "").strip()
    if not condominio_id or condominio_id == "1":
        raise HTTPException(400, "Informe condominio_id real. '1' não é permitido.")
    # Confere se existe entrega ativa NESSE condomínio NESSE box
    # ADMIN PODE ABRIR MESMO SEM ENTREGA - manutenção / emergência
    # Ex: morador abriu com QR e esqueceu encomenda dentro
    dados = load_json(ARQ_DADOS, {"total_boxes":16,"lista":[],"historico":[]})
    achado = None
    for item in dados.get("lista", []):
        if str(item.get("condominio_id")) == condominio_id and str(item.get("box")).zfill(2) == box_id:
            achado = item
            break
    motivo = str((payload or {}).get("motivo") or "MANUTENCAO").strip().upper()
    if not achado:
        motivo = "MANUTENCAO_SEM_ENTREGA"

    # CORRIGIDO ETAPA 1 - Comando padronizado igual tablet / ESP32
    # Se tem entrega -> ENTREGA (só abre, não retira)
    # Se não tem entrega -> MANUTENCAO (só abre, não mexe na lista)
    if achado:
        acao_padrao = "ENTREGA"
        lado_padrao = "F"
    else:
        acao_padrao = "MANUTENCAO"
        lado_padrao = "F"

    # Joga na fila - NÃO marca como retirado ainda, ESP32 confirma depois
    nonce = f"ADMIN-{condominio_id}-{box_id}-{int(time.time())}-{secrets.token_hex(3).upper()}"
    _FILA_ABERTURA.append({
        "box": box_id,
        "condominio_id": condominio_id,
        "nonce": nonce,
        "origem": "ADMIN_REMOTO",
        "motivo": motivo,
        "lado": lado_padrao,
        "acao": acao_padrao,
        "sem_entrega": not bool(achado),
        "criado_em": now_brt().isoformat(),
    })
    registrar_auditoria("ABERTURA_REMOTA_ADMIN", usuario=TOKENS_VALIDOS.get(token,{}).get("user","admin"), detalhes=f"Abertura remota Box {box_id} Cond {condominio_id} Motivo {motivo} Acao {acao_padrao} Lado {lado_padrao} SemEntrega={not bool(achado)} Nonce {nonce}", condominio_id=condominio_id, request=request)
    return {"ok": True, "box": box_id, "condominio_id": condominio_id, "nonce": nonce, "lado": lado_padrao, "acao": acao_padrao, "sem_entrega": not bool(achado), "msg": f"Comando na fila - Box {box_id} Cond {condominio_id} {'(sem entrega - manutencao)' if not achado else ''}"}

@app.post("/api/condominios/{cond_id}/abrir-box")
def abrir_box_por_condominio(cond_id: str, payload: dict, request: Request, token: str = Depends(requer_auth)):
    box = str(payload.get("box") or payload.get("box_id") or "").strip()
    if not box:
        raise HTTPException(400, "Informe o box")
    payload_admin = {"condominio_id": str(cond_id), "box": box, "motivo": payload.get("motivo", "ABERTURA_REMOTA_ADMIN")}
    return abrir_box_remoto(box, payload_admin, request, token)
    
# ESP32 lê - já deixa pronto pra quinta
@app.get("/api/esp32/poll")
def esp32_poll(request: Request, condominio_id: str = Query(None), _esp: bool = Depends(verificar_esp32_token)):
    cond_esp = getattr(request.state, "esp32_condominio_id", "") or ""
    if not cond_esp:
        raise HTTPException(400, "Header x-condominio-id obrigatorio no ESP")
    if condominio_id and str(condominio_id) != cond_esp:
        raise HTTPException(403, "condominio_id da query diferente do header do ESP")
    condominio_id = cond_esp
    agora = time.time()
    # Limpa só expirados > 60s, sem quebrar por data inválida
    nova_fila = []
    for c in list(_FILA_ABERTURA):
        try:
            criado = datetime.fromisoformat(c["criado_em"]).timestamp()
        except:
            criado = agora
        if agora - criado < 60:
            nova_fila.append(c)
    _FILA_ABERTURA[:] = nova_fila
    cmds = [c for c in _FILA_ABERTURA if str(c["condominio_id"]) == str(condominio_id)]
    return {"ok": True, "comandos": cmds}

@app.post("/api/esp32/confirmar")
def esp32_confirmar(payload: dict, request: Request, _esp: bool = Depends(verificar_esp32_token)):
    cond_esp = getattr(request.state, "esp32_condominio_id", "") or ""
    if not cond_esp:
        raise HTTPException(400, "Header x-condominio-id obrigatorio no ESP")
    nonce = str(payload.get("nonce") or "").strip()
    if not nonce:
        raise HTTPException(400, "Nonce obrigatório")
    porta_aberta = payload.get("porta_aberta")
    sensor = payload.get("sensor_abertura")
    reed = payload.get("reed")
    prova = porta_aberta is True or sensor is True or reed is True
    if not prova:
        raise HTTPException(400, "Prova fisica obrigatoria: ESP precisa enviar porta_aberta=true ou sensor_abertura=true")
    agora_ts = time.time()
    for n in list(_NONCES_EXPIRACAO.keys()):
        if _NONCES_EXPIRACAO[n] < agora_ts:
            _NONCES_USADOS.discard(n)
            del _NONCES_EXPIRACAO[n]
    if nonce in _NONCES_USADOS:
        raise HTTPException(409, "Nonce já utilizado - replay bloqueado")
    for c in list(_FILA_ABERTURA):
        if c["nonce"] == nonce:
            if str(c["condominio_id"]) != cond_esp:
                raise HTTPException(403, "Nonce de outro condominio")
            # ALTERADO - rejeita comando expirado > 60s
            try:
                criado = datetime.fromisoformat(c.get("criado_em", "")).timestamp()
            except:
                criado = agora_ts
            if agora_ts - criado > 60:
                _FILA_ABERTURA.remove(c)
                raise HTTPException(410, "Comando expirado - peça novo comando")
            _FILA_ABERTURA.remove(c)
            _NONCES_USADOS.add(nonce)
            _NONCES_EXPIRACAO[nonce] = agora_ts + 600
            acao_cmd = str(c.get("acao") or "").upper()
            if acao_cmd == "RETIRADA":
                dados = load_json(ARQ_DADOS, {"total_boxes":16,"lista":[],"historico":[]})
                nova_lista = []
                achado = None
                for item in dados.get("lista", []):
                    if str(item.get("condominio_id")) == str(c["condominio_id"]) and str(item.get("box")).zfill(2) == str(c["box"]).zfill(2) and not achado:
                        achado = item
                    else:
                        nova_lista.append(item)
                if achado:
                    achado["data_retirada"] = now_brt().strftime("%d/%m/%Y")
                    achado["hora_retirada"] = now_brt().strftime("%H:%M")
                    achado["retirada_por"] = "ESP32_RETIRADA"
                    achado["status"] = "RETIRADO"
                    achado["prova_fisica"] = {"porta_aberta": porta_aberta, "sensor_abertura": sensor, "reed": reed}
                    dados["lista"] = nova_lista
                    dados["historico"].append(achado)
                    save_json(ARQ_DADOS, dados)
            registrar_auditoria("ABERTURA_ESP32_CONFIRMADA", detalhes=f"Box {c['box']} Cond {c['condominio_id']} Acao {acao_cmd} Nonce {nonce} Prova {porta_aberta}/{sensor}/{reed}", condominio_id=c["condominio_id"], request=request)
            return {"ok": True, "box": c["box"], "acao": acao_cmd}
    raise HTTPException(404, "Nonce não encontrado ou expirado")

@app.post("/api/condfy/sync")
def condfy_sync(payload: dict, request: Request, api_key: dict = Depends(verificar_api_key)):
    condominio_id=str(payload.get("condominio_id","")); blocos_api=payload.get("blocos",[]); moradores_api=payload.get("moradores",[])
    check_api_key_condominio(request, condominio_id)
    conds=load_json(ARQ_CONDS, [])
    for c in conds:
        if str(c["id"])==condominio_id and blocos_api:
            c["blocos"]=blocos_api; c["tem_blocos"]=True; c["qtd_blocos"]=len(blocos_api); c["atualizado_em"]=now_brt().isoformat(); save_json(ARQ_CONDS, conds); break
    if moradores_api:
        mors=load_json(ARQ_MORS, []); mors=[m for m in mors if str(m.get("condominio"))!=condominio_id]
        for m in moradores_api: mors.append({"id": str(uuid.uuid4())[:8],"nome": m.get("nome",""),"bloco": m.get("bloco",""),"apto": str(m.get("apto","")),"condominio": condominio_id})
        save_json(ARQ_MORS, mors)
    registrar_auditoria("CONDFY_SYNC", detalhes=f"Cond {condominio_id} Blocos:{len(blocos_api)}", condominio_id=condominio_id, request=request)
    return {"ok": True, "blocos": blocos_api, "moradores": len(moradores_api)}

@app.get("/api/condfy/sync")
def condfy_sync_status(condominio: str = Query(...), token: str = Depends(requer_auth)):
    conds = load_json(ARQ_CONDS, [])
    c = next((x for x in conds if str(x.get("id")) == condominio), None)
    if not c:
        raise HTTPException(404, "Condominio nao encontrado")
    mors = load_json(ARQ_MORS, [])
    qtd = len([m for m in mors if str(m.get("condominio")) == condominio])
    # NUNCA devolve c inteiro - vazava cnpj, valor_mensal, valor_instalacao, endereco
    condominio_limpo = {
        "id": c.get("id"),
        "nome": c.get("nome"),
        "codigo_armario": c.get("codigo_armario"),
        "modelo": c.get("modelo"),
        "dupla_face": bool(c.get("dupla_face")),
        "total_util": c.get("total_util"),
        "total_fisico": c.get("total_fisico"),
        "tem_blocos": bool(c.get("tem_blocos")),
        "qtd_blocos": c.get("qtd_blocos"),
        "blocos": c.get("blocos", []),
        "status": c.get("status"),
        "criado_em": c.get("criado_em"),
    }
    return {"condominio": condominio_limpo, "blocos": c.get("blocos", []), "qtd_moradores": qtd}
    
@app.post("/api/whitelabel/save")
def whitelabel_save(payload: dict, request: Request, token: str = Depends(requer_auth)):
    dados=load_json(ARQ_WHITELABEL, {}); logo=payload.get("logo","")
    if logo and logo.startswith("data:") and len(logo)>500*1024: raise HTTPException(400, "Logo base64 >500KB use URL S3 - ITEM 8")
    dados.update({"logo": logo,"logo_url": payload.get("logo_url",""),"cor_primaria": payload.get("cor_primaria",""),"nome_empresa": payload.get("nome_empresa",""),"atualizado_em": now_brt().isoformat()})
    save_json(ARQ_WHITELABEL, dados); return {"ok": True, "whitelabel": dados}

@app.get("/api/whitelabel/public")
def whitelabel_public():
    return load_json(ARQ_WHITELABEL, {"logo_url": "/logo.png"})

# === WHITELABEL - DEFINITIVO - GET + POST /api/whitelabel ===
# Usa requer_auth igual o /save - não inventa get_usuario_atual
# Usa MERGE - não apaga os campos do /save antigo

@app.get("/api/whitelabel")
def get_whitelabel(token: str = Depends(requer_auth)):
    dados = load_json(ARQ_WHITELABEL, {})
    if not dados:
        return {"nome": "", "nome_empresa": "", "descricao": "", "cor_fundo": "#FFFFFF", "cor_primaria": "#C10010", "cor_qr": "#000000", "cor_botao": "#C10010", "cor_frase": "#000000", "cor_sair": "#C10010", "logo_url": "/logo.png"}
    return dados

@app.post("/api/whitelabel")
async def post_whitelabel(request: Request, token: str = Depends(requer_auth)):
    novo = await request.json()
    # Aceita os 2 nomes - dashboard manda 'nome', /save manda 'nome_empresa'
    if not novo.get("nome") and not novo.get("nome_empresa"):
        raise HTTPException(status_code=400, detail="Nome da marca é obrigatório")
    dados = load_json(ARQ_WHITELABEL, {})
    # MERGE - mantém o que já tinha, só atualiza o que veio
    dados.update(novo)
    dados["nome_empresa"] = novo.get("nome_empresa") or novo.get("nome") or dados.get("nome_empresa", "")
    dados["nome"] = novo.get("nome") or novo.get("nome_empresa") or dados.get("nome", "")
    dados["atualizado_em"] = now_brt().isoformat()
    dados["salvo_em"] = now_brt().isoformat()
    save_json(ARQ_WHITELABEL, dados)
    return {"ok": True, "msg": "Marca salva", "dados": dados}

@app.post("/api/validar-apto")
def validar_apto(payload: dict, request: Request, tablet: dict = Depends(verificar_tablet_token)):
    import re
    condominio_id = str(request.state.tablet_condominio_id or "").strip()
    bloco = str(payload.get("bloco") or "").strip().upper()
    apto = str(payload.get("apto") or payload.get("apartamento") or "").strip().upper()

    if not re.match(r"^[0-9]+[A-Za-z]?$|^[A-Za-z0-9\-/]+$", apto):
        raise HTTPException(400, "Formato apto invalido. Use 12, 12A, 12B")
    if not condominio_id or condominio_id == "1":
        raise HTTPException(400, "Token do tablet sem condominio_id")

    mors = load_json(ARQ_MORS, [])
    if isinstance(mors, dict):
        mors = mors.get("moradores", []) or mors.get("data", []) or []

    achado = next((m for m in mors if str(m.get("condominio_id") or m.get("condominio")) == condominio_id
                   and str(m.get("bloco","")).upper() == bloco
                   and str(m.get("apto") or m.get("apartamento","")).upper() == apto), None)
    if not achado:
        raise HTTPException(404, "Morador não encontrado neste bloco/apto")
    return {"ok": True, "apto": apto, "bloco": bloco, "morador": achado.get("nome",""), "condominio_id": condominio_id}
    
@app.get("/api/comercial/vendedores")
def listar_vendedores(token: str = Depends(requer_auth)):
    return load_json(ARQ_VENDEDORES, [])

@app.post("/api/comercial/venda")
def registrar_venda(payload: dict, request: Request, token: str = Depends(requer_auth)):
    comercial=load_json(ARQ_COMERCIAL, []); vends=load_json(ARQ_VENDEDORES, []); valor=float(payload.get("valor",0) or 0)
    if valor==0: raise HTTPException(400, "Valor nao pode ser 0 - BUG R$ 0,00 ITEM 4")
    vid=payload.get("vendedor_id"); vend=next((v for v in vends if str(v["id"])==str(vid)), None); comissao=0
    if vend: comissao=valor*(vend.get("comissao_percent",10)/100); vend["vendas"]=vend.get("vendas",0)+1; vend["comissao_total"]=float(vend.get("comissao_total",0))+comissao; save_json(ARQ_VENDEDORES, vends)
    venda={"id": str(uuid.uuid4())[:8], "condominio": payload.get("condominio",""), "valor": valor, "vendedor_id": vid, "comissao": comissao, "criado_em": now_brt().isoformat()}; comercial.append(venda); save_json(ARQ_COMERCIAL, comercial); return {"ok": True, "venda": venda}

@app.post("/api/tablet/heartbeat")
def tablet_heartbeat(payload: dict, request: Request, tablet: dict = Depends(verificar_tablet_token)):
    status = load_json(ARQ_TABLET_STATUS, {})
    cond_id = request.state.tablet_condominio_id
    status[cond_id] = {
        "ultimo_heartbeat": now_brt().isoformat(),
        "tablet_id": request.state.tablet_id or payload.get("tablet_id", ""),
        "bateria": payload.get("bateria", 0),
        "online": True,
        "ip": request.client.host if request.client else ""
    }
    save_json(ARQ_TABLET_STATUS, status)
    return {"ok": True}
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
