FROM python:3.11-slim

WORKDIR /app

# Evita .pyc e deixa log na hora
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Dependências do sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Requirements primeiro (cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código - SÓ o que existe no seu repo hoje
COPY main.py .
COPY database.py .
COPY static/ ./static/
COPY templates/ ./templates/

# Se não tiver static/ ou templates/ no repo, comenta as 2 linhas acima
# Se tiver outros .py, adiciona aqui: COPY outro_arquivo.py .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
