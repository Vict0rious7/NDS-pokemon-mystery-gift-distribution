"""
NDS Mystery Gift Event Server
Implements the Nintendo WFC NAS auth and DLS1 download protocol
for distributing Gen 4/5 Pokémon Mystery Gift events to a real DS.

Protocol flow:
  1. DS → conntest.nintendowifi.net GET /        (connectivity check)
  2. DS → nas.nintendowifi.net POST /ac          (NAS login)
  3. DS → nas.nintendowifi.net POST /ac          (SVCLOC for svc=9000)
  4. DS → dls1.nintendowifi.net POST /download   (action=count)
  5. DS → dls1.nintendowifi.net POST /download   (action=list)
  6. DS → dls1.nintendowifi.net POST /download   (action=contents)

Event files:
  Gen 4: .myg files (936 bytes) — the original Nintendo WiFi distribution format
  Gen 5: .pgf files — wonder card format for BW/B2W2

  Note: .pgt/.pcd pairs (common in preservation archives) are the save-file
  injection format, NOT the WiFi distribution format. Use MysteryGiftConvert
  to convert .pcd → .myg if needed.

  Place event files in:
    server/events/gen4/   ← .myg files for Gen 4 games
    server/events/gen5/   ← .pgf files for Gen 5 games
"""

import os
import glob
import random
import logging
import base64
from datetime import datetime, timezone
from flask import Flask, request, Response, make_response
from urllib.parse import unquote_plus
from wsgiref.simple_server import WSGIServer, WSGIRequestHandler

app = Flask(__name__)
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

EVENTS_DIR = os.environ.get("EVENTS_DIR", "/app/events")

