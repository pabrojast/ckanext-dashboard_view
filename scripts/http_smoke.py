"""Exercise native CKAN authorship, asynchronous queries and access revocation.

Only localhost is accepted by default. --dev explicitly targets data.dev-wins.com.
Credentials are read from an environment variable or token file and never printed.
Created fixture IDs and the final dashboard URL are the only persisted metadata.
"""
from __future__ import annotations

import argparse
import csv
import copy
import io
import json
import os
from pathlib import Path
import sys
import time
from html.parser import HTMLParser
from urllib.parse import urlsplit

import requests

ROOT = Path(__file__).resolve().parents[1]
CSV = b"date,country,value,lat,lon\n2025-01-01,CL,1,-33,-70\n2025-01-02,CL,2,-33,-70\n2025-02-01,FR,3,48,2\n2025-02-02,FR,4,48,2\n2025-03-01,BE,5,50,4\n2025-03-02,BE,6,50,4\n"
CONFIG = {"schema_version": 1, "source": {"kind": "file"}, "widgets": [
    {"id": "count", "type": "kpi", "title": "Observations", "x": 0, "y": 0, "w": 3, "h": 2, "aggregate": "count"},
    {"id": "median", "type": "kpi", "title": "Median", "x": 3, "y": 0, "w": 3, "h": 2, "aggregate": "median", "y_field": "value"},
    {"id": "map", "type": "map", "title": "Sampling locations", "x": 0, "y": 2, "w": 7, "h": 6, "lat_field": "lat", "lon_field": "lon", "aggregate": "avg", "y_field": "value"},
    {"id": "trend", "type": "line", "title": "Monthly trend", "x": 7, "y": 2, "w": 5, "h": 4, "x_field": "date", "y_field": "value", "aggregate": "avg", "time_grain": "month"},
    {"id": "countries", "type": "bar", "title": "Observations by country", "x": 7, "y": 6, "w": 5, "h": 4, "x_field": "country", "aggregate": "count"},
    {"id": "table", "type": "table", "title": "Source data", "x": 0, "y": 10, "w": 12, "h": 4, "columns": ["date", "country", "value"]},
], "filters": [{"field": "country", "type": "category", "label": "Country"}], "style": {"accent": "#0069b4"}}


