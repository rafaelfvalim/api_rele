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
    Busca dados de pm2_5 da API externa (tabela entries_sps30).
    Retorna lista de valores de pm2_5 ou None em caso de erro.
    """
    try:
        url = f"{EXTERNAL_API_URL}?last_minutes=15&api_key={EXTERNAL_API_KEY}"
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        if data.get("ok") and "series" in data:
            # Adaptado para nova estrutura: busca pm2_5 ao invés de pm25
            pm25_values = data["series"].get("pm2_5", data["series"].get("pm25", []))
            # Remove valores None e converte para float
            pm25_values = [float(v) for v in pm25_values if v is not None]
            return pm25_values
        return None
    except Exception as e:
        print(f"[ERROR] Erro ao buscar dados da API externa: {e}")
        return None

def fetch_pm25_data_by_range(start_date, end_date):
    """
    Busca dados de pm2_5 da API externa por range de datas (tabela entries_sps30).
    Retorna (labels, pm25_values) ou (None, None) em caso de erro.
    """
    try:
        url = f"{EXTERNAL_API_URL}?start={start_date}&end={end_date}&api_key={EXTERNAL_API_KEY}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data.get("ok") and "series" in data and "labels" in data:
            labels = data.get("labels", [])
            # Adaptado para nova estrutura: busca pm2_5 ao invés de pm25
            pm25_values = data["series"].get("pm2_5", data["series"].get("pm25", []))
            # Remove valores None e mantém correspondência com labels
            filtered_data = [(label, float(val)) for label, val in zip(labels, pm25_values) if val is not None]
            if filtered_data:
                labels_filtered, values_filtered = zip(*filtered_data)
                return list(labels_filtered), list(values_filtered)
        return None, None
    except Exception as e:
        print(f"[ERROR] Erro ao buscar dados da API externa por range: {e}")
        return None, None

def detect_drastic_increase(pm25_values):
    """
    Detecta aumento drástico de 15 ou mais no pm2_5 entre leituras consecutivas.
    Verifica todos os aumentos e retorna o maior aumento encontrado.
    Retorna (True, aumento, valor_anterior, valor_atual) se detectar aumento drástico,
    (False, None, None, None) caso contrário.
    """
    if not pm25_values or len(pm25_values) < 2:
        return False, None, None, None
    
    # Debug: mostra os valores recebidos
    print(f"[DEBUG] Valores pm2_5 recebidos: {pm25_values}")
    print(f"[DEBUG] Total de valores: {len(pm25_values)}")
    
    # Verifica todos os aumentos consecutivos e encontra o maior
    max_increase = 0
    max_previous = None
    max_current = None
    
    for i in range(1, len(pm25_values)):
        increase = pm25_values[i] - pm25_values[i-1]
        print(f"[DEBUG] Comparando: {pm25_values[i-1]} -> {pm25_values[i]} (aumento: {increase})")
        if increase >= 15 and increase > max_increase:
            max_increase = increase
            max_previous = pm25_values[i-1]
            max_current = pm25_values[i]
    
    if max_increase >= 15:
        print(f"[INFO] Aumento drástico detectado: {max_previous} -> {max_current} (aumento de {max_increase})")
        return True, max_increase, max_previous, max_current
    
    print(f"[DEBUG] Nenhum aumento drástico detectado (limiar: 15)")
    return False, None, None, None

def parse_timestamp(ts_str):
    """
    Converte string de timestamp para datetime.
    Aceita formatos ISO com ou sem Z.
    """
    if not ts_str:
        return None
    try:
        # Remove Z se presente
        ts_str = ts_str.rstrip('Z')
        # Tenta diferentes formatos
        for fmt in ["%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"]:
            try:
                return datetime.strptime(ts_str, fmt)
            except ValueError:
                continue
        return datetime.fromisoformat(ts_str.replace('Z', ''))
    except Exception:
        return None

def find_all_drastic_increases(labels, pm25_values):
    """
    Encontra todos os aumentos drásticos de 15 ou mais no pm2_5.
    Agrupa ocorrências próximas (dentro de 5 minutos) e retorna apenas o primeiro de cada sequência.
    Retorna lista de ocorrências com timestamp, valor anterior, valor atual e aumento.
    """
    if not pm25_values or len(pm25_values) < 2:
        return []
    
    all_occurrences = []
    
    # Primeiro, encontra todos os aumentos drásticos
    for i in range(1, len(pm25_values)):
        increase = pm25_values[i] - pm25_values[i-1]
        if increase >= 15:
            occurrence = {
                "timestamp": labels[i] if i < len(labels) else None,
                "previous_value": pm25_values[i-1],
                "current_value": pm25_values[i],
                "increase": increase,
                "index": i
            }
            all_occurrences.append(occurrence)
    
    if not all_occurrences:
        return []
    
    # Agrupa ocorrências próximas (dentro de 5 minutos) e mantém apenas a primeira
    filtered_occurrences = []
    last_timestamp = None
    
    for occurrence in all_occurrences:
        current_timestamp = parse_timestamp(occurrence["timestamp"])
        
        if current_timestamp is None:
            # Se não conseguir parsear, adiciona de qualquer forma
            filtered_occurrences.append({
                "timestamp": occurrence["timestamp"],
                "previous_value": occurrence["previous_value"],
                "current_value": occurrence["current_value"],
                "increase": occurrence["increase"]
            })
            last_timestamp = None
            continue
        
        # Se é a primeira ocorrência ou está a mais de 5 minutos da anterior
        if last_timestamp is None:
            filtered_occurrences.append({
                "timestamp": occurrence["timestamp"],
                "previous_value": occurrence["previous_value"],
                "current_value": occurrence["current_value"],
                "increase": occurrence["increase"]
            })
            last_timestamp = current_timestamp
        else:
            # Calcula diferença em minutos
            time_diff = (current_timestamp - last_timestamp).total_seconds() / 60
            if time_diff > 5:
                # Mais de 5 minutos de diferença, adiciona como nova ocorrência
                filtered_occurrences.append({
                    "timestamp": occurrence["timestamp"],
                    "previous_value": occurrence["previous_value"],
                    "current_value": occurrence["current_value"],
                    "increase": occurrence["increase"]
                })
                last_timestamp = current_timestamp
            # Se está dentro de 5 minutos, ignora (já temos a primeira da sequência)
    
    return filtered_occurrences

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

    # Busca dados de pm2_5 para análise (tabela entries_sps30)
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
        # A partir da segunda execução: recalcula baseado na detecção de pm2_5
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

@app.get("/rele/picos")
def get_picos():
    """
    Retorna os picos de aumento drástico de pm2_5 em um range de datas (tabela entries_sps30).
    Parâmetros: start (data inicial), end (data final), api_key
    """
    is_valid, _ = _validate_api_key()
    if not is_valid:
        return jsonify(
            ok=False, 
            error="unauthorized",
            hint="Envie api_key via querystring (?api_key=...), form, JSON ou header X-API-Key"
        ), 401

    # Obtém parâmetros de data
    start_date = request.args.get("start")
    end_date = request.args.get("end")
    
    if not start_date or not end_date:
        return jsonify(
            ok=False,
            error="missing_parameters",
            hint="Parâmetros 'start' e 'end' são obrigatórios. Formato: YYYY-MM-DDTHH:MM:SSZ ou YYYY-MM-DDTHH:MM:SS"
        ), 400

    # Busca dados da API externa por range de datas
    labels, pm25_values = fetch_pm25_data_by_range(start_date, end_date)
    
    if labels is None or pm25_values is None:
        return jsonify(
            ok=False,
            error="data_fetch_failed",
            hint="Não foi possível buscar dados da API externa para o range de datas especificado"
        ), 500

    # Encontra todos os aumentos drásticos
    occurrences = find_all_drastic_increases(labels, pm25_values)
    
    response_data = {
        "ok": True,
        "start_date": start_date,
        "end_date": end_date,
        "total_occurrences": len(occurrences),
        "occurrences": occurrences
    }
    
    return jsonify(response_data), 200

if __name__ == "__main__":
    # Em produção, prefira gunicorn/uwsgi atrás de um proxy.
    app.run(host="0.0.0.0", port=5000, debug=False)