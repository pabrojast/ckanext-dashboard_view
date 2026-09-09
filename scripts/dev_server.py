"""Localhost-only browser harness using the real engine and saved configuration."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import random
import sys
import threading
from datetime import date, timedelta, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from flask import Flask, Response, jsonify, redirect, render_template_string, request, send_file, send_from_directory
from ckanext.dashboard_view.engine import prepare_table, query_table, export_csv
from ckanext.dashboard_view.schema import normalize_config, normalize_source

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 256 * 1024 * 1024
WORK = ROOT / "output" / "demo"
WORK.mkdir(parents=True, exist_ok=True)
LOCK = threading.Lock()
SOURCE = WORK / "citizen-science.csv"
SAVED = WORK / "dashboard.json"


def make_data(rows=20000):
    rng = random.Random(947)
    places = [("Chile", "Maipo", -33.6, -70.6), ("France", "Loire", 47.2, -1.55),
              ("Belgium", "Scheldt", 51.2, 4.4), ("Kenya", "Nairobi", -1.29, 36.8),
              ("India", "Yamuna", 28.6, 77.2), ("Brazil", "Amazon", -3.1, -60.0)]
    with SOURCE.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", "country", "site", "nitrate", "temperature", "lat", "lon"])
        for i in range(rows):
            country, site, lat, lon = places[i % len(places)]
            writer.writerow([(date(2024, 1, 1) + timedelta(days=i % 730)).isoformat(), country,
                             f"{site} {i % 30 + 1}", round(0.2 + rng.random() * 6 + (i % 12) / 5, 2),
                             round(10 + rng.random() * 18, 1), round(lat + (i % 30) * .008, 5),
                             round(lon + (i % 30) * .008, 5)])


def initial_config():
    def widget(id, kind, title, x, y, w, h, **kw):
        return dict(id=id, type=kind, title=title, x=x, y=y, w=w, h=h, color="#0069b4", **kw)
    return {"schema_version": 1, "source": {"kind": "file"}, "widgets": [
        widget("records", "kpi", "Observaciones", 0, 0, 3, 2, aggregate="count"),
        widget("median", "kpi", "Mediana de nitrato", 3, 0, 3, 2, y_field="nitrate", aggregate="median", unit="mg/L"),
        widget("map", "map", "Lugares de muestreo", 0, 2, 7, 6, lat_field="lat", lon_field="lon", y_field="nitrate", aggregate="median"),
        widget("trend", "line", "Evolución del nitrato", 7, 2, 5, 4, x_field="date", y_field="nitrate", aggregate="median", time_grain="month"),
        widget("countries", "bar", "Observaciones por país", 7, 6, 5, 4, x_field="country", aggregate="count", limit=20),
        widget("distribution", "histogram", "Distribución del nitrato", 0, 8, 7, 4, y_field="nitrate", aggregate="count", bins=15),
        widget("table", "table", "Datos de origen", 0, 12, 12, 5, columns=["date", "country", "site", "nitrate", "temperature"]),
    ], "filters": [{"field": "country", "type": "category", "label": "País"},
                     {"field": "date", "type": "date", "label": "Fecha"}], "style": {"accent": "#0069b4"}}


def saved():
    return json.loads(SAVED.read_text()) if SAVED.exists() else {"title": "Agua y ciencia ciudadana", "config": initial_config()}


def selectors(payload):
    config = normalize_config(payload.get("config") or saved()["config"], allow_empty=True)
    source = normalize_source(payload.get("source") or config["source"])
    signature = hashlib.sha256((json.dumps(source, sort_keys=True) + str(SOURCE.stat().st_mtime_ns)).encode()).hexdigest()[:16]
    db = WORK / (signature + ".duckdb")
    profile_path = WORK / (signature + ".json")
    with LOCK:
        if not db.exists() or not profile_path.exists():
            profile = prepare_table(str(SOURCE), str(db), source=source, format_hint="csv")
            profile_path.write_text(json.dumps(profile))
        profile = json.loads(profile_path.read_text())
    profile.update(status="ready", generation=signature, updated_at=datetime.fromtimestamp(SOURCE.stat().st_mtime, timezone.utc).isoformat())
    return config, db, profile


PAGE = """<!doctype html><html lang="{{ lang }}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{{ title }} · Dashboard Builder</title><link rel="stylesheet" href="/dashboard-static/dashboard.css"><style>body{margin:0;font-family:Inter,system-ui,sans-serif;background:#f4f7fb;color:#18334a}.demo-header{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:16px 24px;background:#fff;border-bottom:1px solid #dce5ef}.demo-header a{color:#0069b4;text-decoration:none}.demo-header small{color:#52677b}.demo-shell{max-width:1600px;margin:auto;padding:20px}.demo-title{width:100%;box-sizing:border-box;padding:12px 16px;border:1px solid #d5dfe9;border-radius:10px;font-size:20px;margin-bottom:16px}.demo-submit{padding:12px 22px;background:#0069b4;color:white;border:0;border-radius:8px;margin:16px 0;cursor:pointer}.demo-note{font-size:13px;color:#52677b;margin:0 0 16px}.demo-error{padding:12px;color:#9b1c20;background:#fff0f0}</style></head><body>{% if not embed %}<header class="demo-header"><a href="/">Dashboard Builder</a><small>Entorno local · datos sintéticos</small><a href="{{ '/dashboard/demo' if mode=='editor' else '/edit' }}">{{ 'Ver dashboard' if mode=='editor' else 'Editar dashboard' }}</a></header>{% endif %}<main class="{{ '' if embed else 'demo-shell' }}">{% if error %}<p class="demo-error">{{ error }}</p>{% endif %}{% if mode=='editor' %}<form method="post" action="/save"><label for="demo-title">Título</label><input id="demo-title" class="demo-title" name="title" value="{{ title }}"><input type="hidden" name="dashboard_config" value="{{ config_text }}"><p class="demo-note">Configura el dashboard y guarda para probar persistencia y el iframe.</p>{% endif %}<div data-dashboard><script type="application/json" data-dashboard-bootstrap>{{ bootstrap|tojson }}</script></div>{% if mode=='editor' %}<button class="demo-submit" type="submit">Guardar dashboard</button></form>{% endif %}</main><script type="module" src="/dashboard-static/dashboard.js"></script></body></html>"""


