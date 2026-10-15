from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query, Request, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from datetime import datetime, timedelta
import json, os, secrets, uuid, csv, io, time, jwt
from collections import defaultdict
from dotenv import load_dotenv
load_dotenv()
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5000", "http://127.0.0.1:5000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")
SECRET_JWT = os.getenv("SECRET_JWT", "smartcube-secret-2026-fallback")

def gerar_token(usuario: str) -> str:
    from datetime import datetime, timezone, timedelta
    payload = {
        "sub": usuario,
        "exp": datetime.now(timezone.utc) + timedelta(hours=8),
        "iat": datetime.now(timezone.utc)
    }
    return jwt.encode(payload, SECRET_JWT, algorithm="HS256")

def verificar_token(token: str):
    try:
        data = jwt.decode(token, SECRET_JWT, algorithms=["HS256"])
        return data.get("sub")
    except:
        return None

def get_path(nome):
    for base in [TEMPLATES_DIR, STATIC_DIR, BASE_DIR]:
        p = os.path.join(base, nome)
        if os.path.exists(p):
            return p
    return os.path.join(TEMPLATES_DIR, nome)

templates = Jinja2Templates(directory=TEMPLATES_DIR)

if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

def load_json(path, default):
    full = os.path.join(BASE_DIR, path)
    if not os.path.exists(full): return default
    try:
        with open(full,'r',encoding='utf-8') as f: return json.load(f)
    except: return default

def save_json(path, data):
    full = os.path.join(BASE_DIR, path)
    with open(full,'w',encoding='utf-8') as f:
        json.dump(data,f,ensure_ascii=False,indent=2)

# ========= SEGURANÇA V7.0 - BLINDADO REMOTO + TABLET SEPARADO =========
ADMIN_USER = os.getenv("SMARTCUBE_USER", "admin")
ADMIN_PASS = os.getenv("SMARTCUBE_ADMIN_PASS", "SmartCube@2026")

ARQ_TOKENS = "tokens.json"
TOKENS_VALIDOS = {}
LOGIN_TENTATIVAS = defaultdict(list)

def load_tokens():
    global TOKENS_VALIDOS
    dados = load_json(ARQ_TOKENS, {})
    for k, v in dados.items():
        try:
            v["expires"] = datetime.fromisoformat(v["expires"])
            TOKENS_VALIDOS[k] = v
        except:
            pass

def save_tokens():
    to_save = {}
    for k, v in TOKENS_VALIDOS.items():
        to_save[k] = {
            "user": v["user"],
            "expires": v["expires"].isoformat(),
            "ip": v.get("ip","")
        }
    save_json(ARQ_TOKENS, to_save)

load_tokens()

def check_admin_pass(senha: str):
    if senha!= ADMIN_PASS:
        raise HTTPException(403, "Senha inválida")

def is_token_valid(token: str) -> bool:
    if not token: return False
    if token not in TOKENS_VALIDOS:
        load_tokens()
    dados = TOKENS_VALIDOS.get(token)
    if not dados: return False
    if datetime.now() > dados["expires"]:
        TOKENS_VALIDOS.pop(token, None)
        save_tokens()
        return False
    return True

# DEPENDENCY QUE BLINDA TODAS AS APIs SENSÍVEIS
def requer_auth(request: Request, authorization: str = Header(None)):
    token = ""
    if authorization and "Bearer" in authorization:
        token = authorization.replace("Bearer ", "").strip()
    if not token:
        token = request.cookies.get("sc_token") or ""
    if not token:
        token = request.query_params.get("token") or ""
    if not token:
        token = request.headers.get("x-token") or ""
    if not token or not is_token_valid(token):
        raise HTTPException(status_code=401, detail="Não autorizado - Faça login no dashboard")
    return token

def check_rate_limit(request: Request):
    ip = request.client.host if request.client else "127.0.0.1"
    agora = time.time()
    LOGIN_TENTATIVAS[ip] = [t for t in LOGIN_TENTATIVAS[ip] if agora - t < 60]
    if len(LOGIN_TENTATIVAS[ip]) >= 5:
        raise HTTPException(status_code=429, detail="Muitas tentativas. Aguarde 1 minuto")
    return ip

