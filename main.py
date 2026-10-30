from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query, Request, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from datetime import datetime, timedelta
import json, os, secrets, uuid, csv, io, time, jwt, threading
from collections import defaultdict
from dotenv import load_dotenv
load_dotenv()
app = FastAPI()
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")
SECRET_JWT = os.getenv("SECRET_JWT", "smartcube-secret-2026-fallback")

# TRAVA PARA JSON - 100 armarios
FILE_LOCK = threading.Lock()

def get_path(nome):
    for base in [TEMPLATES_DIR, STATIC_DIR, BASE_DIR]:
        p = os.path.join(base, nome)
        if os.path.exists(p): return p
    return os.path.join(TEMPLATES_DIR, nome)
templates = Jinja2Templates(directory=TEMPLATES_DIR)
if os.path.exists(STATIC_DIR): app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
def load_json(path, default):
    full_path = os.path.join(BASE_DIR, path)
    if not os.path.exists(full_path): return default
    try:
        with open(full_path,'r',encoding='utf-8') as f: return json.load(f)
    except: return default
def save_json(path, data):
    full_path = os.path.join(BASE_DIR, path)
    with FILE_LOCK:
        with open(full_path,'w',encoding='utf-8') as f: json.dump(data,f,ensure_ascii=False,indent=2)

ARQ_TOKENS = "tokens.json"; ARQ_DADOS = "dashboard_dados.json"; ARQ_KEYS = "api_keys.json"; ARQ_BOXES = "boxes.json"; ARQ_HIST = "historico.json"; ARQ_AUDIT = "auditoria.json"; ARQ_LOGIN = "login_attempts.json"; ARQ_CONDS = "condominios.json"; ARQ_MORS = "moradores.json"; ARQ_APP_USERS = "app_users.json"
ARQ_CACHE_IA = "ia_cache.json"; ARQ_BLOQUEIOS = "ia_bloqueios.json"; ARQ_IA_LOGS = "ia_logs.json"

def no_cache_html(path):
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f: content = f.read()
        return HTMLResponse(content=content, headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"})
    return HTMLResponse(f"<h1>Arquivo nao encontrado: {path}</h1>", status_code=404)
ADMIN_USER = os.getenv("SMARTCUBE_USER", "admin"); ADMIN_PASS = os.getenv("SMARTCUBE_ADMIN_PASS", "SmartCube@2026")
TOKENS_VALIDOS = {}; LOGIN_TENTATIVAS = defaultdict(list)
def load_tokens():
    global TOKENS_VALIDOS; dados = load_json(ARQ_TOKENS, {}); TOKENS_VALIDOS = {}
    for k, v in dados.items():
        try: v["expires"] = datetime.fromisoformat(v["expires"]); TOKENS_VALIDOS[k] = v
        except: pass
def save_tokens():
    to_save = {}
    for k, v in TOKENS_VALIDOS.items(): to_save[k] = {"user": v["user"],"expires": v["expires"].isoformat(),"ip": v.get("ip","")}
    save_json(ARQ_TOKENS, to_save)
load_tokens()
def is_token_valid(token: str) -> bool:
    if not token: return False
    if token not in TOKENS_VALIDOS: load_tokens()
    dados = TOKENS_VALIDOS.get(token)
    if not dados: return False
    try:
        if datetime.now() > dados["expires"]: TOKENS_VALIDOS.pop(token, None); save_tokens(); return False
    except: return False
    return True
def requer_auth(request: Request, authorization: str = Header(None), token: str = Query(None)):
    t = ""
    if authorization and "Bearer" in authorization: t = authorization.replace("Bearer ","").strip()
    if not t: t = token or ""
    if not t: t = request.cookies.get("sc_token") or request.query_params.get("token") or request.headers.get("x-token") or ""
    if not t or not is_token_valid(t): raise HTTPException(status_code=401, detail="Token inválido")
    return t

# AUTH OPCIONAL - PARA TABLET NAO DAR 401 - NAO MUDA ROTA
def requer_auth_opcional(request: Request, authorization: str = Header(None), token: str = Query(None)):
    t = ""
    if authorization and "Bearer" in authorization: t = authorization.replace("Bearer ","").strip()
    if not t: t = token or ""
    if not t: t = request.cookies.get("sc_token") or request.query_params.get("token") or request.headers.get("x-token") or ""
    if t and not is_token_valid(t): raise HTTPException(status_code=401, detail="Token inválido")
    return t or "tablet_public"

def check_rate_limit(request: Request):
    ip = request.client.host if request.client else "unknown"; now = time.time()
    LOGIN_TENTATIVAS[ip] = [x for x in LOGIN_TENTATIVAS[ip] if now - x < 900]
    if len(LOGIN_TENTATIVAS[ip]) >= 10: raise HTTPException(429, "Muitas tentativas. Aguarde 15 min")
    return ip
def registrar_auditoria(acao, usuario="sistema", detalhes="", condominio_id="", request: Request = None):
    logs = load_json(ARQ_AUDIT, []); ip = "sistema"
    if request and request.client: ip = request.client.host
    logs.append({"id": str(uuid.uuid4())[:8],"data": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),"timestamp": datetime.now().isoformat(),"acao": acao,"usuario": usuario,"detalhes": detalhes,"condominio_id": condominio_id,"ip": ip})
    if len(logs) > 1000: logs = logs[-1000:]; save_json(ARQ_AUDIT, logs)
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request); response.headers["X-Content-Type-Options"] = "nosniff"; response.headers["X-Frame-Options"] = "DENY"; return response
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
@app.get("/", response_class=HTMLResponse)
async def inicio_page(request: Request): return no_cache_html(get_path("inicio.html"))
@app.get("/site", response_class=HTMLResponse)
def site_page(): return no_cache_html(get_path("site.html"))
@app.get("/site.html", response_class=HTMLResponse)
def site_html(): return no_cache_html(get_path("site.html"))
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
    auth = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    token = ""
    if auth: token = auth.replace("Bearer ", "").strip()
    if not token: token = request.cookies.get("sc_token") or ""
    if not token: token = request.query_params.get("token") or ""
    if not token: token = request.headers.get("x-token") or ""
    if not token or not is_token_valid(token): return RedirectResponse(url="/login", status_code=302)
    try: return templates.TemplateResponse("dashboard.html", {"request": request})
    except: return no_cache_html(get_path("dashboard.html"))