class Inputs(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.inputs = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and attrs.get("name"):
            self.inputs[attrs["name"]] = attrs.get("value", "")


def action(session, base, name, data, files=None):
    response = session.post(base + "/api/3/action/" + name,
                            data=data if files else None, json=None if files else data,
                            files=files, timeout=90)
    try:
        body = response.json()
    except ValueError:
        raise AssertionError(f"{name}: HTTP {response.status_code}, non-JSON response") from None
    if not body.get("success"):
        # CKAN errors contain field names and constraints, never request headers.
        raise AssertionError(f"{name}: HTTP {response.status_code}: {body.get('error')}")
    return body["result"]


def poll(session, url, payload, timeout=180, fresh=False):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = session.post(url, json=payload, timeout=30)
        if response.status_code != 202:
            assert response.status_code == 200, (response.status_code, response.text[:800])
            if fresh and response.headers.get("content-type", "").startswith("application/json") and response.json().get("refreshing"):
                time.sleep(.5)
                continue
            return response
        time.sleep(.5)
    raise AssertionError("Dashboard processing did not complete before the deadline")


def main(args):
    base = args.base.rstrip("/")
    host = urlsplit(base).hostname
    assert host in ("localhost", "127.0.0.1") or (args.dev and host == "data.dev-wins.com"), "Unexpected target"
    session = requests.Session()
    if args.token_file:
        session.headers["Authorization"] = Path(args.token_file).read_text().strip()
    else:
        login = session.get(base + "/user/login", timeout=30)
        fields = Inputs(login.text).inputs
        payload = {key: val for key, val in fields.items() if "csrf" in key.lower()}
        payload.update(login=args.user, password=os.environ.get("DASHBOARD_QA_PASSWORD", "local-dashboard-only"))
        response = session.post(base + "/user/login", data=payload, timeout=30, allow_redirects=False)
        assert response.status_code in (302, 303), ("login", response.status_code)
        response = session.get(base + "/", timeout=30)
        assert response.status_code == 200
        for key, value in Inputs(response.text).inputs.items():
            if "csrf" in key.lower():
                session.headers["X-CSRFToken"] = value
        if "X-CSRFToken" not in session.headers:
            session.headers["X-CSRFToken"] = next((v for k, v in fields.items() if "csrf" in k.lower()), "")
        token = action(session, base, "api_token_create", {"user": args.user, "name": "dashboard-local-qa"})
        session.headers["Authorization"] = token["token"]
    suffix = str(int(time.time())) + "-" + os.urandom(3).hex()
    output = ROOT / "output" / "http"
    output.mkdir(parents=True, exist_ok=True)
    partial_path = output / (host + "-" + suffix + ".json")
    report = {"base": base, "status": "running", "fixture_prefix": "dashboard-qa-" + suffix, "checks": []}
    def checkpoint(**values):
        report.update(values)
        temporary = partial_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, indent=2))
        temporary.replace(partial_path)
    args._checkpoint = checkpoint
    checkpoint(stage="create-fixtures")
    status = action(session, base, "status_show", {})
    has_datashare = "datashare" in status.get("extensions", [])
    org = action(session, base, "organization_create", {"name": "dashboard-qa-" + suffix, "title": "Dashboard Builder QA"})
    checkpoint(organization_id=org["id"])
    package_data = {"name": "dashboard-qa-" + suffix, "title": "Dashboard Builder · integration fixture", "owner_org": org["id"],
                    "notes": "Synthetic data created to validate Dashboard Builder. Not research observations.", "license_id": "cc-by", "private": False}
    if args.package_defaults:
        package_data.update(json.loads(Path(args.package_defaults).read_text()))
    # Defaults describe metadata, never which existing entities a QA run edits.
    package_data.update(name=report["fixture_prefix"], owner_org=org["id"], private=False)
    package_data.pop("id", None)
    if package_data.get("identifier"):
        package_data["identifier"] += "-" + suffix
    package = action(session, base, "package_create", package_data)
    checkpoint(package_id=package["id"], package_name=package["name"])
    resource = action(session, base, "resource_create", {"package_id": package["id"], "name": "Synthetic observations", "format": "CSV"},
                      files={"upload": ("observations.csv", CSV, "text/csv")})
    resource_id = resource["id"]
    checkpoint(resource_id=resource_id, stage="manual-authorship")
    views = action(session, base, "resource_view_list", {"id": resource_id})
    assert not any(v.get("view_type") == "dashboard_view" for v in views)
    action(session, base, "resource_patch", {"id": resource_id, "description": "Six rows for integration testing"})
    views = action(session, base, "resource_view_list", {"id": resource_id})
    assert not any(v.get("view_type") == "dashboard_view" for v in views)
    editor_url = base + f"/dataset/{package['name']}/resource/{resource_id}/new_view?view_type=dashboard_view"
    page = session.get(editor_url, timeout=30)
    assert page.status_code == 200, ("editor", page.status_code, page.text[:500])
    assert "data-dashboard-bootstrap" in page.text
    fields = Inputs(page.text).inputs
    form = {key: value for key, value in fields.items() if "csrf" in key.lower()}
    form.update(title="Water observations · QA", description="Manually created integration dashboard",
                view_type="dashboard_view", dashboard_config=json.dumps(CONFIG), save="Save")
    saved = session.post(editor_url, data=form, timeout=45)
    assert saved.status_code == 200, ("save", saved.status_code)
    views = action(session, base, "resource_view_list", {"id": resource_id})
    created = [v for v in views if v["view_type"] == "dashboard_view"]
    assert len(created) == 1, ("native form did not create one view", saved.url)
    view = created[0]
    checkpoint(view_id=view["id"], dashboard_url=base + f"/dashboard/{view['id']}", embed_url=base + f"/dashboard/{view['id']}/embed", stage="processing-and-permissions")
    stored = action(session, base, "resource_view_show", {"id": view["id"]})
    config = json.loads(stored["dashboard_config"]) if isinstance(stored["dashboard_config"], str) else stored["dashboard_config"]
    assert [(w["id"], w["x"], w["y"]) for w in config["widgets"]] == [(w["id"], w["x"], w["y"]) for w in CONFIG["widgets"]]
    api = base + f"/dashboard-api/resource/{resource_id}"
    profile = poll(session, api + "/profile", {"view_id": view["id"]}).json()
    assert profile["rows"] == 6, profile
    result = poll(session, api + "/query", {"view_id": view["id"]}).json()
    assert result["results"]["count"]["value"] == 6, result
    assert result["results"]["median"]["value"] == 3.5, result
    anonymous = requests.Session()
    anon_result = poll(anonymous, api + "/query", {"view_id": view["id"], "filters": [{"field": "country", "op": "eq", "value": "CL"}]}).json()
    assert anon_result["rows"] == 2, anon_result
    assert anon_result["results"]["median"]["value"] == 1.5
    csv_response = poll(anonymous, api + "/export", {"view_id": view["id"], "filters": [{"field": "country", "op": "eq", "value": "CL"}]})
    exported = list(csv.DictReader(io.StringIO(csv_response.content.decode("utf-8-sig"))))
    assert len(exported) == 2
    embed_url = base + f"/dashboard/{view['id']}/embed"
    framed = anonymous.get(embed_url, timeout=30)
    assert framed.status_code == 200 and "data-dashboard-bootstrap" in framed.text
    assert not framed.headers.get("X-Frame-Options")
    assert "frame-ancestors" in framed.headers.get("Content-Security-Policy", "")
    assert anonymous.post(api + "/refresh", json={"view_id": view["id"]}, timeout=30).status_code == 403
    assert anonymous.post(api + "/query", json={"config": CONFIG}, timeout=30).status_code == 403
    confidential_patch = {"id": package["id"], "private": True}
    if has_datashare:
        confidential_patch["access_level"] = "confidential"
    private_package = action(session, base, "package_patch", confidential_patch)
    assert private_package["private"] is True
    checkpoint(fixture_private=True)
    assert anonymous.get(embed_url, timeout=30).status_code in (403, 404)
    assert anonymous.post(api + "/query", json={"view_id": view["id"]}, timeout=30).status_code in (403, 404)
    assert anonymous.post(api + "/export", json={"view_id": view["id"]}, timeout=30).status_code in (403, 404)
    private = poll(session, api + "/query", {"view_id": view["id"]}).json()
    assert private["rows"] == 6
    if has_datashare:
        action(session, base, "package_patch", {"id": package["id"], "access_level": "viewable", "private": False})
        metadata = anonymous.post(base + "/api/3/action/resource_show", json={"id": resource_id}, timeout=30)
        assert metadata.status_code == 200 and metadata.json()["success"], metadata.status_code
        assert anonymous.post(api + "/query", json={"view_id": view["id"]}, timeout=30).status_code == 403
        assert anonymous.post(api + "/export", json={"view_id": view["id"]}, timeout=30).status_code == 403
        checkpoint(datashare_viewable_download_denied=True)
    public_patch = {"id": package["id"], "private": False}
    if has_datashare:
        public_patch["access_level"] = "public"
    action(session, base, "package_patch", public_patch)
    checkpoint(fixture_private=False, stage="updates-and-datastore")

    # Editing uses the same native CKAN form as creation and must preserve the
    # existing ResourceView identity while retaining the changed arrangement.
    edit_url = base + f"/dataset/{package['name']}/resource/{resource_id}/edit_view/{view['id']}"
    edit_page = session.get(edit_url, timeout=30)
    assert edit_page.status_code == 200
    edited_config = copy.deepcopy(CONFIG)
    edited_config["widgets"][0]["x"] = 6
    edit_fields = Inputs(edit_page.text).inputs
    edit_form = {key: value for key, value in edit_fields.items() if "csrf" in key.lower()}
    edit_form.update(title="Water observations · QA", description="Updated manually in the CKAN editor",
                     view_type="dashboard_view", dashboard_config=json.dumps(edited_config), save="Save")
    updated = session.post(edit_url, data=edit_form, timeout=45)
    assert updated.status_code == 200
    views_after_edit = action(session, base, "resource_view_list", {"id": resource_id})
    assert len([v for v in views_after_edit if v["view_type"] == "dashboard_view"]) == 1
    stored_edit = action(session, base, "resource_view_show", {"id": view["id"]})
    saved_edit = json.loads(stored_edit["dashboard_config"]) if isinstance(stored_edit["dashboard_config"], str) else stored_edit["dashboard_config"]
    assert saved_edit["widgets"][0]["x"] == 6

    # A resource update must create a new data generation without creating any
    # extra view or dropping the editor's saved layout.
    previous_generation = profile["generation"]
    action(session, base, "resource_update", {"id": resource_id, "package_id": package["id"], "name": "Synthetic observations", "format": "CSV"},
           files={"upload": ("observations.csv", CSV + b"2025-04-01,CL,7,-33,-70\n", "text/csv")})
    refreshed = poll(session, api + "/profile", {"view_id": view["id"]}).json()
    assert refreshed["rows"] == 7 and refreshed["generation"] != previous_generation, refreshed
    changed = poll(session, api + "/query", {"view_id": view["id"]}).json()
    assert changed["results"]["count"]["value"] == 7
    assert changed["results"]["median"]["value"] == 4
    map_export = poll(session, api + "/export", {"view_id": view["id"], "bounds": {"west": -75, "south": -40, "east": -65, "north": -20, "zoom": 4}})
    assert len(list(csv.DictReader(io.StringIO(map_export.content.decode("utf-8-sig"))))) == 3

    # PostgreSQL read-only snapshot, including the file->DataStore parser switch.
    ds_resource = action(session, base, "resource_create", {"package_id": package["id"], "name": "DataStore snapshot QA", "format": "CSV", "url": "https://example.invalid/dashboard-qa.csv"})
    checkpoint(datastore_resource_id=ds_resource["id"])
    action(session, base, "datastore_create", {"resource_id": ds_resource["id"], "force": True,
           "fields": [{"id": "city", "type": "text"}, {"id": "value", "type": "numeric"}],
           "records": [{"city": "Ñuble", "value": 2}, {"city": "Paris", "value": 4}]})
    ds_api = base + f"/dashboard-api/resource/{ds_resource['id']}"
    ds_source = {"kind": "datastore", "delimiter": ";", "encoding": "cp1252"}
    ds_profile = poll(session, ds_api + "/profile", {"source": ds_source}).json()
    assert ds_profile["rows"] == 2 and len(ds_profile["fields"]) == 2, ds_profile
    ds_config = {"source": ds_source, "widgets": [{"id": "average", "type": "kpi", "aggregate": "avg", "y_field": "value"}, {"id": "table", "type": "table"}]}
    ds_query = poll(session, ds_api + "/query", {"config": ds_config}).json()
    assert ds_query["results"]["average"]["value"] == 3, ds_query
    assert ds_query["results"]["table"]["rows"][0]["city"] == "Ñuble"
    ds_views = action(session, base, "resource_view_list", {"id": ds_resource["id"]})
    assert not any(v["view_type"] == "dashboard_view" for v in ds_views)
    ds_generation = ds_profile["generation"]
    action(session, base, "datastore_upsert", {"resource_id": ds_resource["id"], "force": True, "method": "insert", "records": [{"city": "Berlin", "value": 6}]})
    forced = session.post(ds_api + "/refresh", json={"source": ds_source}, timeout=30)
    assert forced.status_code in (200, 202), (forced.status_code, forced.text[:500])
    ds_refreshed = poll(session, ds_api + "/profile", {"source": ds_source}, fresh=True).json()
    assert ds_refreshed["rows"] == 3 and ds_refreshed["generation"] != ds_generation, ds_refreshed
    ds_changed = poll(session, ds_api + "/query", {"config": ds_config}, fresh=True).json()
    assert ds_changed["results"]["average"]["value"] == 4, ds_changed
    output = ROOT / "output" / "http"
    output.mkdir(parents=True, exist_ok=True)
    report.update({"base": base, "status": "passed", "stage": "complete", "package_id": package["id"], "resource_id": resource_id, "view_id": view["id"],
              "dashboard_url": base + f"/dashboard/{view['id']}", "embed_url": embed_url,
              "checks": ["manual-only", "native-form-save", "round-trip-layout", "RQ-preparation", "RQ-query", "exact-aggregates",
                         "anonymous-filters", "CSV-export", "embed-headers", "anonymous-edit-denied", "private-cache-revocation", "authorized-private-query", "native-form-update", "resource-refresh", "map-filtered-export", "DataStore-snapshot", "DataStore-parser-switch", "DataStore-manual-refresh"]})
    if has_datashare:
        report["checks"].append("datashare-viewable-download-denied")
    checkpoint()
    (output / (host + ".json")).write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:5189")
    parser.add_argument("--user", default="dashboard_admin")
    parser.add_argument("--token-file")
    parser.add_argument("--dev", action="store_true")
    parser.add_argument("--package-defaults")
    arguments = parser.parse_args()
    try:
        main(arguments)
    except Exception as exc:
        checkpoint = getattr(arguments, "_checkpoint", None)
        if checkpoint:
            checkpoint(status="failed", error=type(exc).__name__ + ": " + str(exc)[:500])
        raise
