"""Prometheus exporter for the Hermes audit_to_db plugin (stdlib only).

Reads <plugin>/data/audit.db read-only and turns rows into counters.
Counters start at 0 from the DB's current last row (no re-count of history
after a restart) and only grow with new row ids, so pruning old rows never
makes a counter go down. A restart is a normal counter reset for Prometheus.
"""
import calendar
import os
import sqlite3
import threading
import time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DB = os.environ.get("AUDIT_DB", "/audit/audit.db")
PORT = int(os.environ.get("PORT", "9465"))
AGENT = os.environ.get("AGENT_NAME", "enyo")
HOLD = float(os.environ.get("NEW_SERIES_HOLD_S", "90"))  # > 2x scrape_interval (30s)
first_seen = {}

lock = threading.Lock()
last = {"api": 0, "tool": 0}
llm_req = defaultdict(int)       # (provider, model, platform, finish)
llm_tok = defaultdict(int)       # (provider, model, platform, type)
llm_dur = defaultdict(float)     # (provider, model, platform)
tool_n = defaultdict(int)        # (tool, result)
tool_dur = defaultdict(float)    # (tool,)
sessions = defaultdict(set)      # platform -> {session_id}
state = {"up": 0, "last_ts": 0.0}

TOKENS = ("input_tokens", "output_tokens", "cache_read_tokens",
          "cache_write_tokens", "reasoning_tokens")


def ts(s):
    try:
        return calendar.timegm(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S"))  # stored as UTC
    except Exception:
        return 0.0


def refresh():
    if not os.path.exists(DB):
        state["up"] = 0
        state["init"] = True  # fresh install: every future row is new
        return
    try:
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5)
        if not state.get("init"):
            # Start at 0 from the current end of the DB: re-counting history after
            # a pod restart would show up as a fake consumption spike in increase().
            last["api"] = c.execute("select coalesce(max(id),0) from api_calls").fetchone()[0]
            last["tool"] = c.execute("select coalesce(max(id),0) from tool_calls").fetchone()[0]
            state["init"] = True
        api = c.execute(
            "select id,timestamp,session_id,coalesce(provider,'?'),coalesce(model,'?'),"
            "coalesce(platform,'?'),coalesce(finish_reason,'?'),api_duration,"
            + ",".join(TOKENS) + " from api_calls where id>? order by id",
            (last["api"],)).fetchall()
        tools = c.execute(
            "select id,timestamp,tool_name,result,duration_ms from tool_calls "
            "where id>? order by id", (last["tool"],)).fetchall()
        c.close()
    except sqlite3.Error:
        state["up"] = 0
        return
    for r in api:
        rid, t, sid, prov, model, plat, fin, dur = r[:8]
        llm_req[(prov, model, plat, fin)] += 1
        llm_dur[(prov, model, plat)] += dur or 0.0
        for name, v in zip(TOKENS, r[8:]):
            llm_tok[(prov, model, plat, name[:-7])] += v or 0
        sessions[plat].add(sid)
        last["api"] = rid
        state["last_ts"] = max(state["last_ts"], ts(t))
    for rid, t, tool, res, ms in tools:
        tool_n[(tool, "error" if res else "ok")] += 1
        tool_dur[(tool,)] += (ms or 0) / 1000.0
        last["tool"] = rid
        state["last_ts"] = max(state["last_ts"], ts(t))
    state["up"] = 1


def esc(v):
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def fmt(name, kind, help_, data, keys):
    out = [f"# HELP {name} {help_}", f"# TYPE {name} {kind}"]
    now = time.time()
    for k, v in sorted(data.items()):
        # A brand new series is published at 0 for HOLD seconds first, so that
        # Prometheus sees 0 -> N and increase() counts the very first events.
        born = first_seen.setdefault((name, k), now)
        if kind == "counter" and now - born < HOLD:
            v = 0
        lbl = ",".join(f'{n}="{esc(x)}"' for n, x in zip(keys, k))
        lbl = f'agent="{AGENT}"' + ("," + lbl if lbl else "")
        out.append(f"{name}{{{lbl}}} {v}")
    return out


def render():
    with lock:
        refresh()
        o = fmt("hermes_audit_up", "gauge", "1 if audit.db is readable",
                {(): state["up"]}, ())
        o += fmt("hermes_audit_last_event_timestamp_seconds", "gauge",
                 "Unix time of the newest audited event", {(): state["last_ts"]}, ())
        o += fmt("hermes_llm_requests_total", "counter", "LLM API requests",
                 llm_req, ("provider", "model", "platform", "finish_reason"))
        o += fmt("hermes_llm_tokens_total", "counter", "LLM tokens by type",
                 llm_tok, ("provider", "model", "platform", "type"))
        o += fmt("hermes_llm_duration_seconds_total", "counter",
                 "Cumulated LLM API latency", llm_dur, ("provider", "model", "platform"))
        o += fmt("hermes_tool_calls_total", "counter", "Tool calls by result",
                 tool_n, ("tool", "result"))
        o += fmt("hermes_tool_duration_seconds_total", "counter",
                 "Cumulated tool latency", tool_dur, ("tool",))
        o += fmt("hermes_sessions_total", "counter", "Distinct sessions seen",
                 {(p,): len(s) for p, s in sessions.items()}, ("platform",))
    return ("\n".join(o) + "\n").encode()


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/metrics", "/"):
            self.send_response(404)
            self.end_headers()
            return
        body = render()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
