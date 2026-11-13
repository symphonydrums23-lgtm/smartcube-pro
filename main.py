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

import pytz
BRT = pytz.timezone('America/Sao_Paulo')
def now_brt():
    return datetime.now(BRT)
def now_brt_str(fmt="%d/%m/%Y %H:%M:%S"):
    return now_brt().strftime(fmt)

ARQ_COMERCIAL = "comercial.json"
ARQ_CONTRATOS = "contratos.json"
ARQ_CHAMADOS = "chamados.json"
ARQ_RECLAMACOES = "reclamacoes.json"
ARQ_VENDEDORES = "vendedores.json"
ARQ_WHITELABEL = "whitelabel.json"
ARQ_TABLET_STATUS = "tablet_status.json"

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
BOXES_TABLET_RESERVADOS = {"03", "3", "03F", "03V", "03_F", "03_V", "03-F", "03-V"}

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
            if datetime.now() > dados["expires"]:
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
    return k

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
@app.get("/api/health")
def health():
    return {"ok": True, "status": "online", "versao": "v5.8.5-build-11-11-2026-API-LIVRE-CONDFY", "time": datetime.now().isoformat()}

@app.get("/api/auditoria")
def listar_auditoria(request: Request, token: str = Depends(requer_auth)):
    logs = load_json(ARQ_AUDIT, [])
    return logs[::-1][:200]

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
    # ... seu código atual gera numeros ...
    boxes = []
    for b in todos_numeros:
        tam = "G" if b in g_list else "M" if b in m_list else "P"
        if dupla_face:
            boxes.append({"numero": f"{b}-F", "tamanho": tam, "face": "F"})
            boxes.append({"numero": f"{b}-V", "tamanho": tam, "face": "V"})
        else:
            boxes.append({"numero": b, "tamanho": tam})
    return boxes[:total_util] if not dupla_face else boxes
def get_cond_config(cond_id):
    conds = load_json(ARQ_CONDS, [])
    for c in conds:
        if str(c["id"])==str(cond_id):
            return c
    return None

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
    return conds

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
    conds = load_json(ARQ_CONDS, []); mors = load_json(ARQ_MORS, [])
    conds = garantir_codigo_armario(conds)
    if str(cond_id) == "1":
        total_boxes = 16
        try:
            soma = sum(int(c.get("total_util", c.get("total_boxes",0))) for c in conds if str(c.get("id"))!="1")
            if soma>0: total_boxes=soma
        except: pass
        return {"id":"1","nome":"Todos condomínios","total_boxes":total_boxes,"qtd_moradores":len(mors),"status":"ativo"}
    for c in conds:
        if str(c["id"])==str(cond_id):
            c["qtd_moradores"] = len([m for m in mors if str(m.get("condominio"))==str(cond_id)])
            return c
    raise HTTPException(404, "Condomínio não encontrado")

