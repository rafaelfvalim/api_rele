# Usar imagem Python oficial baseada em Debian slim
FROM python:3.11-slim

# Definir diretório de trabalho
WORKDIR /app

# Copiar arquivo de dependências
COPY requirements.txt .

# Instalar dependências
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código da aplicação
COPY app.py .

# Expor porta da aplicação
EXPOSE 5000

# Variável de ambiente para produção
ENV FLASK_APP=app.py
ENV PYTHONUNBUFFERED=1

# Comando para executar a aplicação
CMD ["python", "app.py"]
