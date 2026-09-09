"""Reproducible dev-only deployment patch, with a minimal reversible backup.

Dry-run is the default. Keeps all existing CKAN environment/sidecars intact.
The only supported ingress target is data.dev-wins.com in the default context.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
from datetime import datetime, timezone


def kubectl(*args, payload=None):
    result = subprocess.run(["kubectl", *args], input=payload, text=True, check=True, capture_output=True)
    return result.stdout


def deploy(image, apply=False):
    context = kubectl("config", "current-context").strip()
    if context != "default":
        raise SystemExit(f"Unexpected context: {context}; this script targets the verified dev cluster only")
    ingress = json.loads(kubectl("-n", "ckan", "get", "ingress", "ckan-ingress", "-o", "json"))
    matches = [r for r in ingress["spec"]["rules"] if r.get("host") == "data.dev-wins.com"]
    if not matches or not any(p["backend"]["service"]["name"] == "ckan" and p["path"] == "/" for p in matches[0]["http"]["paths"]):
        raise SystemExit("Dev ingress no longer targets ckan; inspect before deploying")
    deployment = json.loads(kubectl("-n", "ckan", "get", "deployment", "ckan", "-o", "json"))
    spec = deployment["spec"]["template"]["spec"]
    web = next(c for c in spec["containers"] if c["name"] == "ckan")
    script = 'import configparser; c=configparser.ConfigParser(interpolation=None); c.read("/app/production.ini"); print(c.get("app:main","ckan.plugins"))'
    plugins = kubectl("-n", "ckan", "exec", "deploy/ckan", "-c", "ckan", "--", "python", "-c", script).strip().split()
    if "dashboard_view" not in plugins:
        plugins.append("dashboard_view")
    env = copy.deepcopy(web.get("env", []))
    old_plugin_env = next((e for e in env if e["name"] == "CKAN__PLUGINS"), None)
    env = [e for e in env if e["name"] not in {"CKAN__PLUGINS", "CKANEXT__DASHBOARD_VIEW__CACHE_DIR"}]
    env.extend([{"name": "CKAN__PLUGINS", "value": " ".join(plugins)},
                {"name": "CKANEXT__DASHBOARD_VIEW__CACHE_DIR", "value": "/var/lib/ckan/dashboard-cache"}])
    mount = {"name": "dashboard-cache", "mountPath": "/var/lib/ckan/dashboard-cache"}
    web_patch = {"name": "ckan", "image": image, "env": env,
                 "volumeMounts": [mount]}
    workers = []
    for queue in ("build", "query"):
        worker = {"name": f"dashboard-{queue}", "image": image, "imagePullPolicy": "IfNotPresent",
                  "command": ["/usr/local/bin/ckan", "-c", "/app/production.ini", "dashboard", "worker", "--queue", queue],
                  "env": copy.deepcopy(env),
                  "resources": {"requests": {"cpu": "250m", "memory": "256Mi"}, "limits": {"cpu": "2", "memory": "2Gi"}},
                  "volumeMounts": [mount],
                  "securityContext": {"runAsUser": 92, "runAsGroup": 92, "allowPrivilegeEscalation": False}}
        # If another site has added storage/config mounts, workers need them too.
        for existing in web.get("volumeMounts", []):
            if existing["name"] != "dashboard-cache":
                worker["volumeMounts"].append(copy.deepcopy(existing))
        if web.get("envFrom"):
            worker["envFrom"] = copy.deepcopy(web["envFrom"])
        workers.append(worker)
    patch = {"spec": {"template": {"spec": {
        "securityContext": {"fsGroup": 92},
        "initContainers": [{"name": "dashboard-cache-permissions", "image": image,
                            "command": ["sh", "-c", "chown 92:92 /var/lib/ckan/dashboard-cache && chmod 700 /var/lib/ckan/dashboard-cache"],
                            "securityContext": {"runAsUser": 0, "runAsGroup": 0, "allowPrivilegeEscalation": False},
                            "volumeMounts": [mount]}],
        "containers": [web_patch, *workers],
        "volumes": [{"name": "dashboard-cache", "emptyDir": {"sizeLimit": "12Gi"}}],
    }}}}
    summary = {"context": context, "host": "data.dev-wins.com", "deployment": "ckan/ckan",
               "previous_image": web["image"], "image": image, "workers": [w["name"] for w in workers],
               "cache": "12Gi emptyDir; reconstructible", "plugin": "dashboard_view", "automatic_views": "unchanged"}
    print(json.dumps(summary, indent=2))
    if not apply:
        return
    output = Path(__file__).resolve().parents[1] / "output" / "deploy"
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rollback = {"spec": {"template": {"spec": {"containers": [
        {"name": "ckan", "image": web["image"], "env": ([old_plugin_env] if old_plugin_env else [{"name": "CKAN__PLUGINS", "$patch": "delete"}]) +
         [{"name": "CKANEXT__DASHBOARD_VIEW__CACHE_DIR", "$patch": "delete"}],
         "volumeMounts": [{"name": "dashboard-cache", "$patch": "delete"}]},
        {"name": "dashboard-build", "$patch": "delete"}, {"name": "dashboard-query", "$patch": "delete"}],
        "volumes": [{"name": "dashboard-cache", "$patch": "delete"}],
        "initContainers": [{"name": "dashboard-cache-permissions", "$patch": "delete"}],
        "securityContext": spec.get("securityContext", {}) or {"fsGroup": None}
    }}}}
    # A second release must preserve existing workers for its rollback.
    existing_workers = [c for c in spec["containers"] if c["name"] in {"dashboard-build", "dashboard-query"}]
    if existing_workers:
        rollback["spec"]["template"]["spec"] = {"containers": [
            {"name": "ckan", "image": web["image"]},
            *[{"name": c["name"], "image": c["image"]} for c in existing_workers]],
            "initContainers": [{"name": c["name"], "image": c["image"]}
                               for c in spec.get("initContainers", []) if c["name"] == "dashboard-cache-permissions"]}
    path = output / f"rollback-{stamp}.json"
    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(rollback, handle, indent=2)
    (output / f"release-{stamp}.json").write_text(json.dumps(summary, indent=2))
    # The patch is passed on stdin and never prints environment credentials.
    result = kubectl("-n", "ckan", "patch", "deployment", "ckan", "--type", "strategic", "--patch-file", "/dev/stdin", payload=json.dumps(patch))
    print(result.strip())
    print(f"Rollback saved: {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    deploy(args.image, args.apply)
