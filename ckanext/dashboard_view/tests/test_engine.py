import csv
import io
import json
from pathlib import Path
import zipfile

import duckdb
from openpyxl import Workbook
import pytest

from ckanext.dashboard_view.engine import export_csv, inspect_file, prepare_table, query_table


def config(*widgets, filters=None, source=None):
    return {"widgets": [{"id": "w%s" % index, **widget} for index, widget in enumerate(widgets)],
            "filters": filters or [], "source": source or {}}


def prepare(tmp_path, text, source=None, encoding="utf-8", filename="source.csv", limits=None):
    path = tmp_path / filename
    path.write_text(text, encoding=encoding)
    db = tmp_path / "generation.duckdb"
    profile = prepare_table(path, db, source=source, format_hint=Path(filename).suffix.lstrip("."), limits=limits)
    return db, profile


@pytest.fixture
def observations(tmp_path):
    return prepare(tmp_path, 'country,station,value,date,latitude,longitude,valid\nChile,001,2,2026-01-01,-33,-70,true\nChile,002,4,2026-01-02,-34,-71,false\nChile,003,100,2026-02-01,-35,-72,true\nPeru,004,8,2026-02-02,-10,-73,true\nPeru,005,,2026-03-01,999,-74,false\n,006,10,2026-03-02,-12,200,true\n')


def test_profile_preserves_identifiers_original_values_and_exact_median(observations):
    db, profile = observations
    fields = {field["key"]: field for field in profile["fields"]}
    assert fields["station"]["type"] == "text"
    assert fields["date"]["type"] == "date"
    assert fields["valid"]["type"] == "boolean"
    dashboard = config(*({"type": "kpi", "aggregate": agg, "y_field": "value"} for agg in ["count", "sum", "avg", "median", "min", "max", "count_distinct"]))
    result = query_table(db, dashboard)
    assert [block["value"] for block in result["results"].values()] == [6, 124, 24.8, 8, 2, 100, 5]
    assert result["rows"] == 6
    assert "001" in b"".join(export_csv(db, dashboard)).decode()
    assert "2026-01-01," in b"".join(export_csv(db, dashboard)).decode()
    json.dumps(result, allow_nan=False)


def test_category_series_histogram_time_groups_and_null_category(observations):
    db, _ = observations
    dashboard = config({"type": "bar", "x_field": "country", "y_field": "value", "aggregate": "median"},
        {"type": "bar", "x_field": "country", "series_field": "valid"},
        {"type": "line", "x_field": "date", "time_grain": "month"},
        {"type": "histogram", "x_field": "value", "bins": 4})
    result = query_table(db, dashboard)["results"]
    assert result["w0"]["labels"] == ["(Empty)", "Peru", "Chile"]
    assert result["w0"]["datasets"][0]["data"] == [10, 8, 4]
    assert sum(sum(dataset["data"]) for dataset in result["w1"]["datasets"]) == 6
    assert result["w2"]["labels"] == ["2026-01-01T00:00:00", "2026-02-01T00:00:00", "2026-03-01T00:00:00"]
    assert result["w2"]["datasets"][0]["data"] == [2, 2, 2]
    assert sum(result["w3"]["datasets"][0]["data"]) == 5


def test_all_filters_map_bounds_and_export_use_same_rows(observations):
    db, _ = observations
    dashboard = config({"type": "kpi"}, {"type": "table"},
        {"type": "map", "lat_field": "latitude", "lon_field": "longitude"})
    filters = [{"field": "country", "op": "in", "value": ["Chile", "Peru"]},
        {"field": "value", "op": "between", "value": [3, 101]},
        {"field": "date", "op": "gte", "value": "2026-01-02"},
        {"field": "date", "op": "lte", "value": "2026-02-02"}]
    bounds = {"west": -72.5, "east": -70.5, "south": -36, "north": -33}
    result = query_table(db, dashboard, filters=filters, bounds=bounds)
    assert result["rows"] == result["results"]["w0"]["value"] == 2
    assert len(result["results"]["w2"]["points"]) == 2
    exported = list(csv.DictReader(io.StringIO(b"".join(export_csv(db, dashboard, filters, bounds)).decode())))
    assert [row["station"] for row in exported] == ["002", "003"]


