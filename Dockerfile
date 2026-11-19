# SmartCube - Dockerfile v2 - corrigido
FROM python:3.11-slim

# CORRIGIDO: trava timezone + python sem buffer, pra log sair na hora
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=America/Sao_Paulo

WORKDIR /app

# CORRIGIDO: instala curl pra healthcheck + dependência de build, e limpa depois
# Antes faltava curl, o healthcheck do docker-compose falhava
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# CORRIGIDO: cria usuário não-root ANTES de copiar código
# Antes rodava como root - se invadem o container, viram root do host
RUN useradd -m -u 1000 appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# CORRIGIDO: copia só o que precisa, não .env, não moradores.json, não .git
# Antes COPY . . copiava .env com SECRET_JWT, moradores.json com 232 nomes, .git
# Pra isso funcionar, cria o .dockerignore do próximo bloco
COPY main.py .
COPY database.py .
COPY requirements.txt .
COPY static/ ./static/
COPY templates/ ./templates/

# CORRIGIDO: pasta de dados com permissão pro appuser, sem ser root
RUN mkdir -p /app/data /app/logs && chown -R appuser:appuser /app

# CORRIGIDO: troca pra não-root
USER appuser

# CORRIGIDO: healthcheck dentro da imagem, funciona mesmo sem compose
HEALTHCHECK --interval=10s --timeout=5s --retries=5 --start-period=15s \
    CMD curl -f http://localhost:8000/api/health || exit 1

EXPOSE 8000

# Mantido: mesmo comando original, mesmo host, mesma porta
# Na nuvem o compose usa gunicorn por cima, mas local continua uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
