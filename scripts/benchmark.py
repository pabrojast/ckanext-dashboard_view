"""Reproducible numerical and memory benchmark; synthetic files stay in output/."""
import argparse
import csv
import json
from pathlib import Path
import resource
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ckanext.dashboard_view.engine import prepare_table, query_table


def run(rows):
    directory = ROOT / "output" / "benchmarks" / str(rows)
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / "source.csv"
    database = directory / "source.duckdb"
    start = time.perf_counter()
    with source.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", "country", "value", "lat", "lon"])
        batch = [[f"2025-{i % 12 + 1:02}-01", ("CL", "FR", "BE", "BR", "KE")[i % 5],
                  f"{i % 100 / 10:.1f}", f"{i % 150 - 75:.2f}", f"{i % 330 - 165:.2f}"] for i in range(9900)]
        remaining = rows
        while remaining:
            n = min(len(batch), remaining)
            writer.writerows(batch[:n])
            remaining -= n
    generation_seconds = time.perf_counter() - start
    database.unlink(missing_ok=True)
    start = time.perf_counter()
    profile = prepare_table(str(source), str(database), limits={"max_rows": rows, "memory_limit": "1GB", "threads": 2})
    prepare_seconds = time.perf_counter() - start
    config = {"schema_version": 1, "source": {}, "widgets": [
        {"id": "count", "type": "kpi", "aggregate": "count"},
        {"id": "median", "type": "kpi", "aggregate": "median", "y_field": "value"},
        {"id": "countries", "type": "bar", "aggregate": "count", "x_field": "country"},
        {"id": "trend", "type": "line", "aggregate": "avg", "x_field": "date", "y_field": "value", "time_grain": "month"},
        {"id": "hist", "type": "histogram", "aggregate": "count", "y_field": "value", "bins": 20},
        {"id": "map", "type": "map", "aggregate": "avg", "lat_field": "lat", "lon_field": "lon", "y_field": "value"}
    ], "filters": [{"field": "country", "type": "category", "label": "Country"}]}
    timings = []
    result = None
    for _ in range(7):
        start = time.perf_counter()
        result = query_table(str(database), config)
        timings.append(time.perf_counter() - start)
    assert result["rows"] == rows, result
    assert result["results"]["count"]["value"] == rows, result["results"]["count"]
    assert abs(result["results"]["median"]["value"] - 4.95) < 1e-9
    assert sum(result["results"]["hist"]["datasets"][0]["data"]) == rows
    assert sum(point["count"] for point in result["results"]["map"]["points"]) == rows
    assert sorted(result["results"]["countries"]["datasets"][0]["data"]) == [rows // 5] * 5
    assert all("error" not in item for item in result["results"].values()), result
    warm = timings[1:]
    report = {"rows": rows, "input_bytes": source.stat().st_size, "database_bytes": database.stat().st_size,
              "generation_seconds": round(generation_seconds, 3), "prepare_seconds": round(prepare_seconds, 3),
              "query_seconds": [round(t, 3) for t in timings],
              "warm_p95_seconds": round(sorted(warm)[-1], 3),
              "peak_rss_mib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
              "response_bytes": len(json.dumps(result)), "correctness": "count, median, six widget results verified"}
    (directory / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=1000000)
    run(parser.parse_args().rows)