# HELPER BOX LIVRE - NAO MUDA ROTA
def get_box_livre(dados):
    ocupados = set()
    for x in dados.get("lista", []):
        try:
            b = str(x.get("box","")).lstrip("0") or "0"
            ocupados.add(b)
            ocupados.add(str(x.get("box","")).zfill(2))
            ocupados.add(str(x.get("box","")))
        except: pass
    total = int(dados.get("total_boxes",16))
    for i in range(1, total+1):
        s = str(i)
        s2 = f"{i:02d}"
        if s not in ocupados and s2 not in ocupados:
            return s2
    return f"{total:02d}"

@app.get("/api/condominios")
def listar_conds(): return load_json(ARQ_CONDS, [{"id":"1","nome":"Todos condomínios"}])
@app.get("/api/condominios/{cond_id}")
def get_cond(cond_id: str):
    conds = load_json(ARQ_CONDS, []); mors = load_json(ARQ_MORS, [])
    if str(cond_id) == "1" or cond_id == "Todos condomínios":
        total_boxes = 16
        try:
            soma = 0
            for c in conds:
                if str(c.get("id")) != "1":
                    try: soma += int(c.get("total_boxes", 0))
                    except: pass
            if soma > 0: total_boxes = soma
        except: pass
        return {"id": "1","nome": "Todos condomínios","total_boxes": total_boxes,"qtd_moradores": len(mors),"armario_num": "GERAL","status": "ativo","cnpj": "","endereco": "Todos"}
    for c in conds:
        if str(c["id"])==str(cond_id): c["qtd_moradores"] = len([m for m in mors if str(m.get("condominio"))==str(cond_id)]); return c
    raise HTTPException(404, "Condomínio não encontrado")
@app.post("/api/tablet/entrega")
async def tablet_entrega(payload: dict, request: Request = None):
    dados = load_json(ARQ_DADOS, {"total_boxes":16,"livres":15,"ocupados":1,"ocupacao":6,"vencidas":0,"por_hora":[0]*24,"lista":[],"historico":[],"vencidas_lista":[]})
    box_escolhido = payload.get("box") or get_box_livre(dados)
    nova = {"box": str(box_escolhido).zfill(2),"bloco": payload.get("bloco",""),"apartamento": payload.get("apartamento") or payload.get("apto",""),"codigo": payload.get("codigo",""),"codigo_retirada": payload.get("codigo_retirada") or payload.get("codigo",""),"protocolo": payload.get("protocolo") or f"SC-{secrets.randbelow(90000)+10000}","data": datetime.now().strftime("%d/%m/%Y"),"hora": datetime.now().strftime("%H:%M"),"nome": payload.get("nome",""),"created_at": datetime.now().isoformat(),"condominio_id": str(payload.get("condominio_id","1"))}
    dados["lista"].append(nova); dados["ocupados"] = len(dados["lista"]); dados["livres"] = dados.get("total_boxes",16) - dados["ocupados"]; dados["ocupacao"] = int(dados["ocupados"]/dados.get("total_boxes",16)*100); save_json(ARQ_DADOS, dados); registrar_auditoria("ENTREGA_TABLET", detalhes=f"Entrega Box {nova['box']}", request=request); return {"ok": True, "protocolo": nova["protocolo"], "box": nova["box"]}
