"""Viewport aggregates operate on complete authorized snapshots, not UI pages."""
import csv
import json
from pathlib import Path

import fakeredis
import pytest

from ckanext.dashboard_view import engine, service
from ckanext.dashboard_view.simple import schema, sources, spatial, result_cache


def state(w=-10, e=10, quality='quick'):
    return schema.state({'start': '2024-01-01', 'end': '2024-12-31', 'spatial': {
        'mode': 'fixed' if quality == 'native' else 'viewport', 'quality': quality,
        'bounds': {'west': w, 'east': e, 'south': -5, 'north': 5}}})


@pytest.fixture
def table(tmp_path):
    raw = tmp_path / 'data.csv'
    raw.write_text('lon,lat,value,date\n0,0,10,2024-06-01\n1,1,20,2024-06-01\n1,1,,2024-06-01\n0,0,900,2023-01-01\n30,0,100,2024-06-01\n179,0,40,2024-06-01\n-179,0,60,2024-06-01\n999,0,999,2024-06-01\n')
    db = tmp_path / 'table.duckdb'
    profile = engine.prepare_table(raw, db)
    (tmp_path / 'profile.json').write_text(json.dumps(profile))
    return db


def query(table, selection):
    source = {'kind': 'table', 'filters': [], 'date_field': 'date'}
    block = {'id': 'mean', 'type': 'kpi', 'aggregate': 'avg', 'y_field': 'value'}
    return sources.query_blocks(source, [block], table, selection)[0]['mean']


def test_visible_mean_filters_before_aggregation_and_excludes_missing_values(table):
    value = query(table, state())
    assert value['value'] == 15
    assert value['count'] == 3 and value['valid_count'] == 2
    assert value['spatial_scope'] == 'observations'


def test_antimeridian_and_empty_extent(table):
    assert query(table, state(170, -170))['value'] == 50
    value = query(table, state(70, 80))
    assert value['value'] is None and value['count'] == 0


def test_unlocated_source_is_explicitly_unfiltered(table):
    profile = {'fields': [{'key': 'value', 'type': 'number'}]}
    assert spatial.table_selection({'kind': 'table'}, table, state(), profile) == ({}, 'unfiltered')
    with pytest.raises(ValueError):
        spatial.coordinate_fields({'latitude_field': 'missing'}, profile)


def test_internal_row_filter_keeps_all_selected_rows_before_aggregation(table):
    value = engine.query_table(table, {'widgets': [{'id': 'mean', 'type': 'kpi', 'aggregate': 'avg', 'y_field': 'value'}]}, row_ids=[0, 1])
    assert value['results']['mean']['value'] == 15
    with pytest.raises(ValueError):
        engine.query_table(table, {'widgets': []}, row_ids=['0); DROP TABLE data'])


@pytest.mark.parametrize('extent', [None, {}, {'west': 0, 'south': 1, 'east': 2, 'north': -1}, {'west': float('nan'), 'south': 0, 'east': 10, 'north': 5}])
def test_invalid_extents_fail_closed(extent):
    with pytest.raises(ValueError):
        schema.state({'spatial': {'mode': 'viewport', 'bounds': extent}})


def test_native_requires_fixed_area_and_legacy_state_stays_compatible():
    assert schema.state() == {'start': None, 'end': None, 'area': None}
    assert state(quality='native')['spatial']['mode'] == 'fixed'
    with pytest.raises(ValueError):
        schema.state({'spatial': dict(state()['spatial'], quality='native')})


def test_spatial_cache_expires_without_persisting_camera_results(monkeypatch):
    redis = fakeredis.FakeRedis()
    monkeypatch.setattr(service, 'redis_connection', lambda: redis)
    result_cache.put('sample', {'value': 15}, state())
    assert result_cache.cached('sample', state())[0] == {'value': 15}
    assert 0 < redis.ttl('simple-dashboard:extent:sample') <= 3600
    redis.delete('simple-dashboard:extent:sample')
    assert result_cache.cached('sample', state()) == (None, 0)


def test_water_body_overlap_uses_extent_instead_of_centroid():
    assert spatial.overlaps([-50, -20, 5, 20], state()['spatial']['bounds'])
    assert spatial.overlaps([175, -2, -175, 2], state(170, -170)['spatial']['bounds'])
    assert not spatial.overlaps([30, 30, 40, 40], state()['spatial']['bounds'])


def test_geojson_preserves_original_row_order_and_reserved_coordinate_names(tmp_path, monkeypatch):
    monkeypatch.setattr(service, 'setting', lambda _: 100)
    raw = tmp_path / 'features.json'
    raw.write_text(json.dumps({'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'properties': {'value': 3, '_longitude': 999}, 'geometry': {'type': 'Point', 'coordinates': [1, 2]}},
        {'type': 'Feature', 'properties': {'value': 6}, 'geometry': {'type': 'Polygon', 'coordinates': [[[0, 0], [3, 0], [3, 3], [0, 0]]]}}
    ]}))
    converted = tmp_path / 'features.csv'
    sources.geojson_csv(raw, converted)
    rows = list(csv.DictReader(converted.open()))
    assert rows[0]['_longitude'] == '1' and rows[1]['value'] == '6'