@app.post("/api/tablet/entrega")
async def tablet_entrega(payload: dict, request: Request = None):
    with FILE_LOCK:
        dados = load_json(ARQ_DADOS, {"total_boxes":16,"lista":[],"historico":[]})
        condominio_id = str(payload.get("condominio_id","1"))
        tamanho_solicitado = str(payload.get("tamanho","P")).upper() or "P"
        cond_config = get_cond_config(condominio_id)
        if condominio_id=="1":
            raise HTTPException(status_code=400, detail="Tablet não travado. Configure o condomínio no tablet.")
        box_escolhido, tamanho_final, foi_upgrade = None, tamanho_solicitado, False
        box_escolhido, _, foi_upgrade = get_box_livre(dados, condominio_id, tamanho_solicitado, cond_config)
        if not box_escolhido:
            raise HTTPException(status_code=409, detail=f"SEM_ESPACO_{tamanho_solicitado}")
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
        protocolo_entregador = payload.get("protocolo") or f"SC-{secrets.randbelow(900000)+100000}"
        nova = {
            "box": str(box_escolhido).zfill(2),
            "bloco": payload.get("bloco",""),
            "apartamento": payload.get("apartamento") or payload.get("apto",""),
            "codigo": codigo_morador,
            "codigo_retirada": codigo_morador,
            "qr_code": qr_morador,
            "protocolo": protocolo_entregador,
            "data": datetime.now().strftime("%d/%m/%Y"),
            "hora": datetime.now().strftime("%H:%M"),
            "nome": payload.get("nome",""),
            "created_at": datetime.now().isoformat(),
            "condominio_id": condominio_id,
            "tamanho_solicitado": tamanho_solicitado,
            "tamanho_real": tamanho_final if not foi_upgrade else get_box_livre(dados, condominio_id, tamanho_solicitado, cond_config)[1],
            "upgrade": foi_upgrade,
            "qr_valido": True,
            "expira_em": (datetime.now()+timedelta(hours=72)).isoformat()
        }
        if foi_upgrade:
            for bx in (cond_config.get("boxes_lista",[]) if cond_config else []):
                if bx["numero"]==box_escolhido:
                    nova["tamanho_real"]=bx["tamanho"]
                    break
        else:
            nova["tamanho_real"]=tamanho_solicitado
        dados["lista"].append(nova)
        save_json(ARQ_DADOS, dados)
        registrar_auditoria("ENTREGA_TABLET", detalhes=f"Box {nova['box']} Bloco:{nova['bloco']} Apto:{nova['apartamento']} {tamanho_solicitado}->{nova['tamanho_real']} Prot {nova['protocolo']} Cond {condominio_id}", condominio_id=condominio_id, request=request)
        return {"ok": True, "protocolo": nova["protocolo"], "box": nova["box"], "codigo": codigo_morador, "qr_code": qr_morador, "tamanho_solicitado": tamanho_solicitado, "tamanho_real": nova["tamanho_real"], "upgrade": foi_upgrade, "bloco": nova["bloco"], "apartamento": nova["apartamento"]}

@app.post("/api/tablet/retirada")
async def tablet_retirada(payload: dict, request: Request = None):
    with FILE_LOCK:
        dados = load_json(ARQ_DADOS, {"total_boxes":16,"lista":[],"historico":[]})
        codigo = str(payload.get("codigo","")).strip()
        if not codigo:
            raise HTTPException(status_code=400, detail="Código obrigatório")
        if codigo.startswith("SC-") and not codigo.startswith("SC-RET-"):
            raise HTTPException(status_code=403, detail="Protocolo de entregador não abre box. Use código do morador.")
        achado = None
        nova_lista = []
        for item in dados.get("lista",[]):
            if str(item.get("codigo_retirada"))==codigo or str(item.get("codigo"))==codigo or str(item.get("qr_code"))==codigo:
                achado=item
            else:
                nova_lista.append(item)
        if not achado:
            raise HTTPException(status_code=404, detail="Código não encontrado ou já utilizado")
        try:
            expira = datetime.fromisoformat(achado.get("expira_em",""))
            if datetime.now() > expira:
                achado["qr_valido"]=False
                dados["lista"]=nova_lista
                dados["historico"].append(achado)
                save_json(ARQ_DADOS, dados)
                raise HTTPException(status_code=410, detail="QR Code expirado")
        except HTTPException:
            raise
        except:
            pass
        achado["data_retirada"] = datetime.now().strftime("%d/%m/%Y")
        achado["hora_retirada"] = datetime.now().strftime("%H:%M")
        achado["qr_valido"] = False
        dados["lista"]=nova_lista
        dados["historico"].append(achado)
        save_json(ARQ_DADOS, dados)
        registrar_auditoria("RETIRADA_TABLET", detalhes=f"Box {achado['box']} Bloco:{achado.get('bloco')} Apto:{achado.get('apartamento')} Cod morador usado", request=request)
        return {"ok": True, "box": achado["box"], "bloco": achado.get("bloco"), "apartamento": achado.get("apartamento")}
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
            c["atualizado_em"]=datetime.now().isoformat()
            save_json(ARQ_CONDS, conds)
            return c
    raise HTTPException(404)

@app.delete("/api/condominios")
def deletar_cond(id: str = Query(...), request: Request = None, token: str = Depends(requer_auth)):
    conds = load_json(ARQ_CONDS, [])
    conds = [c for c in conds if str(c["id"])!=str(id)]
    save_json(ARQ_CONDS, conds)
    registrar_auditoria("EXCLUIU_CONDOMINIO", detalhes=f"Excluido id {id} via DELETE antigo", condominio_id=id, request=request)
    return {"ok": True}