ARQ_CONDS = "condominios.json"
ARQ_MORS = "moradores.json"
ARQ_DADOS = "dashboard_dados.json"
ARQ_KEYS = "api_keys.json"
ARQ_BOXES = "boxes.json"
ARQ_HIST = "historico.json"
ARQ_AUDIT = "auditoria.json"
ARQ_LOGIN = "login_attempts.json"

def registrar_auditoria(acao, usuario="sistema", detalhes="", condominio_id="", request: Request = None):
    logs = load_json(ARQ_AUDIT, [])
    ip = "sistema"
    if request and request.client:
        ip = request.client.host
    logs.append({
        "id": str(uuid.uuid4())[:8],
        "data": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "timestamp": datetime.now().isoformat(),
        "acao": acao,
        "usuario": usuario,
        "detalhes": detalhes,
        "condominio_id": condominio_id,
        "ip": ip
    })
    if len(logs) > 1000: logs = logs[-1000:]
    save_json(ARQ_AUDIT, logs)

def no_cache_html(path):
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        return HTMLResponse(content=content, headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"})
    return HTMLResponse(f"<h1>Arquivo nao encontrado: {path}</h1>", status_code=404)

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
@app.get("/armario_real_laranja.png")
def serve_armario_real_png():
    p = get_path("armario_real_laranja.png")
    if os.path.exists(p): return FileResponse(p)
    return FileResponse(get_path("armario_real_laranja.jpg"))
@app.get("/{arquivo}.jpg")
def serve_any_jpg(arquivo: str):
    path = get_path(f"{arquivo}.jpg")
    if os.path.exists(path): return FileResponse(path)
    raise HTTPException(404)
@app.get("/{arquivo}.png")
def serve_any_png(arquivo: str):
    path = get_path(f"{arquivo}.png")
    if os.path.exists(path): return FileResponse(path)
    raise HTTPException(404)

# ================== ROTAS PÚBLICAS - SITE + TABLET ==================
@app.get("/", response_class=HTMLResponse)
async def inicio_page(request: Request):
    return no_cache_html(get_path("inicio.html"))

@app.get("/tablet", response_class=HTMLResponse)
async def tablet_menu_page(request: Request):
    return no_cache_html(get_path("tablet.html"))

@app.get("/retirada", response_class=HTMLResponse)
async def retirada_page(request: Request):
    return no_cache_html(get_path("retirada.html"))

@app.get("/entrega", response_class=HTMLResponse)
async def entrega_page(request: Request):
    return no_cache_html(get_path("entrega.html"))

@app.get("/site", response_class=HTMLResponse)
def site_page(): return no_cache_html(get_path("site.html"))

@app.get("/site.html", response_class=HTMLResponse)
def site_html(): return no_cache_html(get_path("site.html"))

@app.get("/login", response_class=HTMLResponse)
def login_page(): return no_cache_html(get_path("login.html"))

# ================== ROTA BLINDADA - DASHBOARD ==================
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    auth = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    token = ""
    if auth:
        token = auth.replace("Bearer ", "").strip()
    if not token:
        token = request.cookies.get("sc_token") or ""
    if not token:
        token = request.query_params.get("token") or ""
    if not token:
        token = request.headers.get("x-token") or ""
    if not token or not is_token_valid(token):
        return RedirectResponse(url="/login", status_code=302)
    try:
        return templates.TemplateResponse("dashboard.html", {"request": request})
    except:
        return no_cache_html(get_path("dashboard.html"))

# ================== API PÚBLICA - TABLET ENVIA DADOS ==================
@app.post("/api/tablet/entrega")
async def tablet_entrega(payload: dict, request: Request = None):
    # Tablet só pode ENVIAR, não pode LER condomínios
    dados = load_json(ARQ_DADOS, {"total_boxes":16,"livres":15,"ocupados":1,"ocupacao":6,"vencidas":0,"por_hora":[0]*24,"lista":[],"historico":[],"vencidas_lista":[]})
    nova = {
        "box": str(payload.get("box","1")),
        "bloco": payload.get("bloco",""),
        "apartamento": payload.get("apartamento") or payload.get("apto",""),
        "codigo": payload.get("codigo",""),
        "codigo_retirada": payload.get("codigo_retirada") or payload.get("codigo",""),
        "protocolo": payload.get("protocolo") or f"SC-{secrets.randbelow(90000)+10000}",
        "data": datetime.now().strftime("%d/%m/%Y"),
        "hora": datetime.now().strftime("%H:%M"),
        "nome": payload.get("nome",""),
        "created_at": datetime.now().isoformat()
    }
    dados["lista"].append(nova)
    dados["ocupados"] = len(dados["lista"])
    dados["livres"] = dados.get("total_boxes",16) - dados["ocupados"]
    dados["ocupacao"] = int(dados["ocupados"]/dados.get("total_boxes",16)*100)
    save_json(ARQ_DADOS, dados)
    registrar_auditoria("ENTREGA_TABLET", detalhes=f"Entrega Box {nova['box']} Bl {nova['bloco']} Ap {nova['apartamento']}", request=request)
    return {"ok": True, "protocolo": nova["protocolo"]}

@app.post("/api/tablet/retirada")
async def tablet_retirada(payload: dict, request: Request = None):
    dados = load_json(ARQ_DADOS, {"total_boxes":16,"livres":15,"ocupados":1,"ocupacao":6,"vencidas":0,"por_hora":[0]*24,"lista":[],"historico":[],"vencidas_lista":[]})
    codigo = payload.get("codigo","")
    # Remove da lista de ocupados e joga pro histórico
    achado = None
    nova_lista = []
    for item in dados.get("lista",[]):
        if str(item.get("codigo"))==str(codigo) or str(item.get("codigo_retirada"))==str(codigo) or str(item.get("protocolo"))==str(codigo):
            achado = item
        else:
            nova_lista.append(item)
    if not achado:
        raise HTTPException(404, "Código não encontrado")
    achado["data_retirada"] = datetime.now().strftime("%d/%m/%Y")
    achado["hora_retirada"] = datetime.now().strftime("%H:%M")
    achado["tempo"] = "Retirado"
    dados["lista"] = nova_lista
    dados["historico"].append(achado)
    dados["ocupados"] = len(nova_lista)
    dados["livres"] = dados.get("total_boxes",16) - dados["ocupados"]
    dados["ocupacao"] = int(dados["ocupados"]/dados.get("total_boxes",16)*100)
    save_json(ARQ_DADOS, dados)
    registrar_auditoria("RETIRADA_TABLET", detalhes=f"Retirada Box {achado['box']} Código {codigo}", request=request)
    return {"ok": True, "box": achado["box"]}

# ================== APIs BLINDADAS - SÓ COM TOKEN ==================
@app.get("/api/condominios")
def listar_conds(token: str = Depends(requer_auth)):
    return load_json(ARQ_CONDS, [{"id":"1","nome":"Todos condomínios"}])

@app.get("/api/condominios/{cond_id}")
def get_cond(cond_id: str, token: str = Depends(requer_auth)):
    conds = load_json(ARQ_CONDS, []); mors = load_json(ARQ_MORS, [])
    for c in conds:
        if str(c["id"])==str(cond_id):
            c["qtd_moradores"] = len([m for m in mors if str(m.get("condominio"))==str(cond_id)])
            registrar_auditoria("VISUALIZOU_CONDOMINIO", detalhes=f"Visualizou {c['nome']}", condominio_id=cond_id)
            return c
    raise HTTPException(404, "Condomínio não encontrado")

@app.post("/api/condominios")
def criar_cond(payload: dict, request: Request, token: str = Depends(requer_auth)):
    conds = load_json(ARQ_CONDS, [])
    novo = {"id": str(uuid.uuid4())[:8],"nome": payload.get("nome","Novo Condomínio"),"cnpj": payload.get("cnpj",""),"endereco": payload.get("endereco",""),"armario_num": payload.get("armario_num", f"ARM-{secrets.randbelow(90000)+10000}"),"total_boxes": payload.get("total_boxes", 16),"data_inicio": payload.get("data_inicio",""),"periodo": payload.get("periodo","12 meses"),"valor_mensal": payload.get("valor_mensal",""),"valor_instalacao": payload.get("valor_instalacao",""),"status": payload.get("status","ativo"),"vencimento": payload.get("vencimento",""),"qtd_moradores":0,"criado_em": datetime.now().isoformat()}
    conds.append(novo); save_json(ARQ_CONDS, conds); registrar_auditoria("CRIOU_CONDOMINIO", detalhes=f"Criou {novo['nome']} {novo['armario_num']}", condominio_id=novo["id"], request=request); return novo

@app.put("/api/condominios/{cond_id}")
def atualizar_cond(cond_id: str, payload: dict, request: Request = None, token: str = Depends(requer_auth)):
    conds = load_json(ARQ_CONDS, [])
    for c in conds:
        if str(c["id"])==str(cond_id):
            for k in ["nome","cnpj","endereco","armario_num","total_boxes","data_inicio","periodo","valor_mensal","valor_instalacao","status","vencimento","operador"]:
                if k in payload: c[k]=payload[k]
            c["atualizado_em"] = datetime.now().isoformat(); save_json(ARQ_CONDS, conds); registrar_auditoria("ATUALIZOU_CONTRATO", detalhes=f"Atualizou contrato {c['nome']}", condominio_id=cond_id, request=request); return c
    raise HTTPException(404)

@app.delete("/api/condominios")
def deletar_cond(id: str = Query(...), request: Request = None, token: str = Depends(requer_auth)):
    conds = load_json(ARQ_CONDS, []); conds = [c for c in conds if str(c["id"])!=str(id)]; save_json(ARQ_CONDS, conds); registrar_auditoria("EXCLUIU_CONDOMINIO", detalhes=f"Excluiu condominio {id}", condominio_id=id, request=request); return {"ok":True}

@app.get("/api/moradores")
def listar_mors(condominio: str = Query("1"), token: str = Depends(requer_auth)):
    mors = load_json(ARQ_MORS, [])
    if condominio!="1": return [m for m in mors if str(m.get("condominio"))==str(condominio)]
    return mors

@app.post("/api/moradores")
def criar_mor(payload: dict, request: Request = None, token: str = Depends(requer_auth)):
    mors = load_json(ARQ_MORS, []); novo = {"id": str(uuid.uuid4())[:8],"nome": payload.get("nome"),"bloco": payload.get("bloco",""),"apto": payload.get("apto","") or payload.get("apartamento",""),"condominio": payload.get("condominio","1"),"consentimento_lgpd": True,"data_consentimento": datetime.now().isoformat(),"origem_cadastro": "painel_admin"}; mors.append(novo); save_json(ARQ_MORS, mors); registrar_auditoria("CRIOU_MORADOR", detalhes=f"Criou morador Bl {novo['bloco']} Ap {novo['apto']}", condominio_id=novo["condominio"], request=request); return novo

@app.delete("/api/moradores")
def deletar_mor(id: str = Query(...), request: Request = None, token: str = Depends(requer_auth)):
    mors = load_json(ARQ_MORS, []); mor = next((m for m in mors if str(m["id"])==str(id)), None); mors = [m for m in mors if str(m["id"])!=str(id)]; save_json(ARQ_MORS, mors)
    if mor: registrar_auditoria("EXCLUIU_MORADOR", detalhes=f"Excluiu morador {id}", condominio_id=mor.get("condominio",""), request=request); return {"ok":True}

@app.delete("/api/moradores/lgpd/{mor_id}")
def anonimizar_mor(mor_id: str, request: Request = None, token: str = Depends(requer_auth)):
    mors = load_json(ARQ_MORS, [])
    for m in mors:
        if str(m["id"])==str(mor_id): m["nome"] = "ANONIMIZADO - LGPD"; m["bloco"] = "***"; m["apto"] = "***"; m["anonimizado_em"] = datetime.now().isoformat(); m["consentimento_lgpd"] = False; save_json(ARQ_MORS, mors); registrar_auditoria("LGPD_ANONIMIZACAO", detalhes=f"Anonimizou morador {mor_id} - LGPD", condominio_id=m.get("condominio",""), request=request); return {"ok": True, "msg": "Dados anonimizados conforme LGPD"}
    raise HTTPException(404)

@app.post("/api/moradores/import")
async def import_csv(file: UploadFile = File(...), condominio: str = Form(...), request: Request = None, token: str = Depends(requer_auth)):
    content = (await file.read()).decode('utf-8', errors='ignore'); reader = csv.DictReader(io.StringIO(content)); mors = load_json(ARQ_MORS, []); count=0
    for row in reader:
        nome = row.get("nome") or row.get("Nome") or row.get("NOME") or list(row.values())[0]
        if not nome or str(nome).strip()=="": continue
        mors.append({"id": str(uuid.uuid4())[:8],"nome": str(nome).strip(),"bloco": str(row.get("bloco","") or row.get("Bloco","")).strip(),"apto": str(row.get("apto","") or row.get("apartamento","") or row.get("Apto","")).strip(),"condominio": condominio,"consentimento_lgpd": True,"data_consentimento": datetime.now().isoformat(),"origem_cadastro": "importacao_csv"}); count+=1
    save_json(ARQ_MORS, mors); registrar_auditoria("IMPORTACAO_CSV", detalhes=f"Importou {count} moradores", condominio_id=condominio, request=request); return {"importados": count}

@app.get("/api/dashboard/dados")
def dashboard_dados(condominio: str = "1", token: str = Depends(requer_auth)):
    dados = load_json(ARQ_DADOS, {"total_boxes":16,"livres":15,"ocupados":1,"ocupacao":6,"vencidas":0,"por_hora":[0]*24,"lista":[],"historico":[],"vencidas_lista":[]})
    if "ocupacao" not in dados: dados["ocupacao"] = int(dados.get("ocupados",0)/16*100)
    return dados

@app.post("/api/integracao/gerar")
def gerar_api_key(payload: dict = {}, request: Request = None, token: str = Depends(requer_auth)):
    keys = load_json(ARQ_KEYS, {}); nova = "sc_live_" + secrets.token_urlsafe(32); keys[nova] = {"id": str(uuid.uuid4())[:8],"nome": payload.get("nome", "Parceiro"),"criada_em": datetime.now().isoformat(),"uso": 0,"condominios_permitidos": payload.get("condominios_permitidos", []),"ativa": True}; save_json(ARQ_KEYS, keys); registrar_auditoria("GEROU_API_KEY", detalhes=f"Gerou key para {payload.get('nome','')}", request=request); return {"api_key": nova}

@app.get("/api/auditoria")
def listar_auditoria(request: Request = None, token: str = Depends(requer_auth)):
    return load_json(ARQ_AUDIT, [])[::-1][:200]

@app.post("/api/auth/login")
def auth_login(payload: dict, request: Request):
    ip = check_rate_limit(request)
    usuario = payload.get("usuario","").strip()
    senha = payload.get("senha","")
    if usuario == ADMIN_USER and senha == ADMIN_PASS:
        LOGIN_TENTATIVAS[ip].clear()
        token = "sc_" + secrets.token_urlsafe(32)
        TOKENS_VALIDOS[token] = {
            "user": usuario,
            "expires": datetime.now() + timedelta(hours=8),
            "ip": ip
        }
        save_tokens()
        registrar_auditoria("LOGIN_SUCESSO", usuario=usuario, detalhes=f"Login no dashboard IP {ip}", request=request)
        return {"ok": True, "token": token, "expires_in": 28800}
    LOGIN_TENTATIVAS[ip].append(time.time())
    registrar_auditoria("LOGIN_FALHA", usuario=usuario, detalhes=f"Tentativa falha IP {ip}", request=request)
    raise HTTPException(status_code=401, detail="Usuário ou senha inválido")

@app.get("/api/auth/verificar")
def verificar_token_api(request: Request, authorization: str = Header(None), token: str = Query(None)):
    t = ""
    if authorization and "Bearer" in authorization:
        t = authorization.replace("Bearer ","").strip()
    if not t:
        t = token or ""
    if not t:
        t = request.cookies.get("sc_token") or request.query_params.get("token") or ""
    if not t:
        raise HTTPException(401, "Sem token")
    if is_token_valid(t):
        return {"ok": True, "user": TOKENS_VALIDOS[t]["user"]}
    raise HTTPException(401, "Token inválido ou expirado")

@app.post("/api/auth/logout")
def logout_token(authorization: str = Header(None), request: Request = None):
    token = ""
    if authorization and "Bearer" in authorization:
        token = authorization.replace("Bearer ","").strip()
    if not token and request:
        token = request.cookies.get("sc_token") or request.query_params.get("token") or ""
    if token:
        TOKENS_VALIDOS.pop(token, None)
        save_tokens()
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)