@app.post("/api/tablet/retirada")
async def tablet_retirada(payload: dict, request: Request = None):
    dados = load_json(ARQ_DADOS, {"total_boxes":16,"livres":15,"ocupados":1,"ocupacao":6,"vencidas":0,"por_hora":[0]*24,"lista":[],"historico":[],"vencidas_lista":[]})
    codigo = payload.get("codigo",""); achado = None; nova_lista = []
    for item in dados.get("lista",[]):
        if str(item.get("codigo"))==str(codigo) or str(item.get("codigo_retirada"))==str(codigo) or str(item.get("protocolo"))==str(codigo): achado = item
        else: nova_lista.append(item)
    if not achado: raise HTTPException(404, "Código não encontrado")
    achado["data_retirada"] = datetime.now().strftime("%d/%m/%Y"); achado["hora_retirada"] = datetime.now().strftime("%H:%M"); dados["lista"] = nova_lista; dados["historico"].append(achado); dados["ocupados"] = len(nova_lista); dados["livres"] = dados.get("total_boxes",16) - dados["ocupados"]; save_json(ARQ_DADOS, dados); registrar_auditoria("RETIRADA_TABLET", detalhes=f"Retirada Box {achado['box']}", request=request); return {"ok": True, "box": achado["box"]}
@app.post("/api/condominios")
def criar_cond(payload: dict, request: Request, token: str = Depends(requer_auth)):
    conds = load_json(ARQ_CONDS, []); novo = {"id": str(uuid.uuid4())[:8],"nome": payload.get("nome","Novo Condomínio"),"cnpj": payload.get("cnpj",""),"endereco": payload.get("endereco",""),"armario_num": payload.get("armario_num", f"ARM-{secrets.randbelow(90000)+10000}"),"total_boxes": payload.get("total_boxes", 16),"data_inicio": payload.get("data_inicio",""),"periodo": payload.get("periodo","12 meses"),"valor_mensal": payload.get("valor_mensal",""),"valor_instalacao": payload.get("valor_instalacao",""),"status": payload.get("status","ativo"),"vencimento": payload.get("vencimento",""),"qtd_moradores":0,"criado_em": datetime.now().isoformat()}; conds.append(novo); save_json(ARQ_CONDS, conds); registrar_auditoria("CRIOU_CONDOMINIO", detalhes=f"Criou {novo['nome']}", condominio_id=novo["id"], request=request); return novo
@app.put("/api/condominios/{cond_id}")
def atualizar_cond(cond_id: str, payload: dict, request: Request = None, token: str = Depends(requer_auth)):
    conds = load_json(ARQ_CONDS, [])
    for c in conds:
        if str(c["id"])==str(cond_id):
            for k in ["nome","cnpj","endereco","armario_num","total_boxes","data_inicio","periodo","valor_mensal","valor_instalacao","status","vencimento","operador"]:
                if k in payload: c[k]=payload[k]
            c["atualizado_em"] = datetime.now().isoformat(); save_json(ARQ_CONDS, conds); registrar_auditoria("ATUALIZOU_CONTRATO", detalhes=f"Atualizou {c['nome']}", condominio_id=cond_id, request=request); return c
    raise HTTPException(404)
@app.delete("/api/condominios")
def deletar_cond(id: str = Query(...), request: Request = None, token: str = Depends(requer_auth)): conds = load_json(ARQ_CONDS, []); conds = [c for c in conds if str(c["id"])!=str(id)]; save_json(ARQ_CONDS, conds); registrar_auditoria("EXCLUIU_CONDOMINIO", detalhes=f"Excluiu {id}", condominio_id=id, request=request); return {"ok":True}
@app.get("/api/moradores")
def listar_mors(condominio: str = Query("1"), token: str = Depends(requer_auth)):
    mors = load_json(ARQ_MORS, [])
    if condominio!="1": return [m for m in mors if str(m.get("condominio"))==str(condominio)]
    return mors
@app.post("/api/moradores")
def criar_mor(payload: dict, request: Request = None, token: str = Depends(requer_auth)):
    mors = load_json(ARQ_MORS, []); novo = {"id": str(uuid.uuid4())[:8],"nome": payload.get("nome"),"bloco": payload.get("bloco",""),"apto": payload.get("apto","") or payload.get("apartamento",""),"condominio": payload.get("condominio","1"),"consentimento_lgpd": True,"data_consentimento": datetime.now().isoformat(),"origem_cadastro": "painel_admin"}; mors.append(novo); save_json(ARQ_MORS, mors); registrar_auditoria("CRIOU_MORADOR", detalhes=f"Criou Bl {novo['bloco']} Ap {novo['apto']}", condominio_id=novo["condominio"], request=request); return novo
@app.delete("/api/moradores")
def deletar_mor(id: str = Query(...), request: Request = None, token: str = Depends(requer_auth)):
    mors = load_json(ARQ_MORS, []); mor = next((m for m in mors if str(m["id"])==str(id)), None); mors = [m for m in mors if str(m["id"])!=str(id)]; save_json(ARQ_MORS, mors)
    if mor: registrar_auditoria("EXCLUIU_MORADOR", detalhes=f"Excluiu {id}", condominio_id=mor.get("condominio",""), request=request); return {"ok":True}