def test_facets_exclude_own_filter_and_ranges_respect_other_filters(observations):
    db, _ = observations
    dashboard = config({"type": "kpi"}, filters=[{"field": "country", "type": "category"}, {"field": "value", "type": "number"}, {"field": "date", "type": "date"}])
    result = query_table(db, dashboard, [{"field": "country", "op": "eq", "value": "Chile"}])
    assert result["rows"] == 3
    assert result["facets"]["country"] == [{"value": "Chile", "count": 3}, {"value": "Peru", "count": 2}, {"value": None, "count": 1}]
    assert result["ranges"]["value"] == {"min": 2, "max": 100}
    assert result["ranges"]["date"]["max"].startswith("2026-02-01")


def test_missing_and_incompatible_columns_fail_per_block(observations):
    db, _ = observations
    dashboard = config({"type": "kpi"}, {"type": "bar", "x_field": "disappeared"},
        {"type": "kpi", "y_field": "country", "aggregate": "sum"}, {"type": "table", "columns": ["gone"]},
        {"type": "text", "text": "A complete narrative section"})
    result = query_table(db, dashboard)["results"]
    assert result["w0"]["value"] == 6
    assert all(result[key]["code"] == "invalid_widget" for key in ["w1", "w2", "w3"])
    assert result["w4"]["text"] == "A complete narrative section"
    with pytest.raises(ValueError, match="no longer available"):
        query_table(db, dashboard, [{"field": "disappeared", "op": "eq", "value": 1}])


def test_sql_injection_in_values_and_identifiers_is_inert(tmp_path):
    evil = 'x"; DROP TABLE data; --'
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow([evil, "country", "value", "x", "series"])
    writer.writerow([10, "x' OR TRUE; --", 2, 7, "A"])
    writer.writerow([20, "safe", 4, 8, "B"])
    db, _ = prepare(tmp_path, stream.getvalue())
    dashboard = config({"type": "kpi", "y_field": evil, "aggregate": "sum"},
        {"type": "bar", "x_field": "country", "y_field": "value", "series_field": "series", "aggregate": "sum"},
        filters=[{"field": "country", "type": "category"}])
    result = query_table(db, dashboard, [{"field": "country", "op": "eq", "value": "x' OR TRUE; --"}])
    assert result["rows"] == 1
    assert result["results"]["w0"]["value"] == 10
    assert result["results"]["w1"]["datasets"][0]["data"] == [2]
    assert query_table(db, dashboard)["rows"] == 2


@pytest.mark.parametrize("encoding", ["utf-8-sig", "cp1252", "utf-16"])
def test_bom_accents_multiline_quoted_decimal_csv(tmp_path, encoding):
    db, profile = prepare(tmp_path, 'station;amount;note;date\n001;"1,25";"Río; Azul\nsegunda línea";31/01/2026\n002;"3,75";"Más";01/02/2026\n',
        encoding=encoding, source={"decimal": ",", "date_format": "%d/%m/%Y"})
    assert profile["delimiter"] == ";"
    result = query_table(db, config({"type": "kpi", "y_field": "amount", "aggregate": "sum"}, {"type": "table"}))["results"]
    assert result["w0"]["value"] == 5
    assert result["w1"]["rows"][0]["date"] == "2026-01-31T00:00:00"
    assert result["w1"]["rows"][0]["note"] == "Río; Azul\nsegunda línea"


def test_tsv_and_duplicate_blank_reserved_headers(tmp_path):
    db, profile = prepare(tmp_path, 'name\tName\t\t__dashboard_internal_row_id__\nA\tB\tC\tD\n', filename="source.tsv")
    assert [field["key"] for field in profile["fields"]] == ["name", "Name_2", "column_3", "__dashboard_internal_row_id___2"]
    result = query_table(db, config({"type": "table"}))
    assert list(result["results"]["w0"]["rows"][0].values()) == ["A", "B", "C", "D"]


def test_type_overrides_preserve_invalid_raw_data(tmp_path):
    db, profile = prepare(tmp_path, "id,value,date\n001,10,01/02/2026\n002,error,02/03/2026\n003,NaN,no-date\n", source={"types": {"value": "number", "date": "date"}, "date_format": "%d/%m/%Y"})
    assert next(field for field in profile["fields"] if field["key"] == "value")["invalid_count"] == 2
    assert len(profile["warnings"]) == 2
    result = query_table(db, config({"type": "kpi", "y_field": "value", "aggregate": "sum"}, {"type": "table"}))
    assert result["results"]["w0"]["value"] == 10
    assert result["results"]["w1"]["rows"][1]["value"] is None
    exported = b"".join(export_csv(db, config({"type": "table"}))).decode()
    assert "error" in exported and "NaN" in exported and "no-date" in exported


