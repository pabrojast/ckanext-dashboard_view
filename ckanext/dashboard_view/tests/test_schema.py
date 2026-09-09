import json

import pytest

from ckanext.dashboard_view.schema import normalize_config, normalize_source, validate_filters


def test_normalizes_safe_versioned_configuration():
    result = normalize_config(json.dumps({"widgets": [{"type": "map", "id": "map1", "x": 11, "w": 6, "h": 2}], "source": {"delimiter": "\\t", "encoding": "latin1"}}))
    assert result["schema_version"] == 1
    assert result["widgets"][0]["x"] == 6
    assert result["widgets"][0]["h"] == 5
    assert result["source"]["delimiter"] == "\t"
    assert result["source"]["encoding"] == "iso8859-1"
    assert "url" not in normalize_source({"url": "file:///etc/passwd"})


@pytest.mark.parametrize("value", [None, [], "{", {"schema_version": True}, {"schema_version": 2}, {"widgets": [{}]},
    {"widgets": [{"type": "<script>"}]}, {"widgets": [{"type": []}]},
    {"widgets": [{"type": "text", "id": "__bad<script>"}]},
    {"widgets": [{"type": "text", "id": "same"}, {"type": "text", "id": "same"}]},
    {"widgets": [{"type": "text", "w": -1}]}, {"widgets": [{"type": "text", "w": 10 ** 400}]},
    {"widgets": [{"type": "text", "color": "url(javascript:evil)"}]},
    {"widgets": [{"type": "text", "show_legend": "true"}]},
    {"widgets": [{"type": "text", "text": "x" * 10001}]},
    {"widgets": [{"id": str(i), "type": "text"} for i in range(25)]}])
def test_rejects_invalid_configuration(value):
    with pytest.raises(ValueError):
        normalize_config(value)


def test_empty_editor_can_be_previewed_but_not_saved():
    assert normalize_config({}, allow_empty=True)["widgets"] == []
    with pytest.raises(ValueError):
        normalize_config({})


@pytest.mark.parametrize("source", [{"types": {"amount": "SQL"}}, {"delimiter": "||"}, {"delimiter": "\n"},
    {"encoding": "rot13"}, {"encoding": "no_such_encoding"}, {"kind": "sql"}, {"date_format": "%q"},
    {"types": []}, {"types": {"x\x00": "number"}}])
def test_source_validation(source):
    with pytest.raises(ValueError):
        normalize_source(source)


@pytest.mark.parametrize("filters", [[{"field": "missing", "op": "eq", "value": "X"}],
    [{"field": "x", "op": "sql", "value": "X"}], [{"field": "x", "op": "in", "value": "X"}],
    [{"field": "x", "op": "between", "value": [1]}], [{"field": "x", "op": "eq", "value": {"sql": "X"}}],
    [{"field": "x", "op": "eq", "value": float("inf")}], [{"field": "x", "op": "gte", "value": None}]])
def test_filter_validation(filters):
    with pytest.raises(ValueError):
        validate_filters(filters, [{"key": "x", "type": "text"}])


def test_filter_values_remain_literal():
    filters = [{"field": "x", "op": "in", "value": [None, "'); DROP TABLE data; --"]}]
    assert validate_filters(filters, [{"key": "x", "type": "text"}]) == filters
