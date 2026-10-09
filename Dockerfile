FROM python:3.12-slim

# iputils-ping -- usado pelo widget de status (admin.py:check_ping) pra
# checar se o host de um cliente está no ar via ICMP, em vez de depender
# de um serviço HTTP específico estar escutando numa porta certa.
RUN apt-get update && apt-get install -y --no-install-recommends iputils-ping \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "chat:app", "--host", "0.0.0.0", "--port", "8000"]