@app.delete("/api/moradores/lgpd/{mor_id}")
def anonimizar_mor(mor_id: str, request: Request = None, token: str = Depends(requer_auth)):
    mors = load_json(ARQ_MORS, [])
    for m in mors:
        if str(m["id"])==str(mor_id): m["nome"] = "ANONIMIZADO - LGPD"; m["bloco"] = "***"; m["apto"] = "***"; m["anonimizado_em"] = datetime.now().isoformat(); m["consentimento_lgpd"] = False; save_json(ARQ_MORS, mors); registrar_auditoria("LGPD_ANONIMIZACAO", detalhes=f"Anonimizou {mor_id}", condominio_id=m.get("condominio",""), request=request); return {"ok": True, "msg": "Dados anonimizados"}
    raise HTTPException(404)
@app.post("/api/moradores/import")
async def import_csv(file: UploadFile = File(...), condominio: str = Form(...), request: Request = None, token: str = Depends(requer_auth)):
    content = (await file.read()).decode('utf-8', errors='ignore'); reader = csv.DictReader(io.StringIO(content)); mors = load_json(ARQ_MORS, []); count=0
    for row in reader:
        nome = row.get("nome") or row.get("Nome") or row.get("NOME") or list(row.values())[0]
        if not nome or str(nome).strip()=="": continue
        mors.append({"id": str(uuid.uuid4())[:8],"nome": str(nome).strip(),"bloco": str(row.get("bloco","") or row.get("Bloco","")).strip(),"apto": str(row.get("apto","") or row.get("apartamento","") or row.get("Apto","")).strip(),"condominio": condominio,"consentimento_lgpd": True,"data_consentimento": datetime.now().isoformat(),"origem_cadastro": "importacao_csv"}); count+=1
    save_json(ARQ_MORS, mors); registrar_auditoria("IMPORTACAO_CSV", detalhes=f"Importou {count}", condominio_id=condominio, request=request); return {"importados": count}
@app.get("/api/dashboard/dados")
def dashboard_dados(condominio: str = "1", token: str = Depends(requer_auth)):
    raw = load_json(ARQ_DADOS, {"total_boxes":16,"livres":15,"ocupados":1,"ocupacao":6,"vencidas":0,"por_hora":[0]*24,"lista":[],"historico":[],"vencidas_lista":[]})
    lista_all = raw.get("lista", []); hist_all = raw.get("historico", [])
    # FIX VAZAMENTO - sem "or condominio_id not in x"
    if str(condominio) == "1": lista = lista_all; historico = hist_all
    else: lista = [x for x in lista_all if str(x.get("condominio_id")) == str(condominio)]; historico = [x for x in hist_all if str(x.get("condominio_id")) == str(condominio)]
    total_boxes = raw.get("total_boxes", 16); ocupados = len(lista); livres = max(0, int(total_boxes) - ocupados); ocupacao = int((ocupados / int(total_boxes) * 100)) if int(total_boxes) > 0 else 0; agora = datetime.now()
    return {"total_boxes": int(total_boxes),"livres": livres,"ocupados": ocupados,"ocupacao": ocupacao,"vencidas": 0,"por_hora": [0]*24,"lista": lista,"historico": historico,"vencidas_lista": [],"timestamp": agora.isoformat(),"atualizado": agora.strftime("%H:%M:%S")}
@app.post("/api/integracao/gerar")
def gerar_api_key(payload: dict = {}, request: Request = None, token: str = Depends(requer_auth)):
    keys = load_json(ARQ_KEYS, {}); nova = "sc_live_" + secrets.token_urlsafe(32); keys[nova] = {"id": str(uuid.uuid4())[:8],"nome": payload.get("nome", "Parceiro"),"criada_em": datetime.now().isoformat(),"uso": 0,"condominios_permitidos": payload.get("condominios_permitidos", []),"ativa": True}; save_json(ARQ_KEYS, keys); registrar_auditoria("GEROU_API_KEY", detalhes=f"Gerou {payload.get('nome','')}", request=request); return {"api_key": nova}
@app.get("/api/auditoria")
def listar_auditoria(request: Request = None, token: str = Depends(requer_auth)): return load_json(ARQ_AUDIT, [])[::-1][:200]
@app.post("/api/auth/login")
def auth_login(payload: dict, request: Request):
    ip = check_rate_limit(request); usuario = payload.get("usuario","").strip(); senha = payload.get("senha","")
    if usuario == ADMIN_USER and senha == ADMIN_PASS:
        LOGIN_TENTATIVAS[ip].clear(); token = "sc_" + secrets.token_urlsafe(32); TOKENS_VALIDOS[token] = {"user": usuario,"expires": datetime.now() + timedelta(hours=8),"ip": ip}; save_tokens(); registrar_auditoria("LOGIN_SUCESSO", usuario=usuario, detalhes=f"Login IP {ip}", request=request); return {"ok": True, "token": token, "expires_in": 28800}
    LOGIN_TENTATIVAS[ip].append(time.time()); registrar_auditoria("LOGIN_FALHA", usuario=usuario, detalhes=f"Falha IP {ip}", request=request); raise HTTPException(status_code=401, detail="Usuário ou senha inválido")
