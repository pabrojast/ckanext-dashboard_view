#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
IMAGE="${DASHBOARD_TEST_IMAGE:-dashboard-view-test}"
docker image inspect dashboard-duckdb-wheel:1.5.5 >/dev/null 2>&1 || \
  docker build -f deploy/Dockerfile.duckdb -t dashboard-duckdb-wheel:1.5.5 .
docker build -f Dockerfile.test -t "$IMAGE" .
docker run --rm "$IMAGE" python scripts/check_plugin.py
docker run --rm -e PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 "$IMAGE" python -m pytest -q -p no:ckan ckanext/dashboard_view/tests