@app.delete("/api/condominios/{cond_id}")
def deletar_cond_path(cond_id: str, request: Request = None, token: str = Depends(requer_auth)):
    conds = load_json(ARQ_CONDS, [])
    cond_alvo = next((c for c in conds if str(c["id"]) == str(cond_id)), None)
    if not cond_alvo:
        raise HTTPException(status_code=404, detail="Condomínio não encontrado")
    conds = [c for c in conds if str(c["id"]) != str(cond_id)]
    save_json(ARQ_CONDS, conds)
    registrar_auditoria("EXCLUIU_CONDOMINIO", detalhes=f"Excluido {cond_alvo.get('nome')} {cond_alvo.get('codigo_armario','')} via DELETE", condominio_id=cond_id, request=request)
    return {"ok": True}

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
        "criado_em": existente.get("criado_em") if existente else datetime.now().isoformat(),
        "atualizado_em": datetime.now().isoformat()
    }
    if existente:
        users = [u for u in users if not (str(u.get("condominio"))==condominio and str(u.get("bloco")).lower()==bloco.lower() and str(u.get("apto")).lower()==apto.lower())]
    users.append(novo_user)
    save_json(ARQ_APP_USERS, users)
    registrar_auditoria("CRIOU_OPERADOR", detalhes=f"Operador {nome} {bloco}/{apto} Cond {condominio}", condominio_id=condominio, request=request)
    return {"ok": True, "usuario": novo_user}

@app.get("/api/usuarios")
def listar_usuarios(condominio: str = Query(None), token: str = Depends(requer_auth)):
    users = load_json(ARQ_APP_USERS, [])
    if condominio:
        users = [u for u in users if str(u.get("condominio"))==str(condominio)]
    return users

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
        "criado_em": datetime.now().isoformat()
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
        "criado_em": datetime.now().isoformat(),
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
    keys = [k for k in keys if str(k.get("id")) != str(key_id) and str(k.get("api_key")) != str(key_id)]
    save_json(ARQ_KEYS, keys)
    return {"ok": True}

@app.get("/api/moradores")
def listar_mors(condominio: str = Query("1"), token: str = Depends(requer_auth)):
    mors = load_json(ARQ_MORS, [])
    if condominio!="1": return [m for m in mors if str(m.get("condominio"))==str(condominio)]
    return mors

@app.post("/api/moradores")
def criar_mor(payload: dict, request: Request = None, token: str = Depends(requer_auth)):
    nome = str(payload.get("nome","")).strip()
    if not nome:
        raise HTTPException(status_code=400, detail="Nome do morador obrigatório")
    mors = load_json(ARQ_MORS, [])
    novo = {"id": str(uuid.uuid4())[:8],"nome": nome,"bloco": payload.get("bloco",""),"apto": payload.get("apto",""),"condominio": payload.get("condominio","1")}
    mors.append(novo); save_json(ARQ_MORS, mors)
    return novo

@app.delete("/api/moradores")
def deletar_mor(id: str = Query(...), request: Request = None, token: str = Depends(requer_auth)):
    mors = load_json(ARQ_MORS, []); mors=[m for m in mors if str(m["id"])!=str(id)]
    save_json(ARQ_MORS, mors); return {"ok":True}

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
                created = BRT.localize(created)
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
        TOKENS_VALIDOS[token] = {"user": usuario,"expires": datetime.now() + timedelta(hours=8),"ip": ip}
        save_tokens()
        registrar_auditoria("LOGIN_SUCESSO", usuario=usuario, request=request)
        resp = JSONResponse({"ok": True, "token": token, "expires_in": 28800})
        resp.set_cookie(key="sc_token", value=token, httponly=True, max_age=28800, samesite="Lax", path="/")
        return resp
    LOGIN_TENTATIVAS[ip].append(time.time())
    raise HTTPException(401, "Usuário ou senha inválido")

@app.get("/api/auth/verificar")
def auth_verificar(token: str = Depends(requer_auth)):
    dados = TOKENS_VALIDOS.get(token, {})
    return {"ok": True, "user": dados.get("user","admin")}