def test_ambiguous_dates_and_large_ids_stay_text(tmp_path):
    _, profile = prepare(tmp_path, "date,id\n01/02/2026,9223372036854775807\n02/03/2026,9223372036854775808\n")
    assert all(field["type"] == "text" for field in profile["fields"])
    assert any("Ambiguous dates" in warning for warning in profile["warnings"])


def test_xlsx_sheet_selection_and_expansion_limits(tmp_path):
    workbook = Workbook()
    workbook.active.title = "Instructions"
    workbook.active.append(["note"])
    workbook.active.append(["Choose observations"])
    worksheet = workbook.create_sheet("Observations")
    worksheet.append(["station", "value"])
    worksheet.append(["001", 12.5])
    worksheet.append(["002", 17.5])
    path = tmp_path / "source.xlsx"
    workbook.save(path)
    assert inspect_file(path)["sheets"] == ["Instructions", "Observations"]
    db = tmp_path / "generation.duckdb"
    profile = prepare_table(path, db, source={"sheet": "Observations"}, format_hint="xlsx")
    assert profile["rows"] == 2 and profile["sheet"] == "Observations"
    assert query_table(db, config({"type": "kpi", "aggregate": "sum", "y_field": "value"}))["results"]["w0"]["value"] == 30
    with pytest.raises(ValueError, match="expanded spreadsheet"):
        prepare_table(path, tmp_path / "limited.duckdb", format_hint="xlsx", limits={"max_xlsx_uncompressed_bytes": 100})
    with pytest.raises(ValueError, match="worksheet"):
        prepare_table(path, tmp_path / "missing.duckdb", source={"sheet": "Gone"}, format_hint="xlsx")


@pytest.mark.parametrize("limit", [{"max_rows": 1}, {"max_columns": 1}, {"max_bytes": 1}])
def test_limits_leave_no_partial_database(tmp_path, limit):
    with pytest.raises(ValueError, match="limit"):
        prepare(tmp_path, "a,b\n1,2\n3,4\n", limits=limit)
    assert not (tmp_path / "generation.duckdb").exists()


def test_existing_generation_never_overwritten_and_malformed_csv_is_not_skipped(tmp_path):
    db, _ = prepare(tmp_path, "a,b\n1,2\n")
    with pytest.raises(ValueError, match="already exists"):
        prepare_table(tmp_path / "source.csv", db)
    assert query_table(db, config({"type": "kpi"}))["rows"] == 1
    bad = tmp_path / "bad.csv"
    bad.write_text("a,b\n1,2\n3,4,5\n")
    with pytest.raises(ValueError, match="could not be prepared"):
        prepare_table(bad, tmp_path / "bad.duckdb", source={"delimiter": ","})
    assert not (tmp_path / "bad.duckdb").exists()


def test_empty_filtered_results_are_truthful(observations):
    db, _ = observations
    dashboard = config({"type": "kpi", "aggregate": "sum", "y_field": "value"}, {"type": "kpi"},
        {"type": "histogram", "x_field": "value"}, {"type": "bar", "x_field": "country"},
        {"type": "scatter", "x_field": "latitude", "y_field": "value"},
        {"type": "map", "lat_field": "latitude", "lon_field": "longitude"})
    result = query_table(db, dashboard, [{"field": "country", "op": "in", "value": []}])
    assert result["rows"] == 0
    assert result["results"]["w0"]["value"] is None
    assert result["results"]["w1"]["value"] == 0
    assert result["results"]["w2"]["labels"] == []
    assert result["results"]["w5"]["points"] == []


def test_header_only_table(tmp_path):
    db, profile = prepare(tmp_path, "country,value\n")
    assert profile["rows"] == 0
    assert query_table(db, config({"type": "table"}))["results"]["w0"]["rows"] == []