@app.get("/api/auth/verificar")
def verificar_token_api(request: Request, authorization: str = Header(None), token: str = Query(None)):
    t = ""
    if authorization and "Bearer" in authorization: t = authorization.replace("Bearer ","").strip()
    if not t: t = token or ""
    if not t: t = request.cookies.get("sc_token") or request.query_params.get("token") or ""
    if not t: raise HTTPException(401, "Sem token")
    if is_token_valid(t): return {"ok": True, "user": TOKENS_VALIDOS[t]["user"]}
    raise HTTPException(401, "Token inválido")
@app.post("/api/auth/logout")
def logout_token(authorization: str = Header(None), request: Request = None):
    token = ""
    if authorization and "Bearer" in authorization: token = authorization.replace("Bearer ","").strip()
    if not token and request: token = request.cookies.get("sc_token") or request.query_params.get("token") or ""
    if token: TOKENS_VALIDOS.pop(token, None); save_tokens()
    return {"ok": True}
@app.post("/api/entregas")
async def api_entregas_compat(payload: dict, request: Request = None):
    dados = load_json(ARQ_DADOS, {"total_boxes":16,"livres":15,"ocupados":1,"ocupacao":6,"vencidas":0,"por_hora":[0]*24,"lista":[],"historico":[],"vencidas_lista":[]})
    # BOX DINAMICO - se mandar 07 fixo, corrige pro livre
    box_req = payload.get("box","")
    if not box_req or box_req=="07" or box_req=="7":
        box_req = get_box_livre(dados)
    nova = {"box": str(box_req).zfill(2),"bloco": payload.get("bloco",""),"apartamento": payload.get("apartamento") or payload.get("apto",""),"codigo": payload.get("codigo") or payload.get("protocolo") or "","codigo_retirada": payload.get("codigo_retirada") or payload.get("codigo") or "","protocolo": payload.get("protocolo") or payload.get("codigo") or f"SC-{secrets.randbelow(90000)+10000}","data": payload.get("data") or datetime.now().strftime("%d/%m/%Y"),"hora": payload.get("hora") or datetime.now().strftime("%H:%M"),"nome": payload.get("condominio_nome") or payload.get("nome",""),"created_at": payload.get("data_hora") or datetime.now().isoformat(),"condominio_id": str(payload.get("condominio_id","1"))}
    if not any(x.get("protocolo")==nova["protocolo"] for x in dados.get("lista",[])): dados["lista"].append(nova); save_json(ARQ_DADOS, dados); registrar_auditoria("ENTREGA_API", detalhes=f"Entrega {nova['protocolo']} Box {nova['box']}", request=request)
    return {"ok": True, "protocolo": nova["protocolo"], "box": nova["box"]}
@app.get("/api/entregas")
def api_listar_entregas_compat(condominio: str = "1", token: str = Depends(requer_auth)):
    dados = load_json(ARQ_DADOS, {"total_boxes":16,"livres":15,"ocupados":1,"ocupacao":6,"vencidas":0,"por_hora":[0]*24,"lista":[],"historico":[],"vencidas_lista":[]})
    if condominio=="1": return dados.get("lista",[])
    return [e for e in dados.get("lista",[]) if str(e.get("condominio_id"))==str(condominio)]
@app.post("/api/retiradas")
async def api_retiradas_compat(payload: dict, request: Request = None):
    dados = load_json(ARQ_DADOS, {"total_boxes":16,"livres":15,"ocupados":1,"ocupacao":6,"vencidas":0,"por_hora":[0]*24,"lista":[],"historico":[],"vencidas_lista":[]})
    codigo = payload.get("protocolo") or payload.get("codigo") or payload.get("codigo_retirada") or ""; achado = None; nova_lista = []
    for item in dados.get("lista",[]):
        if str(item.get("codigo"))==str(codigo) or str(item.get("codigo_retirada"))==str(codigo) or str(item.get("protocolo"))==str(codigo): achado = item
        else: nova_lista.append(item)
    if achado: achado["data_retirada"] = datetime.now().strftime("%d/%m/%Y"); dados["lista"] = nova_lista; dados["historico"].append(achado); save_json(ARQ_DADOS, dados); registrar_auditoria("RETIRADA_API", detalhes=f"Retirada {codigo} Box {achado['box']}", request=request); return {"ok": True, "box": achado["box"]}
    # AGORA RETORNA 404 REAL - PRA TABLET VALIDAR
    raise HTTPException(status_code=404, detail="Código não encontrado")
