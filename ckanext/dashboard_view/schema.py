"""Small, dependency-free validation boundary for dashboard configuration."""

import codecs
import json
import math
import re


WIDGET_TYPES = frozenset({"kpi", "line", "area", "bar", "doughnut", "scatter", "histogram", "table", "text", "map"})
AGGREGATES = frozenset({"count", "count_distinct", "sum", "avg", "median", "min", "max"})
FIELD_TYPES = frozenset({"text", "number", "date", "boolean"})
MAX_WIDGETS = 24
MAX_FILTERS = 12
MAX_CONFIG_BYTES = 262144


def _text(value, name, maximum=200, nullable=False):
    if nullable and (value is None or value == ""):
        return None
    if not isinstance(value, str) or len(value) > maximum or "\x00" in value:
        raise ValueError("Invalid %s." % name)
    return value


def _integer(value, name, lower, upper):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or (isinstance(value, float) and (not math.isfinite(value) or int(value) != value)):
        raise ValueError("%s must be a whole number." % name)
    if not lower <= value <= upper:
        raise ValueError("%s must be between %s and %s." % (name, lower, upper))
    return int(value)


def _choice(value, choices, name):
    if not isinstance(value, str) or value not in choices:
        raise ValueError("Invalid %s." % name)
    return value


def _field(value, name="column", nullable=False):
    result = _text(value, name, 512, nullable)
    if result == "":
        raise ValueError("Choose a %s." % name)
    return result


def _color(value):
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise ValueError("Colors must use #RRGGBB format.")
    return value