def test_export_formula_defense_and_long_text_pagination(tmp_path):
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["=HYPERLINK(1)", "value", "text"])
    for index in range(60):
        writer.writerow([" \t=HYPERLINK(1)" if index == 0 else "@SUM(1)", -2, "a" * 2500])
    db, _ = prepare(tmp_path, stream.getvalue())
    dashboard = config({"type": "table"})
    table = query_table(db, dashboard, pages={"w0": 2})["results"]["w0"]
    assert table["total"] == 60 and len(table["rows"]) == 10 and table["truncated"]
    assert len(table["rows"][0]["text"]) == 2001
    exported = list(csv.reader(io.StringIO(b"".join(export_csv(db, dashboard)).decode())))
    assert exported[0][0].startswith("'=") and exported[1][0].startswith("' \t=") and exported[2][0].startswith("'@")
    assert exported[1][1] == "-2" and len(exported[1][2]) == 2500


def test_map_dateline_and_invalid_coordinates(tmp_path):
    db, _ = prepare(tmp_path, "lat,lon\n5,179\n6,-179\n7,0\n999,170\n")
    dashboard = config({"type": "map", "lat_field": "lat", "lon_field": "lon"}, {"type": "kpi"})
    result = query_table(db, dashboard, bounds={"west": 175, "east": -175, "south": -10, "north": 10})
    assert result["rows"] == 2 and len(result["results"]["w0"]["points"]) == 2
    assert query_table(db, dashboard)["results"]["w0"]["valid_count"] == 3
    with pytest.raises(ValueError, match="bounds"):
        query_table(db, dashboard, bounds={"west": float("nan"), "east": 0, "south": 0, "north": 1})


def test_reductions_are_bounded_and_exact_aggregates_unchanged(tmp_path):
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["country", "lat", "lon", "value"])
    for index in range(5000):
        writer.writerow(["category%s" % (index % 200), -40 + (index % 100) / 10, -75 + (index % 200) / 10, index])
    db, _ = prepare(tmp_path, stream.getvalue())
    dashboard = config({"type": "map", "lat_field": "lat", "lon_field": "lon", "y_field": "value", "aggregate": "median"},
        {"type": "scatter", "x_field": "lat", "y_field": "value", "series_field": "country"},
        {"type": "bar", "x_field": "country", "limit": 10},
        {"type": "kpi", "y_field": "value", "aggregate": "median"}, filters=[{"field": "country", "type": "category"}])
    result = query_table(db, dashboard)
    mapping, scatter, bar, kpi = [result["results"]["w%s" % index] for index in range(4)]
    assert mapping["aggregated"] and len(mapping["points"]) <= 2000
    assert sum(point["count"] for point in mapping["points"]) == 5000
    assert scatter["sampled"] and sum(len(dataset["data"]) for dataset in scatter["datasets"]) == 2000
    assert scatter["truncated"] and len(scatter["datasets"]) <= 9
    assert bar["truncated"] and len(bar["labels"]) == 10
    assert kpi["value"] == 2499.5
    assert len(result["facets"]["country"]) == 100 and result["facets_truncated"] == ["country"]


def test_csv_hash_rows_are_data_and_null_markers_are_not_guessed(tmp_path):
    db, profile = prepare(tmp_path, "station,value\n#one,NA\n#two,NULL\n#three,N/A\n")
    assert profile["rows"] == 3
    table = query_table(db, config({"type": "table"}))["results"]["w0"]
    assert [row["station"] for row in table["rows"]] == ["#one", "#two", "#three"]
    assert [row["value"] for row in table["rows"]] == ["NA", "NULL", "N/A"]


def test_dates_normalize_timezones_and_end_dates_include_whole_day(tmp_path):
    db, _ = prepare(tmp_path, "date,value\n2026-01-01T23:00:00-03:00,1\n2026-01-02T23:59:59Z,2\n2026-01-03T00:00:00Z,3\n")
    dashboard = config({"type": "table"})
    table = query_table(db, dashboard)["results"]["w0"]
    assert table["rows"][0]["date"] == "2026-01-02T02:00:00"
    assert query_table(db, dashboard, [{"field": "date", "op": "between", "value": ["2026-01-02", "2026-01-02"]}])["rows"] == 2
    assert query_table(db, dashboard, [{"field": "date", "op": "lte", "value": "2026-01-02"}])["rows"] == 2
    assert query_table(db, dashboard, [{"field": "date", "op": "eq", "value": "2026-01-01T23:00:00-03:00"}])["rows"] == 1


