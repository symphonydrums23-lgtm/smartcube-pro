from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query, Request, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from datetime import datetime, timedelta
import json, os, secrets, uuid, csv, io, time, jwt, threading, hashlib, binascii
from collections import defaultdict
from dotenv import load_dotenv
load_dotenv()

# ========= SEGURANCA - ETAPA 2 CORRIGIDA - SEM FALLBACK =========
SECRET_JWT = os.getenv("SECRET_JWT")
if not SECRET_JWT or len(SECRET_JWT) < 32:
    raise RuntimeError("SECRET_JWT ausente ou fraco (<32 chars). Defina no .env")

ADMIN_USER = os.getenv("SMARTCUBE_USER")
ADMIN_PASS = os.getenv("SMARTCUBE_ADMIN_PASS")
if not ADMIN_USER or not ADMIN_PASS:
    raise RuntimeError("SMARTCUBE_USER e SMARTCUBE_ADMIN_PASS obrigatórios no .env")

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:5000,http://127.0.0.1:5000").split(",")
ALLOWED_ORIGINS = [o.strip() for o in ALLOWED_ORIGINS if o.strip()]

app = FastAPI(title="SmartCube API v5.6")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,  # ETAPA 2: NAO MAIS "*"
    allow_credentials=True,
    allow_methods=["GET","POST","PUT","DELETE"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")

FILE_LOCK = threading.Lock()

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

def no_cache_html(path):
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f: content = f.read()
        return HTMLResponse(content=content, headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"})
    return HTMLResponse(f"<h1>Arquivo nao encontrado: {path}</h1>", status_code=404)

# ========= HASH SENHA - ETAPA 2 =========
def hash_senha(senha: str) -> str:
    salt = secrets.token_bytes(16)
    pwdhash = hashlib.pbkdf2_hmac('sha256', senha.encode('utf-8'), salt, 100000)
    return binascii.hexlify(salt + pwdhash).decode('ascii')

def verificar_senha(stored: str, provided: str) -> bool:
    try:
        if not stored or not provided: return False
        # compat: se ainda for texto puro antigo
        if len(stored) < 64 and stored == provided: return True
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
        if datetime.now() > dados["expires"]:
            TOKENS_VALIDOS.pop(token, None); save_tokens(); return False
    except Exception:
        return False
    return True

def requer_auth(request: Request, authorization: str = Header(None), token: str = Query(None)):
    t = ""
    if authorization and "Bearer" in authorization: t = authorization.replace("Bearer ","").strip()
    if not t: t = token or ""
    if not t: t = request.cookies.get("sc_token") or request.query_params.get("token") or request.headers.get("x-token") or ""
    if not t or not is_token_valid(t):
        raise HTTPException(status_code=401, detail="Token inválido")
    return t

def requer_auth_opcional(request: Request, authorization: str = Header(None), token: str = Query(None)):
    t = ""
    if authorization and "Bearer" in authorization: t = authorization.replace("Bearer ","").strip()
    if not t: t = token or ""
    if not t: t = request.cookies.get("sc_token") or request.query_params.get("token") or request.headers.get("x-token") or ""
    if t and not is_token_valid(t):
        raise HTTPException(status_code=401, detail="Token inválido")
    return t or "tablet_public"

def check_rate_limit(request: Request):
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    LOGIN_TENTATIVAS[ip] = [x for x in LOGIN_TENTATIVAS[ip] if now - x < 900]
    if len(LOGIN_TENTATIVAS[ip]) >= 10:
        raise HTTPException(429, "Muitas tentativas. Aguarde 15 min")
    return ip

# ETAPA 2 BUG CORRIGIDO: save_json FORA do if
def registrar_auditoria(acao, usuario="sistema", detalhes="", condominio_id="", request: Request = None):
    logs = load_json(ARQ_AUDIT, [])
    ip = "sistema"
    if request and request.client: ip = request.client.host
    logs.append({
        "id": str(uuid.uuid4())[:8],
        "data": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "timestamp": datetime.now().isoformat(),
        "acao": acao,"usuario": usuario,"detalhes": detalhes,
        "condominio_id": condominio_id,"ip": ip
    })
    if len(logs) > 1000:
        logs = logs[-1000:]
    save_json(ARQ_AUDIT, logs)  # SEMPRE SALVA

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
    if not token: token = request.cookies.get("sc_token") or request.query_params.get("token") or request.headers.get("x-token") or ""
    if not token or not is_token_valid(token): return RedirectResponse(url="/login", status_code=302)
    try: return templates.TemplateResponse("dashboard.html", {"request": request})
    except: return no_cache_html(get_path("dashboard.html"))

def get_box_livre(dados):
    ocupados = set()
    for x in dados.get("lista", []):
        try:
            b = str(x.get("box","")).strip()
            ocupados.add(b); ocupados.add(b.lstrip("0")); ocupados.add(b.zfill(2))
        except: pass
    total = int(dados.get("total_boxes",16))
    for i in range(1, total+1):
        if str(i) not in ocupados and f"{i:02d}" not in ocupados:
            return f"{i:02d}"
    return f"{total:02d}"

# ========= CONDOMINIOS - ETAPA 2: PROTEGIDO =========
@app.get("/api/condominios")
def listar_conds(token: str = Depends(requer_auth)):
    return load_json(ARQ_CONDS, [])

@app.get("/api/condominios/public")
def conds_public():
    # ROTA PUBLICA MINIMA - ETAPA 2
    conds = load_json(ARQ_CONDS, [])
    return [{"id": c["id"], "nome": c["nome"]} for c in conds if str(c["id"])!="1"]

@app.get("/api/condominios/{cond_id}")
def get_cond(cond_id: str, token: str = Depends(requer_auth)):
    conds = load_json(ARQ_CONDS, []); mors = load_json(ARQ_MORS, [])
    if str(cond_id) == "1":
        total_boxes = 16
        try:
            soma = sum(int(c.get("total_boxes",0)) for c in conds if str(c.get("id"))!="1")
            if soma>0: total_boxes=soma
        except: pass
        return {"id":"1","nome":"Todos condomínios","total_boxes":total_boxes,"qtd_moradores":len(mors),"status":"ativo"}
    for c in conds:
        if str(c["id"])==str(cond_id):
            c["qtd_moradores"] = len([m for m in mors if str(m.get("condominio"))==str(cond_id)])
            return c
    raise HTTPException(404, "Condomínio não encontrado")

# ========= TABLET - SEM AUTH MAS COM RATE LIMIT =========
@app.post("/api/tablet/entrega")
async def tablet_entrega(payload: dict, request: Request = None):
    dados = load_json(ARQ_DADOS, {"total_boxes":16,"lista":[],"historico":[]})
    box_escolhido = payload.get("box") or get_box_livre(dados)
    nova = {
        "box": str(box_escolhido).zfill(2),
        "bloco": payload.get("bloco",""),
        "apartamento": payload.get("apartamento") or payload.get("apto",""),
        "codigo": payload.get("codigo",""),
        "codigo_retirada": payload.get("codigo_retirada") or payload.get("codigo",""),
        "protocolo": payload.get("protocolo") or f"SC-{secrets.randbelow(90000)+10000}",
        "data": datetime.now().strftime("%d/%m/%Y"),
        "hora": datetime.now().strftime("%H:%M"),
        "nome": payload.get("nome",""),
        "created_at": datetime.now().isoformat(),
        "condominio_id": str(payload.get("condominio_id","1"))
    }
    dados["lista"].append(nova)
    save_json(ARQ_DADOS, dados)
    registrar_auditoria("ENTREGA_TABLET", detalhes=f"Box {nova['box']}", request=request)
    return {"ok": True, "protocolo": nova["protocolo"], "box": nova["box"]}

@app.post("/api/tablet/retirada")
async def tablet_retirada(payload: dict, request: Request = None):
    dados = load_json(ARQ_DADOS, {"total_boxes":16,"lista":[],"historico":[]})
    codigo = payload.get("codigo","")
    achado = None; nova_lista = []
    for item in dados.get("lista",[]):
        if str(item.get("codigo"))==str(codigo) or str(item.get("codigo_retirada"))==str(codigo) or str(item.get("protocolo"))==str(codigo):
            achado=item
        else:
            nova_lista.append(item)
    if not achado: raise HTTPException(404, "Código não encontrado")
    achado["data_retirada"] = datetime.now().strftime("%d/%m/%Y")
    dados["lista"]=nova_lista; dados["historico"].append(achado)
    save_json(ARQ_DADOS, dados)
    registrar_auditoria("RETIRADA_TABLET", detalhes=f"Box {achado['box']}", request=request)
    return {"ok": True, "box": achado["box"]}

@app.post("/api/condominios")
def criar_cond(payload: dict, request: Request, token: str = Depends(requer_auth)):
    conds = load_json(ARQ_CONDS, [])
    novo = {"id": str(uuid.uuid4())[:8],"nome": payload.get("nome"),"total_boxes": payload.get("total_boxes",16),"status":"ativo","criado_em": datetime.now().isoformat()}
    conds.append(novo); save_json(ARQ_CONDS, conds)
    registrar_auditoria("CRIOU_CONDOMINIO", detalhes=novo["nome"], condominio_id=novo["id"], request=request)
    return novo

@app.put("/api/condominios/{cond_id}")
def atualizar_cond(cond_id: str, payload: dict, request: Request = None, token: str = Depends(requer_auth)):
    conds = load_json(ARQ_CONDS, [])
    for c in conds:
        if str(c["id"])==str(cond_id):
            for k in payload: c[k]=payload[k]
            c["atualizado_em"]=datetime.now().isoformat()
            save_json(ARQ_CONDS, conds)
            return c
    raise HTTPException(404)

@app.delete("/api/condominios")
def deletar_cond(id: str = Query(...), request: Request = None, token: str = Depends(requer_auth)):
    conds = load_json(ARQ_CONDS, []); conds=[c for c in conds if str(c["id"])!=str(id)]
    save_json(ARQ_CONDS, conds); return {"ok":True}

@app.get("/api/moradores")
def listar_mors(condominio: str = Query("1"), token: str = Depends(requer_auth)):
    mors = load_json(ARQ_MORS, [])
    if condominio!="1": return [m for m in mors if str(m.get("condominio"))==str(condominio)]
    return mors

@app.post("/api/moradores")
def criar_mor(payload: dict, request: Request = None, token: str = Depends(requer_auth)):
    mors = load_json(ARQ_MORS, [])
    novo = {"id": str(uuid.uuid4())[:8],"nome": payload.get("nome"),"bloco": payload.get("bloco",""),"apto": payload.get("apto",""),"condominio": payload.get("condominio","1")}
    mors.append(novo); save_json(ARQ_MORS, mors)
    return novo

@app.delete("/api/moradores")
def deletar_mor(id: str = Query(...), request: Request = None, token: str = Depends(requer_auth)):
    mors = load_json(ARQ_MORS, []); mors=[m for m in mors if str(m["id"])!=str(id)]
    save_json(ARQ_MORS, mors); return {"ok":True}

# ETAPA 2: CSV DELIMITER CORRIGIDO
@app.post("/api/moradores/import")
async def import_csv(file: UploadFile = File(...), condominio: str = Form(...), request: Request = None, token: str = Depends(requer_auth)):
    content = (await file.read()).decode('utf-8', errors='ignore')
    # detecta ; ou ,
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
    lista_all = raw.get("lista", []); hist_all = raw.get("historico", [])
    if str(condominio) == "1": lista=lista_all; historico=hist_all
    else: lista=[x for x in lista_all if str(x.get("condominio_id"))==str(condominio)]; historico=[x for x in hist_all if str(x.get("condominio_id"))==str(condominio)]
    total_boxes = raw.get("total_boxes",16)
    ocupados=len(lista); livres=max(0,int(total_boxes)-ocupados)
    return {"total_boxes":int(total_boxes),"livres":livres,"ocupados":ocupados,"lista":lista,"historico":historico,"timestamp":datetime.now().isoformat()}

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
        return {"ok": True, "token": token, "expires_in": 28800}
    LOGIN_TENTATIVAS[ip].append(time.time())
    raise HTTPException(401, "Usuário ou senha inválido")

@app.post("/api/entregas")
async def api_entregas_compat(payload: dict, request: Request = None, token: str = Depends(requer_auth)):
    # ETAPA 2: AGORA EXIGE AUTH
    dados = load_json(ARQ_DADOS, {"total_boxes":16,"lista":[],"historico":[]})
    box_req = payload.get("box","")
    if not box_req or box_req=="07" or box_req=="7": box_req=get_box_livre(dados)
    nova = {"box": str(box_req).zfill(2),"bloco": payload.get("bloco",""),"apartamento": payload.get("apartamento") or payload.get("apto",""),"protocolo": payload.get("protocolo") or f"SC-{secrets.randbelow(90000)+10000}","data": payload.get("data") or datetime.now().strftime("%d/%m/%Y"),"hora": payload.get("hora") or datetime.now().strftime("%H:%M"),"created_at": payload.get("data_hora") or datetime.now().isoformat(),"condominio_id": str(payload.get("condominio_id","1"))}
    dados["lista"].append(nova); save_json(ARQ_DADOS, dados)
    registrar_auditoria("ENTREGA_API", detalhes=nova["protocolo"], request=request)
    return {"ok": True, "protocolo": nova["protocolo"], "box": nova["box"]}

@app.post("/api/retiradas")
async def api_retiradas_compat(payload: dict, request: Request = None, token: str = Depends(requer_auth)):
    # ETAPA 2: AGORA EXIGE AUTH + 404 REAL
    dados = load_json(ARQ_DADOS, {"total_boxes":16,"lista":[],"historico":[]})
    codigo = payload.get("protocolo") or payload.get("codigo") or ""
    achado=None; nova_lista=[]
    for item in dados.get("lista",[]):
        if str(item.get("protocolo"))==str(codigo) or str(item.get("codigo"))==str(codigo): achado=item
        else: nova_lista.append(item)
    if achado:
        dados["lista"]=nova_lista; dados["historico"].append(achado); save_json(ARQ_DADOS, dados)
        registrar_auditoria("RETIRADA_API", detalhes=codigo, request=request)
        return {"ok": True, "box": achado["box"]}
    raise HTTPException(404, "Código não encontrado")

# ========= APP - ETAPA 2 CORRIGIDO - SEM SENHA MESTRE =========
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

    # ETAPA 2: REMOVE ADMIN_PASS COMO MESTRE
    mors = load_json(ARQ_MORS, [])
    mor = next((m for m in mors if str(m.get("condominio"))==condominio and str(m.get("bloco")).lower()==bloco.lower() and str(m.get("apto") or m.get("apartamento","")).lower()==apto.lower()), None)
    if not mor:
        raise HTTPException(401, "Morador não encontrado")

    users = get_app_users()
    u = next((x for x in users if x.get("condominio")==condominio and x.get("bloco")==bloco and x.get("apto")==apto), None)

    # ETAPA 2: EXIGE CONTA EM app_users.json
    if not u:
        raise HTTPException(401, "Conta de app não cadastrada. Solicite ao síndico")

    # ETAPA 2: VALIDA SENHA COM HASH
    if not u.get("senha_hash") and not u.get("senha"):
        raise HTTPException(401, "Senha não configurada. Solicite reset ao síndico")

    senha_ok = False
    if u.get("senha_hash"):
        senha_ok = verificar_senha(u["senha_hash"], senha)
    elif u.get("senha"):
        senha_ok = u.get("senha") == senha
        # migra para hash
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
    bloco=token_data.get("bloco",""); apto=token_data.get("apto",""); role=token_data.get("role","morador")
    todas = dados.get("lista",[])+dados.get("historico",[])
    if role=="morador":
        filtradas=[x for x in todas if str(x.get("bloco","")).lower()==bloco.lower() and str(x.get("apartamento") or "").lower()==apto.lower()]
    else:
        filtradas=todas
    return filtradas[::-1][:200]

@app.get("/app", response_class=HTMLResponse)
def app_page(): return no_cache_html(get_path("app.html"))

# IA PACK v5.6 - MANTIDO
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
    resultado={"condominio":condominio,"ocupados":len(lista),"previsao_percent":min(100,perc+15),"total_atrasados":0,"alertas_24h":[],"atualizado":datetime.now().isoformat(),"versao":"v5.6-corrigida"}
    _set_cache_ia("lotacao_"+condominio, resultado)
    return resultado

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
