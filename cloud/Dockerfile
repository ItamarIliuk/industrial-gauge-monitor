# Usa imagem oficial leve do Python
FROM python:3.11-slim

# Impede que o Python gere arquivos .pyc e permite logs em tempo real
ENV PYTHONUNBUFFERED True
ENV APP_HOME /app

WORKDIR $APP_HOME

# Instala dependências
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o código da aplicação
COPY main.py .

# Comando para rodar o Gunicorn (servidor WSGI de produção)
# Workers=1 e Threads=8 é uma configuração recomendada para Cloud Run
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 main:app