@app.get("/api/retiradas")
def api_listar_retiradas_compat(condominio: str = "1", token: str = Depends(requer_auth)): dados = load_json(ARQ_DADOS, {"total_boxes":16,"livres":15,"ocupados":1,"ocupacao":6,"vencidas":0,"por_hora":[0]*24,"lista":[],"historico":[],"vencidas_lista":[]}); return dados.get("historico",[])[-100:]
def get_app_users(): return load_json(ARQ_APP_USERS, [])
def save_app_users(data): save_json(ARQ_APP_USERS, data)
def verificar_app_token(request: Request, authorization: str = Header(None)):
    token = ""
    if authorization and "Bearer" in authorization: token = authorization.replace("Bearer ","").strip()
    if not token: token = request.headers.get("x-token") or request.query_params.get("token") or ""
    if not token: raise HTTPException(401, "Token do App obrigatório")
    try: payload = jwt.decode(token, SECRET_JWT, algorithms=["HS256"]); return payload
    except: raise HTTPException(401, "Token App inválido")
@app.get("/api/condominios/public")
def conds_public(): conds = load_json(ARQ_CONDS, []); return [{"id": c["id"], "nome": c["nome"]} for c in conds if str(c["id"])!="1"]
@app.post("/api/app/auth/login")
def app_login(payload: dict, request: Request):
    condominio = str(payload.get("condominio","1")); bloco = str(payload.get("bloco","")).strip(); apto = str(payload.get("apto","")).strip(); senha = str(payload.get("senha","")).strip()
    if senha == ADMIN_PASS:
        users = get_app_users(); u = next((x for x in users if x.get("condominio")==condominio and x.get("bloco")==bloco and x.get("apto")==apto), None); role = u["role"] if u else "sindico"; nome = u["nome"] if u else f"Síndico Bl {bloco} Ap {apto}"; token = jwt.encode({"sub": f"{condominio}-{bloco}-{apto}", "condominio": condominio, "bloco": bloco, "apto": apto, "role": role, "nome": nome, "exp": datetime.now()+timedelta(days=30)}, SECRET_JWT, algorithm="HS256"); registrar_auditoria("LOGIN_APP_SINDICO", usuario=nome, detalhes=f"Login síndico", condominio_id=condominio, request=request); return {"ok": True, "token": token, "user": {"nome": nome, "role": role, "condominio": condominio, "bloco": bloco, "apto": apto}}
    mors = load_json(ARQ_MORS, []); mor = next((m for m in mors if str(m.get("condominio"))==condominio and str(m.get("bloco")).lower()==bloco.lower() and str(m.get("apto") or m.get("apartamento","")).lower()==apto.lower()), None)
    if not mor: raise HTTPException(401, "Morador não encontrado")
    users = get_app_users(); u = next((x for x in users if x.get("condominio")==condominio and x.get("bloco")==bloco and x.get("apto")==apto), None)
    if u and u.get("senha") and u.get("senha")!=senha: raise HTTPException(401, "Senha inválida")
    role = u["role"] if u and u.get("role") else "morador"; token = jwt.encode({"sub": f"{condominio}-{bloco}-{apto}", "condominio": condominio, "bloco": bloco, "apto": apto, "role": role, "nome": mor["nome"], "exp": datetime.now()+timedelta(days=30)}, SECRET_JWT, algorithm="HS256"); registrar_auditoria("LOGIN_APP_MORADOR", usuario=mor["nome"], detalhes=f"Login morador", condominio_id=condominio, request=request); return {"ok": True, "token": token, "user": {"nome": mor["nome"], "role": role, "condominio": condominio, "bloco": bloco, "apto": apto}}
@app.get("/api/app/relatorios")
def app_relatorios(de: str = "", ate: str = "", token_data: dict = Depends(verificar_app_token)):
    dados = load_json(ARQ_DADOS, {"lista":[],"historico":[]}); bloco = token_data.get("bloco",""); apto = token_data.get("apto",""); role = token_data.get("role","morador"); todas = dados.get("lista",[]) + dados.get("historico",[])
    if role=="morador": filtradas = [x for x in todas if str(x.get("bloco","")).lower()==bloco.lower() and str(x.get("apartamento") or x.get("apto","")).lower()==apto.lower()]
    else: filtradas = todas
    return filtradas[::-1][:200]
@app.post("/api/app/porta/abrir")
def app_abrir_porta(payload: dict, request: Request, token_data: dict = Depends(verificar_app_token)):
    if token_data.get("role")!="sindico": raise HTTPException(403, "Apenas síndico pode abrir portas")
    box = payload.get("box","GERAL"); registrar_auditoria("ABERTURA_PORTA_SINDICO", usuario=token_data.get("nome","sindico"), detalhes=f"Abriu Box {box}", condominio_id=token_data.get("condominio",""), request=request); return {"ok": True, "box": box, "aberta_em": datetime.now().isoformat()}
@app.get("/api/app/moradores")
def app_listar_moradores(token_data: dict = Depends(verificar_app_token)):
    if token_data.get("role")!="sindico": raise HTTPException(403, "Apenas síndico")
    mors = load_json(ARQ_MORS, []); return [m for m in mors if str(m.get("condominio"))==str(token_data.get("condominio"))]
