from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime
import os
import requests

app = Flask(__name__)
# Configuração explícita do CORS para permitir todas as origens, métodos e headers
CORS(app, 
     resources={r"/*": {
         "origins": "*",
         "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
         "allow_headers": ["Content-Type", "Authorization", "X-API-Key"]
     }})

# Segurança simples por token
API_KEY = os.environ.get("API_KEY", "MINHA_CHAVE")

# Configuração da API externa de monitoramento
EXTERNAL_API_URL = os.environ.get("EXTERNAL_API_URL", "https://teste.net")
EXTERNAL_API_KEY = os.environ.get("EXTERNAL_API_KEY", "123456789")

# Estado desejado e último estado aplicado (em memória)
STATE = {
    "desired": "off",
    "last_applied": "off",
    "last_seen": None,
    "manual_desired_used": False  # Flag para rastrear se o desired manual já foi usado uma vez
}

def _validate_api_key():
    """
    Valida a api_key da requisição.
    Aceita api_key via querystring, form, JSON ou header.
    Retorna (True, api_key) se válida, (False, None) caso contrário.
    """
    data = {}
    data.update(request.args.to_dict(flat=True))
    if request.form:
        data.update(request.form.to_dict(flat=True))
    if request.is_json:
        js = request.get_json(silent=True) or {}
        if isinstance(js, dict):
            data.update(js)
    
    # Aceita api_key, apikey (sem underscore) ou key na querystring/form/JSON
    api_key = (data.get("api_key") or data.get("apikey") or data.get("key") or "").strip()
    
    # Também aceita no header X-API-Key
    header_key = request.headers.get("X-API-Key", "").strip()
    
    # Verifica se alguma das chaves corresponde
    final_key = api_key or header_key
    
    # Debug: log para identificar o problema (remover em produção)
    if not final_key or final_key != API_KEY:
        print(f"[DEBUG] API_KEY esperada: '{API_KEY}'")
        print(f"[DEBUG] Chave recebida (querystring/form/json): '{api_key}'")
        print(f"[DEBUG] Chave recebida (header): '{header_key}'")
        print(f"[DEBUG] Chave final usada: '{final_key}'")
        print(f"[DEBUG] Match: {final_key == API_KEY}")
        return False, None
    return True, final_key

def fetch_pm25_data():
    """
    Busca dados de pm25 da API externa.
    Retorna lista de valores de pm25 ou None em caso de erro.
    """
    try:
        url = f"{EXTERNAL_API_URL}?last_minutes=15&api_key={EXTERNAL_API_KEY}"
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        if data.get("ok") and "series" in data:
            pm25_values = data["series"].get("pm25", [])
            # Remove valores None e converte para float
            pm25_values = [float(v) for v in pm25_values if v is not None]
            return pm25_values
        return None
    except Exception as e:
        print(f"[ERROR] Erro ao buscar dados da API externa: {e}")
        return None

def detect_drastic_increase(pm25_values):
    """
    Detecta aumento drástico de 15 ou mais no pm25 entre leituras consecutivas.
    Retorna (True, aumento, valor_anterior, valor_atual) se detectar aumento drástico,
    (False, None, None, None) caso contrário.
    """
    if not pm25_values or len(pm25_values) < 2:
        return False, None, None, None
    
    # Verifica aumentos consecutivos de 15 ou mais
    for i in range(1, len(pm25_values)):
        increase = pm25_values[i] - pm25_values[i-1]
        if increase >= 15:
            print(f"[INFO] Aumento drástico detectado: {pm25_values[i-1]} -> {pm25_values[i]} (aumento de {increase})")
            return True, increase, pm25_values[i-1], pm25_values[i]
    
    return False, None, None, None

def compute_desired_state():
    """
    Exemplo de regra: liga entre 08:00 e 20:00, fora disso desliga.
    Troque por sua lógica real (condições, agenda, sensor, etc.).
    """
    now = datetime.now()
    hour = now.hour
    return "on" if 8 <= hour < 20 else "off"

@app.get("/rele")
def get_rele():
    is_valid, _ = _validate_api_key()
    if not is_valid:
        return jsonify(
            ok=False, 
            error="unauthorized",
            hint="Envie api_key via querystring (?api_key=...), form, JSON ou header X-API-Key"
        ), 401

    # Busca dados de pm25 para análise
    pm25_values = fetch_pm25_data()
    has_drastic_increase = False
    increase_amount = None
    previous_value = None
    current_value = None
    
    if pm25_values:
        has_drastic_increase, increase_amount, previous_value, current_value = detect_drastic_increase(pm25_values)
    
    # Se o desired foi definido manualmente e ainda não foi usado, retorna o valor manual
    if not STATE["manual_desired_used"]:
        # Primeira execução depois do POST manual: retorna o valor definido manualmente
        STATE["manual_desired_used"] = True  # Marca como usado
        # Mantém o desired atual (definido pelo POST)
    else:
        # A partir da segunda execução: recalcula baseado na detecção de pm25
        if pm25_values:
            # Se detecta aumento drástico, desired é "on", caso contrário é "off"
            if has_drastic_increase:
                STATE["desired"] = "on"
                STATE["last_applied"] = "on"
                STATE["last_seen"] = datetime.now().isoformat(timespec="seconds")
            else:
                STATE["desired"] = "off"
                STATE["last_applied"] = "off"
        else:
            # Se não conseguir buscar dados da API, usa a lógica inicial (horário)
            desired = compute_desired_state()
            STATE["desired"] = desired
            # Mantém o valor atual de last_applied se não conseguir buscar dados

    response_data = {
        "ok": True,
        "desired": STATE["desired"],
        "last_applied": STATE["last_applied"],
        "last_seen": STATE["last_seen"],
        "pm25_detected_increase": has_drastic_increase
    }
    
    # Adiciona informações de debug sobre o aumento detectado
    if has_drastic_increase:
        response_data["pm25_increase_amount"] = increase_amount
        response_data["pm25_previous_value"] = previous_value
        response_data["pm25_current_value"] = current_value
    
    return jsonify(response_data), 200

@app.post("/rele")
def post_rele():
    is_valid, _ = _validate_api_key()
    if not is_valid:
        return jsonify(
            ok=False, 
            error="unauthorized",
            hint="Envie api_key via querystring (?api_key=...), form, JSON ou header X-API-Key"
        ), 401

    data = request.get_json(silent=True) or {}
    applied = data.get("applied")
    desired = data.get("desired")  # Campo opcional para definir manualmente o estado desejado

    if applied not in ("on", "off"):
        return jsonify(ok=False, error="invalid_applied", hint="applied must be 'on' or 'off'"), 400

    # Se desired for fornecido, valida e atualiza o estado desejado manualmente
    if desired is not None:
        if desired not in ("on", "off"):
            return jsonify(ok=False, error="invalid_desired", hint="desired must be 'on' or 'off'"), 400
        STATE["desired"] = desired
        STATE["manual_desired_used"] = False  # Reseta a flag para permitir que o próximo GET use o valor manual

    STATE["last_applied"] = applied
    STATE["last_seen"] = datetime.now().isoformat(timespec="seconds")

    return jsonify(ok=True, desired=STATE["desired"], recorded=True), 200

if __name__ == "__main__":
    # Em produção, prefira gunicorn/uwsgi atrás de um proxy.
    app.run(host="0.0.0.0", port=5000, debug=False)