@pytest.mark.parametrize("numbers", [["-1e308", "0", "1e308"], ["0", "5e-324"], ["5", "5", "5"]])
def test_histogram_extreme_numbers_and_constant_values_remain_counted(tmp_path, numbers):
    db, _ = prepare(tmp_path, "value\n" + "\n".join(numbers) + "\n")
    result = query_table(db, config({"type": "histogram", "x_field": "value"}))["results"]["w0"]
    assert sum(result["datasets"][0]["data"]) == len(numbers)
    json.dumps(result, allow_nan=False)


def test_huge_categories_do_not_make_huge_responses_or_unusable_facets(tmp_path):
    db, _ = prepare(tmp_path, "label,value\n" + "x" * 10000 + ",1\nshort,2\n")
    result = query_table(db, config({"type": "bar", "x_field": "label"}, filters=[{"field": "label", "type": "category"}]))
    assert max(map(len, result["results"]["w0"]["labels"])) <= 513
    assert result["results"]["w0"]["text_truncated"]
    assert result["facets"]["label"] == [{"value": "short", "count": 1}]
    assert result["facets_truncated"] == ["label"]


def test_numeric_overflow_is_disclosed_without_breaking_other_blocks(tmp_path):
    db, _ = prepare(tmp_path, "group,value\nA,1e308\nA,1e308\n")
    result = query_table(db, config({"type": "kpi", "aggregate": "sum", "y_field": "value"},
        {"type": "bar", "x_field": "group", "aggregate": "sum", "y_field": "value"}, {"type": "kpi"}))
    assert "numeric range" in result["results"]["w0"]["error"]
    assert "numeric range" in result["results"]["w1"]["error"]
    assert result["results"]["w2"]["value"] == 2


def test_category_click_filters_preserve_null_boolean_and_temporal_identity(observations):
    db, _ = observations
    dashboard = config({"type": "bar", "x_field": "country"}, {"type": "bar", "x_field": "valid"},
        {"type": "line", "x_field": "date", "time_grain": "month"})
    results = query_table(db, dashboard)["results"]
    for key in ("w0", "w1", "w2"):
        result = results[key]
        for index, category in enumerate(result["category_filters"]):
            filtered = query_table(db, config({"type": "kpi"}), [category])
            assert filtered["rows"] == result["datasets"][0]["data"][index]
    empty_index = results["w0"]["labels"].index("(Empty)")
    assert results["w0"]["category_filters"][empty_index]["value"] is None
    assert results["w2"]["category_filters"][1]["value"] == ["2026-02-01", "2026-02-28"]


def test_long_category_clicks_keep_bounded_original_or_are_disabled(tmp_path):
    db, _ = prepare(tmp_path, "label\n" + "x" * 1000 + "\n" + "y" * 3000 + "\n")
    result = query_table(db, config({"type": "bar", "x_field": "label"}))["results"]["w0"]
    assert result["category_filters"][0]["value"] == "x" * 1000
    assert result["category_filters"][1] is None


def test_xlsx_in_memory_metadata_is_bounded_even_when_zip_is_small(tmp_path):
    path = tmp_path / "metadata.xlsx"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/styles.xml", b" " * (8 * 1024 * 1024 + 1))
    assert path.stat().st_size < 10000
    with pytest.raises(ValueError, match="style metadata"):
        prepare_table(path, tmp_path / "generation.duckdb", format_hint="xlsx")


def test_bounds_identify_the_map_whose_coordinates_should_filter_all_blocks(tmp_path):
    db, _ = prepare(tmp_path, "origin_lat,origin_lon,destination_lat,destination_lon\n0,0,40,40\n40,40,0,0\n")
    dashboard = config({"type": "map", "lat_field": "origin_lat", "lon_field": "origin_lon"},
        {"type": "map", "lat_field": "destination_lat", "lon_field": "destination_lon"}, {"type": "table"})
    bounds = {"west": -1, "east": 1, "south": -1, "north": 1, "widget_id": "w1"}
    result = query_table(db, dashboard, bounds=bounds)
    assert result["rows"] == 1
    assert result["results"]["w2"]["rows"][0]["origin_lat"] == 40
    rows = list(csv.DictReader(io.StringIO(b"".join(export_csv(db, dashboard, bounds=bounds)).decode())))
    assert rows[0]["origin_lat"] == "40"
    with pytest.raises(ValueError, match="map with valid"):
        query_table(db, dashboard, bounds=dict(bounds, widget_id="w2"))
