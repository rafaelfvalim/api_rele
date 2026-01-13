from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime
import os

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

# Estado desejado e último estado aplicado (em memória)
STATE = {
    "desired": "off",
    "last_applied": "off",
    "last_seen": None
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

    desired = compute_desired_state()
    STATE["desired"] = desired

    return jsonify(
        ok=True,
        desired=STATE["desired"],
        last_applied=STATE["last_applied"],
        last_seen=STATE["last_seen"]
    ), 200

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

    if applied not in ("on", "off"):
        return jsonify(ok=False, error="invalid_applied", hint="applied must be 'on' or 'off'"), 400

    STATE["last_applied"] = applied
    STATE["last_seen"] = datetime.now().isoformat(timespec="seconds")

    return jsonify(ok=True, desired=STATE["desired"], recorded=True), 200

if __name__ == "__main__":
    # Em produção, prefira gunicorn/uwsgi atrás de um proxy.
    app.run(host="0.0.0.0", port=5000, debug=False)