# ---------------------------------------------------------------------------
# Game code → (generation, game name, region) mapping
# The DS sends its 4-character game code in every request.
# ---------------------------------------------------------------------------
GAME_CODES = {
    # Gen 4 — Diamond/Pearl
    "ADAE": ("gen4", "Diamond",    "EN"),
    "ADAP": ("gen4", "Diamond",    "EU"),
    "ADAF": ("gen4", "Diamond",    "FR"),
    "ADAI": ("gen4", "Diamond",    "IT"),
    "ADAS": ("gen4", "Diamond",    "ES"),
    "ADAD": ("gen4", "Diamond",    "DE"),
    "ADAJ": ("gen4", "Diamond",    "JP"),
    "ADAK": ("gen4", "Diamond",    "KO"),
    "APAE": ("gen4", "Pearl",      "EN"),
    "APAP": ("gen4", "Pearl",      "EU"),
    "APAJ": ("gen4", "Pearl",      "JP"),
    # Gen 4 — Platinum
    "CPUE": ("gen4", "Platinum",   "EN"),
    "CPUP": ("gen4", "Platinum",   "EU"),
    "CPUF": ("gen4", "Platinum",   "FR"),
    "CPUI": ("gen4", "Platinum",   "IT"),
    "CPUS": ("gen4", "Platinum",   "ES"),
    "CPUD": ("gen4", "Platinum",   "DE"),
    "CPUJ": ("gen4", "Platinum",   "JP"),
    "CPUK": ("gen4", "Platinum",   "KO"),
    # Gen 4 — HeartGold/SoulSilver
    "IPKE": ("gen4", "HeartGold",  "EN"),
    "IPKP": ("gen4", "HeartGold",  "EU"),
    "IPKJ": ("gen4", "HeartGold",  "JP"),
    "IPGE": ("gen4", "SoulSilver", "EN"),
    "IPGP": ("gen4", "SoulSilver", "EU"),
    "IPGF": ("gen4", "SoulSilver", "FR"),
    "IPGI": ("gen4", "SoulSilver", "IT"),
    "IPGS": ("gen4", "SoulSilver", "ES"),
    "IPGD": ("gen4", "SoulSilver", "DE"),
    "IPGJ": ("gen4", "SoulSilver", "JP"),
    "IPGK": ("gen4", "SoulSilver", "KO"),
    # Gen 5 — Black/White
    "IRAE": ("gen5", "Black",      "EN"),
    "IRAP": ("gen5", "Black",      "EU"),
    "IRAJ": ("gen5", "Black",      "JP"),
    "IRAO": ("gen5", "Black",      "AU"),
    "IRBE": ("gen5", "White",      "EN"),
    "IRBP": ("gen5", "White",      "EU"),
    "IRBJ": ("gen5", "White",      "JP"),
    "IRBO": ("gen5", "White",      "AU"),
    # Gen 5 — Black 2/White 2
    "IB2E": ("gen5", "Black2",     "EN"),
    "IB2P": ("gen5", "Black2",     "EU"),
    "IB2J": ("gen5", "Black2",     "JP"),
    "IW2E": ("gen5", "White2",     "EN"),
    "IW2P": ("gen5", "White2",     "EU"),
    "IW2J": ("gen5", "White2",     "JP"),
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_event_files(generation):
    """Return all available event files for the given generation."""
    if generation == "gen4":
        # .myg is the WiFi distribution format (preferred)
        # .pgt/.pcd are save-file formats, kept as fallback
        extensions = ["*.myg", "*.pgt", "*.pcd"]
    else:
        extensions = ["*.pgf"]

    files = []
    base = os.path.join(EVENTS_DIR, generation)
    for ext in extensions:
        files.extend(glob.glob(os.path.join(base, ext)))
    return files


def nintendo_b64encode(s):
    """Nintendo's custom base64 variant: + → .  / → -  = → *"""
    if isinstance(s, str):
        s = s.encode()
    return base64.b64encode(s).decode().replace('+', '.').replace('/', '-').replace('=', '*')


def parse_nintendo_body(raw_body):
    """Parse a Nintendo base64-encoded POST body into a plain dict."""
    params = {}
    for part in raw_body.decode('latin-1').split('&'):
        if '=' not in part:
            continue
        k, v = part.split('=', 1)
        k = unquote_plus(k)
        v = unquote_plus(v)
        # Reverse Nintendo base64 substitution then decode
        nb64 = v.replace('*', '=').replace('-', '/').replace('.', '+')
        try:
            params[k] = base64.b64decode(nb64 + '==').decode('latin-1')
        except Exception:
            params[k] = v
    return params


# ---------------------------------------------------------------------------
# NAS authentication  (/ac)
# The DS hits this twice: once for login, once for SVCLOC (service locator).
# We return fake-but-valid responses that tell the DS where DLS1 is.
# ---------------------------------------------------------------------------
@app.route("/ac", methods=["POST"])
def nas_auth():
    raw_body = request.get_data(cache=False)
    log.info(f"NAS /ac from {request.remote_addr}")
    params_in = parse_nintendo_body(raw_body)
    log.debug(f"Parsed: {params_in}")

    now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    token = "A" * 32
    action = params_in.get("action", "login")

    if action == "SVCLOC":
        log.info(f"SVCLOC for svc={params_in.get('svc', '')}")
        params_out = [
            ("retry",      "0"),
            ("returncd",   "007"),
            ("statusdata", "Y"),
            ("svchost",    "dls1.nintendowifi.net"),
            ("token",      token),
            ("datetime",   now),
        ]
    else:
        log.info("NAS login")
        params_out = [
            ("locator",  "dls1.nintendowifi.net"),
            ("retry",    "0"),
            ("returncd", "001"),
            ("token",    token),
            ("datetime", now),
        ]

    body = "&".join(f"{k}={nintendo_b64encode(v)}" for k, v in params_out)
    log.debug(f"Response: {body}")

    resp = make_response(body)
    resp.headers["Content-Type"] = "text/plain;charset=ISO-8859-1"
    resp.headers["Content-Length"] = str(len(body))
    return resp


# ---------------------------------------------------------------------------
# NAS profile check  (/pr)
# Some games hit this after /ac. We return a minimal success response.
# ---------------------------------------------------------------------------
@app.route("/pr", methods=["POST"])
def nas_profile():
    log.info(f"NAS /pr from {request.remote_addr}")
    now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    body = "&".join(f"{k}={nintendo_b64encode(v)}" for k, v in [
        ("returncd", "001"),
        ("datetime", now),
    ])
    return Response(body, mimetype="text/plain;charset=ISO-8859-1", status=200)


# ---------------------------------------------------------------------------
# DLS1 download endpoint  (/download)
# The DS posts here with three sequential actions:
#   count    → returns number of available gifts ("1")
#   list     → returns a tab-separated line: "filename\t\t\t\t\tsize\r\n"
#   contents → DS echoes back the filename; we return the binary .myg/.pgf
# ---------------------------------------------------------------------------
@app.route("/download", methods=["GET", "POST"])
def dls1_download():
    raw_body = request.get_data(cache=False)
    log.info(f"DLS1 /download from {request.remote_addr}")
    log.debug(f"Raw body: {raw_body}")

    params_in = parse_nintendo_body(raw_body)
    log.debug(f"Parsed: {params_in}")

    action    = params_in.get("action",  "").strip()
    game_code = params_in.get("gamecd",  "UNKNOWN").strip().upper()[:4]
    log.info(f"Action: {action}, game code: {game_code}")

    game_info  = GAME_CODES.get(game_code)
    generation = game_info[0] if game_info else "gen4"
    ext        = ".myg" if generation == "gen4" else ".pgf"
    event_files = [f for f in get_event_files(generation) if f.endswith(ext)]

    if action == "count":
        count = 1 if event_files else 0
        log.info(f"Count: {count}")
        return Response(str(count), mimetype="text/plain", status=200)

    elif action == "list":
        if not event_files:
            return Response("", status=200)
        chosen   = random.choice(event_files)
        filename = os.path.basename(chosen)
        size     = os.path.getsize(chosen)
        line     = f"{filename}\t\t\t\t\t{size}\r\n"
        log.info(f"List: {line!r}")
        return Response(line, status=200, headers={"Content-Type": "text/plain"})

    elif action == "contents":
        filename = params_in.get("contents", "").strip()
        log.info(f"Contents: {filename!r}")
        file_path = os.path.join(EVENTS_DIR, generation, filename)
        if not os.path.isfile(file_path):
            log.warning(f"File not found: {file_path}")
            return Response(b"", status=404)
        with open(file_path, "rb") as f:
            data = f.read()
        log.info(f"Serving {filename} ({len(data)} bytes)")
        resp = make_response(data)
        resp.headers["Content-Type"]   = "application/x-dsdl"
        resp.headers["Content-Length"] = str(len(data))
        return resp

    else:
        log.warning(f"Unknown action: {action!r}")
        return Response(b"", status=200)


# ---------------------------------------------------------------------------
# Health check  (/health)
# ---------------------------------------------------------------------------
@app.route("/health", methods=["GET"])
def health():
    return {
        "status": "ok",
        "events": {
            "gen4": [os.path.basename(f) for f in get_event_files("gen4")],
            "gen5": [os.path.basename(f) for f in get_event_files("gen5")],
        }
    }


# ---------------------------------------------------------------------------
# Catch-all — logs anything unexpected for debugging
# ---------------------------------------------------------------------------
@app.after_request
def strip_headers(response):
    # Remove headers that wsgiref adds but the DS doesn't need
    response.headers.remove('Server')
    response.headers.remove('Date')
    return response

@app.route("/", defaults={"path": ""}, methods=["GET", "POST"])
@app.route("/<path:path>", methods=["GET", "POST"])
def catch_all(path):
    raw_body = request.get_data(cache=False)
    log.info(f"Catch-all: {request.method} /{path}")
    log.debug(f"Headers: {dict(request.headers)}")
    log.debug(f"Body: {raw_body[:200]}")
    return Response("", status=200)


# ---------------------------------------------------------------------------
# Entry point — wsgiref with HTTP/1.0 forced
# The DS's DLS1 parser only speaks HTTP/1.0, so we must not send HTTP/1.1.
# wsgiref is single-threaded which is fine for a local LAN server.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    class HTTP10Handler(WSGIRequestHandler):
        protocol_version = "HTTP/1.0"
        def log_message(self, format, *args):
            pass  # Suppress wsgiref's own logging; we use Flask's

    server = WSGIServer(("0.0.0.0", 8080), HTTP10Handler)
    server.set_app(app)
    log.info("Serving on 0.0.0.0:8080 with HTTP/1.0")
    server.serve_forever()