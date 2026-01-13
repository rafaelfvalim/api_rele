from flask import Flask, request, jsonify
from datetime import datetime
import os

app = Flask(__name__)

# Segurança simples por token
API_KEY = os.environ.get("API_KEY", "MINHA_CHAVE")

# Estado desejado e último estado aplicado (em memória)
STATE = {
    "desired": "off",
    "last_applied": "off",
    "last_seen": None
}

def authorized(req):
    return req.headers.get("X-API-Key") == API_KEY

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
    if not authorized(request):
        return jsonify(ok=False, error="unauthorized"), 401

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
    if not authorized(request):
        return jsonify(ok=False, error="unauthorized"), 401

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