@app.post("/api/auth/verificar")
def auth_verificar_post(token: str = Depends(requer_auth)):
    dados = TOKENS_VALIDOS.get(token, {})
    return {"ok": True, "user": dados.get("user","admin")}

@app.post("/api/entregas")
async def api_entregas_compat(payload: dict, request: Request = None, token: str = Depends(requer_auth)):
    dados = load_json(ARQ_DADOS, {"total_boxes":16,"lista":[],"historico":[]})
    condominio_id = str(payload.get("condominio_id","1"))
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
    nova = {
        "box": str(box_req).zfill(2),
        "bloco": payload.get("bloco",""),
        "apartamento": payload.get("apartamento") or payload.get("apto",""),
        "codigo": codigo_morador,
        "codigo_retirada": codigo_morador,
        "qr_code": f"SC-RET-{secrets.token_hex(6).upper()}",
        "protocolo": payload.get("protocolo") or f"SC-{secrets.randbelow(900000)+100000}",
        "data": payload.get("data") or datetime.now().strftime("%d/%m/%Y"),
        "hora": payload.get("hora") or datetime.now().strftime("%H:%M"),
        "created_at": payload.get("data_hora") or datetime.now().isoformat(),
        "condominio_id": condominio_id,
        "qr_valido": True,
        "expira_em": (datetime.now()+timedelta(hours=72)).isoformat()
    }
    dados["lista"].append(nova); save_json(ARQ_DADOS, dados)
    registrar_auditoria("ENTREGA_API", detalhes=nova["protocolo"], request=request)
    return {"ok": True, "protocolo": nova["protocolo"], "box": nova["box"], "bloco": nova["bloco"]}

@app.post("/api/retiradas")
async def api_retiradas_compat(payload: dict, request: Request = None, token: str = Depends(requer_auth)):
    dados = load_json(ARQ_DADOS, {"total_boxes":16,"lista":[],"historico":[]})
    codigo = str(payload.get("protocolo") or payload.get("codigo") or "").strip()
    if codigo.startswith("SC-") and not codigo.startswith("SC-RET-"):
        raise HTTPException(status_code=403, detail="Protocolo não abre box")
    achado=None; nova_lista=[]
    for item in dados.get("lista",[]):
        if str(item.get("codigo_retirada"))==codigo or str(item.get("codigo"))==codigo or str(item.get("qr_code"))==codigo:
            achado=item
        else:
            nova_lista.append(item)
    if achado:
        achado["qr_valido"]=False
        dados["lista"]=nova_lista; dados["historico"].append(achado); save_json(ARQ_DADOS, dados)
        registrar_auditoria("RETIRADA_API", detalhes=codigo[:3]+"***", request=request)
        return {"ok": True, "box": achado["box"]}
    raise HTTPException(404, "Código não encontrado")

def get_app_users(): return load_json(ARQ_APP_USERS, [])
def save_app_users(data): save_json(ARQ_APP_USERS, data)

def verificar_app_token(request: Request, authorization: str = Header(None)):
    token = ""
    if authorization and "Bearer" in authorization: token = authorization.replace("Bearer ","").strip()
    if not token: token = request.headers.get("x-token") or ""
    if not token: raise HTTPException(401, "Token do App obrigatório")
    try: return jwt.decode(token, SECRET_JWT, algorithms=["HS256"])
    except: raise HTTPException(401, "Token App inválido")

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
    token = jwt.encode({"sub": f"{condominio}-{bloco}-{apto}", "condominio": condominio, "bloco": bloco, "apto": apto, "role": role, "nome": mor["nome"], "exp": datetime.now()+timedelta(days=30)}, SECRET_JWT, algorithm="HS256")
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
    cached=_get_cache_ia("lotacao_"+condominio)
    if cached: return cached
    raw=load_json(ARQ_DADOS, {"lista":[],"historico":[]})
    lista = raw.get("lista",[]) if str(condominio)=="1" else [x for x in raw.get("lista",[]) if str(x.get("condominio_id"))==str(condominio)]
    perc=int(len(lista)/int(raw.get("total_boxes",16))*100) if raw.get("total_boxes") else 0
    resultado={"condominio":condominio,"ocupados":len(lista),"previsao_percent":min(100,perc+15),"total_atrasados":0,"alertas_24h":[],"atualizado":datetime.now().isoformat(),"versao":"v5.8.5-tablet-ocupa"}
    _set_cache_ia("lotacao_"+condominio, resultado)
    return resultado

