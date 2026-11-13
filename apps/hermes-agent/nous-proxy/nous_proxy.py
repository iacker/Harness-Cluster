"""Proxy LLM Nous Portal pour le Hindsight d'Enyo.

Hindsight a besoin d'une cle API fixe ; Nous Portal ne donne a Enyo qu'une
cle d'agent OAuth qui expire toutes les heures. Ce sidecar reutilise la
session Nous d'Enyo (/opt/data/auth.json) via le resolveur officiel de Hermes,
qui rafraichit sous le verrou du store : aucune course avec la gateway.

Garde-fous : jeton partage obligatoire (NOUS_PROXY_TOKEN), seul
POST /v1/chat/completions est relaye, modele force (NOUS_PROXY_MODEL),
chaque appel est journalise avec son cout dans NOUS_PROXY_LEDGER.
"""
import hmac
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from hermes_cli.auth_nous import resolve_nous_runtime_credentials

TOKEN = os.environ["NOUS_PROXY_TOKEN"]
MODEL = os.environ.get("NOUS_PROXY_MODEL", "deepseek/deepseek-v4.1-flash")
LEDGER = os.environ.get("NOUS_PROXY_LEDGER", "/opt/data/logs/nous-proxy-ledger.jsonl")
PORT = int(os.environ.get("NOUS_PROXY_PORT", "8651"))
MAX_BODY = 4 * 1024 * 1024
_lock = threading.Lock()


def _creds(force=False):
    with _lock:
        return resolve_nous_runtime_credentials(force_refresh=force)


def _ledger(entry):
    try:
        os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
        with open(LEDGER, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/healthz":
            return self._send(200, b'{"ok":true}')
        self._send(404, b'{"error":"not found"}')

    def do_POST(self):
        auth = self.headers.get("Authorization", "")
        if not hmac.compare_digest(auth.encode(), ("Bearer " + TOKEN).encode()):
            return self._send(401, b'{"error":"unauthorized"}')
        if self.path.rstrip("/") not in ("/v1/chat/completions", "/chat/completions"):
            return self._send(404, b'{"error":"only /v1/chat/completions"}')
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > MAX_BODY:
            return self._send(413, b'{"error":"bad body size"}')
        try:
            body = json.loads(self.rfile.read(n))
        except ValueError:
            return self._send(400, b'{"error":"bad json"}')
        asked = body.get("model")
        body["model"] = MODEL
        data = json.dumps(body).encode()
        t0 = time.time()
        out, code, ctype = b'{"error":"no attempt"}', 502, "application/json"
        for attempt in (0, 1):
            try:
                c = _creds(force=attempt == 1)
            except Exception as e:  # session Nous morte : a reconnecter cote Enyo
                _ledger({"ts": t0, "status": "auth_error", "error": type(e).__name__})
                return self._send(503, json.dumps({"error": "nous auth: " + type(e).__name__}).encode())
            req = urllib.request.Request(
                c["base_url"].rstrip("/") + "/chat/completions", data=data, method="POST",
                headers={"Authorization": "Bearer " + c["api_key"], "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=300) as r:
                    out, code, ctype = r.read(), r.status, r.headers.get("Content-Type", "application/json")
                break
            except urllib.error.HTTPError as e:
                out, code, ctype = e.read(), e.code, e.headers.get("Content-Type", "application/json")
                if code == 401 and attempt == 0:
                    continue
                break
            except Exception as e:
                out, code, ctype = json.dumps({"error": type(e).__name__}).encode(), 502, "application/json"
                break
        usage = {}
        try:
            usage = json.loads(out).get("usage") or {}
        except ValueError:
            pass
        _ledger({"ts": t0, "ms": int((time.time() - t0) * 1000), "status": code, "asked": asked,
                 "model": MODEL, "prompt_tokens": usage.get("prompt_tokens"),
                 "completion_tokens": usage.get("completion_tokens"), "cost_usd": usage.get("cost")})
        self._send(code, out, ctype)


if __name__ == "__main__":
    print(f"nous-proxy :{PORT} model={MODEL}", file=sys.stderr, flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