def normalize_source(value=None):
    """Return a bounded source interpretation, never a URL or filesystem path."""
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError("Source must be an object.")
    source = {"kind": _choice(value.get("kind", "file"), {"file", "datastore"}, "source kind")}
    source["sheet"] = _text(value.get("sheet"), "worksheet", 128, True)
    delimiter = value.get("delimiter") or None
    if delimiter == "\\t":
        delimiter = "\t"
    if delimiter is not None and (not isinstance(delimiter, str) or len(delimiter) != 1 or delimiter in "\r\n\x00\""):
        raise ValueError("Choose one delimiter character.")
    source["delimiter"] = delimiter
    encoding = _text(value.get("encoding"), "encoding", 40, True)
    if encoding:
        try:
            encoding = codecs.lookup(encoding).name
        except LookupError as exc:
            raise ValueError("Unsupported text encoding.") from exc
        if encoding not in {"utf-8", "utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "iso8859-1", "cp1252", "ascii"}:
            raise ValueError("Unsupported text encoding.")
    source["encoding"] = encoding
    date_format = _text(value.get("date_format"), "date format", 64, True)
    if date_format and re.search(r"%(?![YymdHMSfzZbBjpUWVaAuwGgvcCxX%])", date_format):
        raise ValueError("Unsupported date format. Use strptime format codes.")
    source["date_format"] = date_format
    source["decimal"] = _choice(value.get("decimal", "."), {".", ","}, "decimal separator")
    types = value.get("types", {})
    if not isinstance(types, dict) or len(types) > 500:
        raise ValueError("Column type overrides must be an object with at most 500 columns.")
    source["types"] = {_field(key): _choice(kind, FIELD_TYPES, "column type") for key, kind in types.items()}
    return source


def normalize_config(value, allow_empty=False):
    if isinstance(value, str):
        if len(value.encode("utf-8")) > MAX_CONFIG_BYTES:
            raise ValueError("Dashboard configuration is too large.")
        try:
            value = json.loads(value)
        except (ValueError, RecursionError) as exc:
            raise ValueError("Dashboard configuration is not valid JSON.") from exc
    if not isinstance(value, dict):
        raise ValueError("Dashboard configuration must be an object.")
    try:
        if len(json.dumps(value, allow_nan=False).encode("utf-8")) > MAX_CONFIG_BYTES:
            raise ValueError("Dashboard configuration is too large.")
    except (TypeError, RecursionError) as exc:
        raise ValueError("Invalid dashboard configuration.") from exc
    if type(value.get("schema_version", 1)) is not int or value.get("schema_version", 1) != 1:
        raise ValueError("Unsupported dashboard configuration version.")
    raw_widgets = value.get("widgets", [])
    if not isinstance(raw_widgets, list) or len(raw_widgets) > MAX_WIDGETS or (not raw_widgets and not allow_empty):
        raise ValueError("A dashboard must contain between 1 and 24 blocks.")
    widgets, identifiers = [], set()
    for index, raw in enumerate(raw_widgets):
        if not isinstance(raw, dict):
            raise ValueError("Each dashboard block must be an object.")
        identifier = _text(raw.get("id", "w%s" % (index + 1)), "block identifier", 80)
        if not re.fullmatch(r"[A-Za-z0-9_-]+", identifier) or identifier in identifiers:
            raise ValueError("Block identifiers must be unique letters, numbers, underscores or hyphens.")
        identifiers.add(identifier)
        kind = _choice(raw.get("type"), WIDGET_TYPES, "block type")
        width = _integer(raw.get("w", 6), "Block width", 1, 12)
        minimum_height = 5 if kind == "map" else 2 if kind in {"text", "kpi", "table"} else 4
        # Older saved layouts remain readable: normalize the documented minimum.
        height = max(minimum_height, _integer(raw.get("h", minimum_height), "Block height", 1, 50))
        widget = {"id": identifier, "type": kind, "title": _text(raw.get("title", ""), "block title"),
                  "x": min(_integer(raw.get("x", 0), "Block x", 0, 11), 12 - width),
                  "y": _integer(raw.get("y", index * 4), "Block y", 0, 10000), "w": width, "h": height,
                  "aggregate": _choice(raw.get("aggregate", "count"), AGGREGATES, "aggregation"),
                  "limit": _integer(raw.get("limit", 20), "Category limit", 1, 100),
                  "bins": _integer(raw.get("bins", 20), "Histogram bins", 2, 100),
                  "color": _color(raw.get("color", "#0069b4")),
                  "time_grain": _choice(raw.get("time_grain", "none"), {"none", "day", "month", "year"}, "time grouping"),
                  "sort": _choice(raw.get("sort", "desc"), {"asc", "desc"}, "sort order"),
                  "show_legend": raw.get("show_legend", True)}
        if not isinstance(widget["show_legend"], bool):
            raise ValueError("Legend visibility must be true or false.")
        for name in ("x_field", "y_field", "series_field", "lat_field", "lon_field"):
            widget[name] = _field(raw.get(name), name, True)
        columns = raw.get("columns", [])
        if not isinstance(columns, list) or len(columns) > 500:
            raise ValueError("Table columns must be a list of at most 500 columns.")
        widget["columns"] = list(dict.fromkeys(_field(column) for column in columns))
        widget["text"] = _text(raw.get("text", ""), "text block", 10000)
        widget["unit"] = _text(raw.get("unit", ""), "unit", 40)
        widgets.append(widget)
    raw_filters = value.get("filters", [])
    if not isinstance(raw_filters, list) or len(raw_filters) > MAX_FILTERS:
        raise ValueError("A dashboard can contain at most 12 filters.")
    filters = []
    for item in raw_filters:
        if not isinstance(item, dict):
            raise ValueError("Each filter must be an object.")
        filters.append({"field": _field(item.get("field")),
                        "type": _choice(item.get("type", "category"), {"category", "number", "date"}, "filter type"),
                        "label": _text(item.get("label", item.get("field", "")), "filter label")})
    style = value.get("style", {})
    if not isinstance(style, dict):
        raise ValueError("Dashboard style must be an object.")
    return {"schema_version": 1, "source": normalize_source(value.get("source")), "widgets": widgets,
            "filters": filters, "style": {"accent": _color(style.get("accent", "#0069b4"))}}


def validate_filters(filters, fields):
    """Validate runtime values; SQL generation still binds every value separately."""
    if filters is None:
        return []
    if not isinstance(filters, list) or len(filters) > 24:
        raise ValueError("At most 24 filter conditions are allowed.")
    if isinstance(fields, dict):
        field_map = fields
    else:
        field_map = {field["key"]: field for field in fields}
    normalized = []
    for item in filters:
        if not isinstance(item, dict):
            raise ValueError("Each filter condition must be an object.")
        field = _field(item.get("field"))
        if field not in field_map:
            raise ValueError("Filter column '%s' is no longer available." % field)
        op = _choice(item.get("op", "eq"), {"in", "eq", "gte", "lte", "between"}, "filter operation")
        value = item.get("value")
        values = value if op in {"in", "between"} else [value]
        if not isinstance(values, list) or len(values) > 100 or (op == "between" and len(values) != 2):
            raise ValueError("Invalid filter values.")
        for entry in values:
            if isinstance(entry, (list, dict)) or not isinstance(entry, (str, int, float, bool, type(None))):
                raise ValueError("Filter values must be scalar values.")
            if isinstance(entry, str) and (len(entry) > 2000 or "\x00" in entry):
                raise ValueError("Filter value is too long.")
            if isinstance(entry, float) and not math.isfinite(entry):
                raise ValueError("Filter numbers must be finite.")
            if entry is None and op in {"between", "gte", "lte"}:
                raise ValueError("Range filters cannot use empty values.")
        normalized.append({"field": field, "op": op, "value": value})
    return normalized