def render(mode, embed=False, error=None):
    item = saved()
    lang = request.args.get("lang", "es")
    boot = dict(mode=mode, resource_id="demo", view_id="demo", title=item["title"], config=item["config"],
                lang=lang, api_base="/dashboard-api/resource/demo", view_url="/dashboard/demo",
                embed_url="/dashboard/demo/embed", resource_url="/sample.csv",
                basemap_url="https://tiles.openfreemap.org/styles/positron", can_edit=True)
    return render_template_string(PAGE, mode=mode, embed=embed, title=item["title"], lang=lang,
                                  bootstrap=boot, config_text=json.dumps(item["config"]), error=error)


@app.get("/")
@app.get("/edit")
def editor():
    return render("editor")


@app.get("/dashboard/demo")
def viewer():
    return render("view")


@app.get("/dashboard/demo/embed")
def embed():
    return render("view", embed=True)


@app.post("/save")
def save():
    try:
        config = normalize_config(request.form["dashboard_config"])
        title = request.form.get("title", "Dashboard").strip()[:200]
        SAVED.write_text(json.dumps(dict(title=title, config=config), ensure_ascii=False, indent=2))
        return redirect("/dashboard/demo")
    except (ValueError, KeyError) as exc:
        return render("editor", error=str(exc)), 400


@app.post("/dashboard-api/resource/demo/<operation>")
def api(operation):
    try:
        payload = request.get_json(silent=True) or {}
        config, db, profile = selectors(payload)
        if operation in ("profile", "refresh"):
            return jsonify(profile)
        if operation == "query":
            result = query_table(str(db), config, filters=payload.get("filters"), bounds=payload.get("bounds"), pages=payload.get("pages"))
            return jsonify(dict(result, status="ready", generation=profile["generation"], updated_at=profile["updated_at"]))
        if operation == "export":
            return Response(export_csv(str(db), config, filters=payload.get("filters"), bounds=payload.get("bounds")), mimetype="text/csv", headers={"Content-Disposition": 'attachment; filename="dashboard.csv"'})
        return jsonify(status="error", message="Not found"), 404
    except (ValueError, KeyError) as exc:
        return jsonify(status="error", message=str(exc)), 400


@app.get("/dashboard-static/<path:name>")
def assets(name):
    return send_from_directory(ROOT / "ckanext/dashboard_view/public/dashboard", name)


@app.get("/sample.csv")
def sample():
    return send_file(SOURCE, mimetype="text/csv", as_attachment=True)


@app.get("/embed-example")
def example():
    return '<!doctype html><html><meta name="viewport" content="width=device-width,initial-scale=1"><title>Embed QA</title><body style="margin:0;font-family:system-ui"><h1 style="padding:12px">Citizen science portal · iframe example</h1><iframe src="http://127.0.0.1:' + str(request.host.split(':')[-1]) + '/dashboard/demo/embed" title="Water observations dashboard" style="width:100%;height:1100px;border:0" loading="lazy"></iframe></body></html>'


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5188)
    parser.add_argument("--rows", type=int, default=20000)
    args = parser.parse_args()
    if not SOURCE.exists():
        make_data(args.rows)
    app.run(host="127.0.0.1", port=args.port, debug=False, threaded=True)
