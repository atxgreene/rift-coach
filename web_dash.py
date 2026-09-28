"""Local-only second-screen dashboard. Binds to 127.0.0.1, never the LAN."""

import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import lol_coach

ROOT = lol_coach.ROOT

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Macro Goblin</title>
<style>
  body { margin: 0; background: #05080d; color: #f0e6d2; font: 15px Segoe UI, sans-serif; }
  main { max-width: 420px; margin: 24px auto; background: #0d1828; border: 1px solid #233957; padding: 16px 18px; }
  .brand { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
  .brand img { width: 34px; height: 34px; border-radius: 50%; box-shadow: 0 0 18px rgba(63,183,216,.35); }
  h1 { font-size: 12px; letter-spacing: 0.12em; color: #f0d58c; margin: 0; }
  .clock { font: 22px Consolas, monospace; margin: 4px 0 12px; }
  table { width: 100%; border-collapse: collapse; }
  td { padding: 3px 0; }
  td:last-child { text-align: right; font-family: Consolas, monospace; }
  .muted { color: #8b909a; }
  .up { color: #7dcea0; }
  .soon { color: #f0b45a; }
  .down { color: #e07a7a; }
  .bar { height: 10px; background: #222733; margin: 6px 0 12px; position: relative; }
  .fill { position: absolute; top: 0; height: 10px; }
  ul { margin: 8px 0 0; padding-left: 18px; color: #f0b45a; }
  p { margin: 8px 0; }
</style>
</head>
<body>
<main>
  <div class="brand"><img src="/assets/app-icon-128.png" alt="Macro Goblin logo"><h1>MACRO GOBLIN</h1></div>
  <div class="clock" id="clock">READY</div>
  <p class="muted" id="who">Queue up</p>
  <table id="timers"></table>
  <p class="muted" id="gold">Item gold</p>
  <div class="bar"><div class="fill" id="fill"></div></div>
  <p id="cs">CS</p>
  <div id="lines"></div>
  <ul id="spikes"></ul>
</main>
<script>
function fmt(s) {
  s = Math.max(0, Math.floor(s));
  return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
}
function esc(s) {
  return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
async function tick() {
  const res = await fetch("/state", {cache: "no-store"});
  const state = await res.json();
  document.getElementById("clock").textContent = state.clock || "READY";
  const who = document.getElementById("who");
  if (state.in_game) {
    who.textContent = [state.champion, state.position, state.kda].filter(Boolean).join("  ");
  } else {
    who.textContent = state.hint || "Queue up. Borderless.";
  }
  const names = {dragon: state.elder ? "Elder" : "Dragon", grubs: "Grubs", herald: "Herald", baron: "Baron"};
  const rows = Object.keys(names).map(key => {
    const at = (state.spawns || {})[key];
    if (at == null || state.t == null) return "<tr><td class='muted'>" + names[key] + "</td><td class='muted'>--</td></tr>";
    const remain = at - state.t;
    const cls = remain <= 0 ? "up" : (remain <= 60 ? "soon" : "");
    const text = remain <= 0 ? "UP" : fmt(remain);
    return "<tr><td class='muted'>" + names[key] + "</td><td class='" + cls + "'>" + text + "</td></tr>";
  }).join("");
  document.getElementById("timers").innerHTML = rows;
  const diff = state.gold_diff || 0;
  const prev = state.prev_gold_diff || diff;
  const arrow = diff > prev + 200 ? "^" : (diff < prev - 200 ? "v" : "-");
  document.getElementById("gold").textContent = state.in_game
    ? ("Item gold " + (diff >= 0 ? "+" : "-") + Math.abs(diff / 1000).toFixed(1) + "k " + arrow)
    : "";
  const fill = document.getElementById("fill");
  const span = Math.max(-1, Math.min(1, diff / 5000)) * 50;
  fill.style.background = diff >= 0 ? "#7dcea0" : "#e07a7a";
  fill.style.left = (span >= 0 ? 50 : 50 + span) + "%";
  fill.style.width = Math.abs(span) + "%";
  const cs = document.getElementById("cs");
  if (state.position === "UTILITY") cs.textContent = "";
  else if (state.cs_rate == null) cs.textContent = "CS --";
  else {
    const rate = state.cs_rate, target = state.cs_target || 8;
    cs.textContent = "CS " + rate.toFixed(1) + " / " + target;
    cs.className = rate >= target - 0.3 ? "up" : (rate >= target - 1.5 ? "soon" : "down");
  }
  document.getElementById("lines").innerHTML = (state.callouts || []).map(row => "<p>" + esc(row[1]) + "</p>").join("");
  document.getElementById("spikes").innerHTML = (state.spikes || []).slice(-3).map(s => "<li>" + esc(s) + "</li>").join("");
}
tick();
setInterval(tick, 1000);
</script>
</body>
</html>
"""


def make_handler(bus):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path.startswith("/assets/"):
                name = os.path.basename(parsed.path)
                path = os.path.join(ROOT, "assets", name)
                asset_root = os.path.abspath(os.path.join(ROOT, "assets"))
                path_abs = os.path.abspath(path)
                if not path_abs.startswith(asset_root + os.sep) or not os.path.exists(path_abs):
                    self.send_error(404)
                    return
                content_type = mimetypes.guess_type(path_abs)[0] or "application/octet-stream"
                with open(path_abs, "rb") as handle:
                    body = handle.read()
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "public, max-age=3600")
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path.startswith("/state"):
                body = json.dumps(bus.snapshot()).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path in ("/", "/index.html"):
                body = PAGE.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_error(404)

        def log_message(self, fmt, *args):
            return

    return Handler


def serve(bus, stop, host=None, port=None):
    host = host or lol_coach.CONFIG["web_host"]
    port = lol_coach.CONFIG["web_port"] if port is None else port
    if host not in ("127.0.0.1", "localhost"):
        raise SystemExit("Refusing to bind the dashboard to %s. Localhost only." % host)
    try:
        httpd = ThreadingHTTPServer((host, port), make_handler(bus))
    except OSError as exc:
        print("Web dashboard did not start (%s)." % exc, flush=True)
        return
    httpd.timeout = 0.5
    print("Dashboard at http://%s:%s" % (host, port), flush=True)
    while not stop.is_set():
        httpd.handle_request()
    httpd.server_close()
