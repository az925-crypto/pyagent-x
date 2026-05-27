import os
import json
import time
import asyncio
import threading
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory
from dotenv import load_dotenv

load_dotenv()

from agent.provider import create_provider, get_model, get_provider_info, recreate_provider
from agent.shared import SYSTEM_PROMPT
from tools.scan import resolve_dns, resolve_mx, scan_target
from tools.orchestrator import run_ig, run_sherlock, run_scan
from utils import validate_target, fetch_geoip, resolve_target_data

app = Flask(__name__, static_folder="web/static", template_folder="web/templates")

_ai = None

ALLOWED_ORIGINS = {"http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:5173", "http://127.0.0.1:5173"}

_rate_limit_store = {}
_rate_limit_lock = threading.Lock()
RATE_LIMIT_WINDOW_MS = 60 * 1000
RATE_LIMIT_MAX = 30
RATE_LIMIT_CLEANUP_INTERVAL = 300


def _rate_limit_cleanup():
    now = int(time.time() * 1000)
    with _rate_limit_lock:
        expired = [ip for ip, ts_list in _rate_limit_store.items() if all(now - t >= RATE_LIMIT_WINDOW_MS for t in ts_list)]
        for ip in expired:
            del _rate_limit_store[ip]

def rate_limit_middleware():
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            ip = request.remote_addr or "unknown"
            now = int(time.time() * 1000)
            with _rate_limit_lock:
                window = _rate_limit_store.get(ip, [])
                window = [t for t in window if now - t < RATE_LIMIT_WINDOW_MS]
                if len(window) >= RATE_LIMIT_MAX:
                    return jsonify({"error": "Rate limit exceeded. Try again later."}), 429
                window.append(now)
                _rate_limit_store[ip] = window
            return f(*args, **kwargs)
        return wrapped
    return decorator


def origin_check():
    origin = request.headers.get("Origin", "")
    if origin and origin not in ALLOWED_ORIGINS:
        return jsonify({"error": "Forbidden origin"}), 403
    return None

def get_ai():
    global _ai
    if _ai is None:
        try:
            _ai = create_provider()
        except Exception:
            pass
    return _ai


@app.route("/")
def index():
    return send_from_directory(app.template_folder, "index.html")


@app.route("/api/status")
def api_status():
    provider_type = os.environ.get("AI_PROVIDER", "gemini")
    key_status = (
        bool(os.environ.get("OPENROUTER_API_KEY"))
        if provider_type == "openrouter"
        else bool(os.environ.get("ZEN_API_KEY"))
        if provider_type == "zen"
        else bool(os.environ.get("GEMINI_API_KEY"))
    )
    if not key_status:
        return jsonify({"aiStatus": "NOT_CONFIGURED", "provider": provider_type})
    ai = get_ai()
    if not ai:
        return jsonify({"aiStatus": "ERROR", "reason": "AI Client not initialized", "provider": provider_type})
    model = get_model()
    try:
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(
            ai.generate_content(
                model=model,
                contents=[{"role": "user", "parts": [{"text": "ping"}]}],
                config={"maxOutputTokens": 5},
            )
        )
        loop.close()
        return jsonify({"aiStatus": "CONNECTED", "provider": provider_type, "model": model})
    except Exception as e:
        return jsonify({"aiStatus": "ERROR", "reason": str(e), "provider": provider_type, "model": model})


@app.route("/api/admin/reload-provider", methods=["POST"])
@rate_limit_middleware()
def reload_provider():
    global _ai
    try:
        _ai = recreate_provider()
        info = get_provider_info()
        return jsonify({"success": True, "provider": info["type"], "model": info["model"]})
    except Exception as e:
        _ai = None
        return jsonify({"error": str(e)}), 500


@app.route("/api/osint/scan", methods=["POST"])
@rate_limit_middleware()
def osint_scan():
    origin_err = origin_check()
    if origin_err:
        return origin_err

    ai = get_ai()
    if not ai:
        return jsonify({"error": "AI provider is not configured."}), 500

    data = request.get_json(silent=True)
    target = (data or {}).get("target")
    if not validate_target(target):
        return jsonify({"error": "Invalid target payload."}), 400

    target_type = target["type"].upper()
    target_value = target["value"].strip().lower()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        resolved_ips, geo_data = loop.run_until_complete(
            resolve_target_data(target_type, target_value, resolve_dns, resolve_mx, fetch_geoip)
        )

        prompt = f"""Perform security and OSINT analysis based on the following REAL DATA just resolved by our server:
Target: {target_value}
Target Type: {target_type}

[REAL INFRASTRUCTURE DATA]
- {"MX Records" if target_type == "EMAIL" else "IP Resolution"}: {", ".join(resolved_ips) if resolved_ips else "Could not resolve"}
- GeoIP Location: {geo_data.get("city", "") + ", " + geo_data.get("country", "") if geo_data.get("city") else "Unknown/Not applicable"}
- Organization/ISP: {geo_data.get("organization_name") or geo_data.get("organization") or "Unknown"}
- ASN: {geo_data.get("asn") or "Unknown"}

As Agent-X, a Threat Intelligence analyst, create a concise report based on the actual technical data above.
Your job is to produce PURE JSON output (no markdown), using this schema:
{{
  "narrative": "Brief explanation of security threat or infrastructure status of the target",
  "threatLevel": "LOW / MEDIUM / HIGH / CRITICAL",
  "findings": ["DNS data found: ...", "Server location: ...", "Organization: ..."]
}}"""

        result = loop.run_until_complete(
            ai.generate_content(
                model=get_model(),
                contents=[{"role": "user", "parts": [{"text": prompt}]}],
                system_instruction=SYSTEM_PROMPT,
                config={"temperature": 0.7, "responseMimeType": "application/json"},
            )
        )

        try:
            report = json.loads(result.text or "{}")
        except json.JSONDecodeError:
            return jsonify({"error": "AI response parsing failed."}), 500

        return jsonify({
            "success": True,
            "report": {
                "target": {"type": target_type, "value": target_value},
                **report,
            },
        })
    except Exception as e:
        print(f"OSINT Scan error: {e}")
        return jsonify({"error": "Analysis failed on the server. Please try again later."}), 500
    finally:
        loop.close()


def _start_rate_limit_cleanup():
    import threading
    def _cleanup_loop():
        while True:
            time.sleep(RATE_LIMIT_CLEANUP_INTERVAL)
            _rate_limit_cleanup()
    thread = threading.Thread(target=_cleanup_loop, daemon=True)
    thread.start()


def start_server(host="127.0.0.1", port=3000):
    _start_rate_limit_cleanup()
    print(f"Server running on http://{host}:{port}")
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    start_server()