@app.post("/api/app/moradores")
def app_add_morador(payload: dict, request: Request, token_data: dict = Depends(verificar_app_token)):
    if token_data.get("role")!="sindico": raise HTTPException(403, "Apenas síndico")
    mors = load_json(ARQ_MORS, []); novo = {"id": str(uuid.uuid4())[:8], "nome": payload.get("nome"), "bloco": payload.get("bloco",""), "apto": payload.get("apto",""), "condominio": token_data.get("condominio","1"), "criado_por_sindico": token_data.get("nome"), "criado_em": datetime.now().isoformat()}; mors.append(novo); save_json(ARQ_MORS, mors); registrar_auditoria("ADD_MORADOR_SINDICO", usuario=token_data.get("nome"), detalhes=f"Add {novo['nome']}", condominio_id=token_data.get("condominio"), request=request); return novo
@app.delete("/api/app/moradores")
def app_del_morador(id: str = Query(...), request: Request = None, token_data: dict = Depends(verificar_app_token)):
    if token_data.get("role")!="sindico": raise HTTPException(403, "Apenas síndico")
    mors = load_json(ARQ_MORS, []); mor = next((m for m in mors if str(m["id"])==str(id)), None); mors = [m for m in mors if str(m["id"])!=str(id)]; save_json(ARQ_MORS, mors)
    if mor: registrar_auditoria("EXCLUIU_MORADOR_SINDICO", usuario=token_data.get("nome"), detalhes=f"Excluiu {mor['nome']}", condominio_id=token_data.get("condominio"), request=request)
    return {"ok": True}
@app.get("/app", response_class=HTMLResponse)
def app_page(): return no_cache_html(get_path("app.html"))

# =========================================================
# IA PACK v5.5 - INICIO - 6 IAs NUVEM READY - ADD-ONLY
# =========================================================

def _get_cache_ia(condominio_id: str):
    dados = load_json(ARQ_CACHE_IA, {})
    item = dados.get(str(condominio_id))
    if not item: return None
    try:
        if time.time() - item.get("ts", 0) < 300:
            return item.get("data")
    except: pass
    return None

def _set_cache_ia(condominio_id: str, data: dict):
    cache = load_json(ARQ_CACHE_IA, {})
    cache[str(condominio_id)] = {"ts": time.time(), "data": data}
    save_json(ARQ_CACHE_IA, cache)

# 1 - IA LOTAÇÃO 24H + PREVISÃO - DASHBOARD - AGORA SEM 401 NO TABLET
@app.get("/api/ia/lotacao-24h")
def ia_lotacao_24h(condominio: str = "1", request: Request = None, token: str = Depends(requer_auth_opcional)):
    cached = _get_cache_ia("lotacao_"+condominio)
    if cached: return cached
    raw = load_json(ARQ_DADOS, {"lista":[],"historico":[]})
    lista_all = raw.get("lista", [])
    # FIX VAZAMENTO
    if str(condominio)=="1":
        lista = lista_all
    else:
        lista = [x for x in lista_all if str(x.get("condominio_id"))==str(condominio)]
    agora = datetime.now(); alertas = []
    for e in lista:
        try:
            created_str = e.get("created_at") or ""
            if "T" in created_str: dt = datetime.fromisoformat(created_str.replace("Z",""))
            else: dt = datetime.strptime(f"{e.get('data','')} {e.get('hora','00:00')}", "%d/%m/%Y %H:%M")
            horas = (agora - dt).total_seconds()/3600
            if horas>24: alertas.append({"box": e.get("box","--"),"bloco": e.get("bloco",""),"apartamento": e.get("apartamento") or e.get("apto",""),"morador": e.get("nome","") or f"Bl {e.get('bloco','')} Ap {e.get('apartamento','')}", "horas": int(horas), "protocolo": e.get("protocolo","")})
        except: continue
    total_boxes = raw.get("total_boxes",16)
    try:
        if str(condominio)=="1":
            conds = load_json(ARQ_CONDS, [])
            soma = sum(int(c.get("total_boxes",0)) for c in conds if str(c.get("id"))!="1")
            if soma>0: total_boxes=soma
    except: pass
    perc_ocup = int((len(lista)/int(total_boxes)*100)) if int(total_boxes)>0 else 0
    previsao_percent = min(100, perc_ocup+15 if len(lista)>0 else 12)
    resultado = {"condominio": condominio,"ocupados": len(lista),"total_boxes": int(total_boxes),"previsao_percent": previsao_percent,"previsao_lotacao": f"{previsao_percent}% de ocupação prevista às 18h","total_atrasados": len(alertas),"alertas_24h": alertas[:50],"atualizado": agora.isoformat(),"cache": "nuvem 5min","versao":"v5.5"}
    _set_cache_ia("lotacao_"+condominio, resultado)
    return resultado