@app.post("/api/admin/abrir-box/{box_id}")
def abrir_box_remoto(box_id: str, request: Request, token: str = Depends(requer_auth)):
    box_id = str(box_id).zfill(2)
    if not box_id.isdigit() or not 1 <= int(box_id) <= 32:
        raise HTTPException(400, "Box inválido")
    if box_id in BOXES_TABLET_RESERVADOS:
        raise HTTPException(400, "Box 03 é do tablet, não pode abrir remotamente - trava dupla face")
    registrar_auditoria("ABERTURA_REMOTA_ADMIN", usuario=TOKENS_VALIDOS.get(token,{}).get("user","admin"), detalhes=f"Abertura remota Box {box_id}", request=request)
    dados = load_json(ARQ_DADOS, {"total_boxes":16,"lista":[],"historico":[]})
    achado = None
    nova_lista = []
    for item in dados.get("lista",[]):
        if str(item.get("box")).zfill(2) == box_id:
            achado = item
        else:
            nova_lista.append(item)
    if achado:
        achado["data_retirada"] = datetime.now().strftime("%d/%m/%Y")
        achado["hora_retirada"] = datetime.now().strftime("%H:%M")
        achado["retirada_por"] = "ADMIN_REMOTO"
        dados["lista"] = nova_lista
        dados["historico"].append(achado)
        save_json(ARQ_DADOS, dados)
    return {"ok": True, "box": box_id, "msg": f"Comando de abertura enviado para Box {box_id} - libera frente e verso (mesma caixa física)"}

@app.post("/api/condfy/sync")
def condfy_sync(payload: dict, request: Request, token: str = Depends(requer_auth)):
    condominio_id=str(payload.get("condominio_id","")); blocos_api=payload.get("blocos",[]); moradores_api=payload.get("moradores",[])
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
    conds=load_json(ARQ_CONDS, []); c=next((x for x in conds if str(x["id"])==condominio), None)
    if not c: raise HTTPException(404, "Condominio nao encontrado")
    mors=load_json(ARQ_MORS, []); qtd=len([m for m in mors if str(m.get("condominio"))==condominio])
    return {"condominio": c, "blocos": c.get("blocos",[]), "qtd_moradores": qtd}

@app.post("/api/whitelabel/save")
def whitelabel_save(payload: dict, request: Request, token: str = Depends(requer_auth)):
    dados=load_json(ARQ_WHITELABEL, {}); logo=payload.get("logo","")
    if logo and logo.startswith("data:") and len(logo)>500*1024: raise HTTPException(400, "Logo base64 >500KB use URL S3 - ITEM 8")
    dados.update({"logo": logo,"logo_url": payload.get("logo_url",""),"cor_primaria": payload.get("cor_primaria",""),"nome_empresa": payload.get("nome_empresa",""),"atualizado_em": now_brt().isoformat()})
    save_json(ARQ_WHITELABEL, dados); return {"ok": True, "whitelabel": dados}

@app.get("/api/whitelabel/public")
def whitelabel_public():
    return load_json(ARQ_WHITELABEL, {"logo_url": "/logo.png"})

@app.post("/api/validar-apto")
def validar_apto(payload: dict):
    apto=str(payload.get("apto","")).strip()
    import re
    if not re.match(r"^[0-9]+[A-Za-z]?$|^[A-Za-z0-9\-/]+$", apto):
        raise HTTPException(400, "Formato apto invalido. Use 12, 12A, 12B")
    return {"ok": True, "apto": apto.upper()}

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
def tablet_heartbeat(payload: dict, request: Request):
    status=load_json(ARQ_TABLET_STATUS, {}); cond_id=str(payload.get("condominio_id","1")); status[cond_id]={"ultimo_heartbeat": now_brt().isoformat(), "tablet_id": payload.get("tablet_id",""), "bateria": payload.get("bateria",0), "online": True, "ip": request.client.host if request.client else ""}; save_json(ARQ_TABLET_STATUS, status); return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