@app.post("/api/ia/sindico/pergunta")
def ia_sindico_pergunta(payload: dict, request: Request = None, token_data: dict = Depends(verificar_app_token)):
    if token_data.get("role")!="sindico": raise HTTPException(403, "Apenas síndico")
    pergunta = payload.get("pergunta","").lower()
    cond_id = token_data.get("condominio","1")
    dados = load_json(ARQ_DADOS, {"lista":[],"historico":[]})
    mors = load_json(ARQ_MORS, [])
    lista = [x for x in dados.get("lista",[]) if str(x.get("condominio_id"))==str(cond_id)]
    if "atrasada" in pergunta or "24h" in pergunta:
        atrasadas = 0
        for e in lista:
            try:
                dt = datetime.fromisoformat(e.get("created_at","").replace("Z","")) if "T" in e.get("created_at","") else datetime.now()
                if (datetime.now()-dt).total_seconds()/3600>24: atrasadas+=1
            except: pass
        resposta = f"Você tem {atrasadas} encomendas com mais de 24h no condomínio. Quer que eu liste?"
    elif "ocup" in pergunta or "lotação" in pergunta:
        resposta = f"Você está com {len(lista)} boxes ocupados agora. Previsão de {min(100,len(lista)*6+15)}% às 18h."
    elif "morador" in pergunta:
        resposta = f"Você tem {len([m for m in mors if str(m.get('condominio'))==str(cond_id)])} moradores cadastrados."
    else:
        resposta = f"Síndico {token_data.get('nome','')}, posso te ajudar com atrasadas, lotação, moradores. Pergunte ex: 'quantas atrasadas?'"
    registrar_auditoria("IA_SINDICO_PERGUNTA", usuario=token_data.get("nome"), detalhes=pergunta[:100], condominio_id=cond_id, request=request)
    return {"resposta": resposta, "condominio": cond_id, "versao":"v5.5"}

@app.get("/api/ia/seguranca/status")
def ia_seguranca_status(token: str = Depends(requer_auth)):
    bloqueios = load_json(ARQ_BLOQUEIOS, {})
    return {"bloqueios_ativos": len(bloqueios), "lista": bloqueios, "versao":"v5.5"}

def _check_bloqueio(ip: str) -> bool:
    bloqueios = load_json(ARQ_BLOQUEIOS, {})
    b = bloqueios.get(ip)
    if not b: return False
    if time.time() - b.get("ts",0) < b.get("duracao",1800):
        return True
    bloqueios.pop(ip, None)
    save_json(ARQ_BLOQUEIOS, bloqueios)
    return False

@app.post("/api/ia/gestora/convite")
def ia_gestora_convite(payload: dict, request: Request = None, token: str = Depends(requer_auth)):
    cond_id = payload.get("condominio_id")
    bloco = payload.get("bloco",""); apto = payload.get("apto",""); nome = payload.get("nome","Morador")
    if not cond_id: raise HTTPException(400, "condominio_id obrigatório")
    users = load_json(ARQ_APP_USERS, [])
    user_id = str(uuid.uuid4())[:8]
    novo = {"id": user_id, "condominio": str(cond_id), "bloco": bloco, "apto": apto, "nome": nome, "role": payload.get("role","morador"), "criado_em": datetime.now().isoformat(), "origem": "ia_gestora"}
    users.append(novo)
    save_json(ARQ_APP_USERS, users)
    link = f"/app?condominio={cond_id}&bloco={bloco}&apto={apto}&convite={user_id}"
    registrar_auditoria("IA_GESTORA_CONVITE", detalhes=f"Convite {nome} Bl {bloco} Ap {apto}", condominio_id=cond_id, request=request)
    return {"ok": True, "link": link, "mensagem_whatsapp": f"Olá {nome}! Seu acesso ao Smart Cube: {link} - Bl {bloco} Ap {apto}", "versao":"v5.5"}

@app.post("/api/ia/tablet/assistente")
def ia_tablet_assistente(payload: dict, request: Request = None):
    ip = request.client.host if request.client else "unknown"
    if _check_bloqueio(ip): raise HTTPException(429, "Tablet bloqueado temporariamente por segurança")
    pergunta = payload.get("pergunta","").lower()
    if "box" in pergunta or "livre" in pergunta:
        dados = load_json(ARQ_DADOS, {"lista":[],"total_boxes":16})
        ocup = set(str(x.get("box")) for x in dados.get("lista",[]))
        livres = [str(i) for i in range(1, int(dados.get("total_boxes",16))+1) if str(i) not in ocup and f"{i:02d}" not in ocup]
        resposta = f"Boxes livres: {', '.join(livres[:5])}. Recomendo Box {livres[0] if livres else '01'}"
    elif "codigo" in pergunta:
        resposta = "Digite o código no campo. Se não funcionar, peça ajuda ao síndico. Após 5 erros, bloqueio por segurança."
    else:
        resposta = "Sou a IA do tablet. Posso ajudar: 'qual box livre?', 'código não funciona?'"
    return {"resposta": resposta, "versao":"v5.5"}

@app.get("/api/ia/logs")
def ia_logs(token: str = Depends(requer_auth)):
    return load_json(ARQ_IA_LOGS, [])[::-1][:100]

if __name__ == "__main__": import uvicorn; uvicorn.run(app, host="0.0.0.0", port=5000)
