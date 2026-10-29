"""Versioned declarative layouts. No expressions, SQL, URLs in blocks or results."""
import json
import math
import re
from datetime import date
from uuid import UUID
from ..schema import normalize_config, normalize_source

ENGINE_VERSION = 'simple-1'


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[\w-]{1,80}', value):
        raise ValueError('Invalid identifier.')
    return value


def text(value, maximum=200):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or '\0' in value:
        raise ValueError('A title or source name is required.')
    return value.strip()


def geometry(value):
    if value is None:
        return None
    if not isinstance(value, dict) or value.get('type') not in ('Point', 'Polygon'):
        raise ValueError('Select a point or a polygon.')
    coordinates = value.get('coordinates')
    if not isinstance(coordinates, list) or (value['type'] == 'Polygon' and any(not isinstance(r, list) for r in coordinates)):
        raise ValueError('Invalid geographic coordinates.')
    points = [coordinates] if value['type'] == 'Point' else [p for ring in coordinates for p in ring]
    if not points or len(points) > 2000:
        raise ValueError('The selected area is too complex.')
    for point in points:
        if (not isinstance(point, list) or len(point) != 2 or
                any(type(x) not in (int, float) or not math.isfinite(x) for x in point) or
                not -180 <= point[0] <= 180 or not -90 <= point[1] <= 90):
            raise ValueError('Invalid geographic coordinates.')
    if value['type'] == 'Polygon' and any(len(r) < 4 or r[0] != r[-1] for r in coordinates):
        raise ValueError('Polygon rings must be closed.')
    return {'type': value['type'], 'coordinates': coordinates}


def state(value=None):
    value = value or {}
    result = {'start': None, 'end': None, 'area': geometry(value.get('area'))}
    for key in ('start', 'end'):
        if value.get(key):
            result[key] = date.fromisoformat(value[key]).isoformat()
    if result['start'] and result['end'] and result['start'] > result['end']:
        raise ValueError('The start date must precede the end date.')
    return result


def normalize(value, allow_empty=False):
    if not isinstance(value, dict) or len(json.dumps(value, allow_nan=False)) > 65536:
        raise ValueError('Invalid dashboard configuration.')
    if value.get('version', 1) != 1:
        raise ValueError('Unsupported dashboard version.')
    sources = value.get('sources', [])
    if not isinstance(sources, list) or not 1 <= len(sources) <= 6:
        raise ValueError('Choose between one and six data sources.')
    normalized, ids = [], set()
    for source in sources:
        sid = identifier(source.get('id'))
        if sid in ids:
            raise ValueError('Source identifiers must be unique.')
        ids.add(sid)
        kind = source.get('kind', 'table')
        if kind not in ('table', 'geojson', 'cog', 'water'):
            raise ValueError('Unsupported data source.')
        resource_id = str(UUID(source['resource_id'])) if source.get('resource_id') else None
        catalog_url = source.get('catalog_url')
        if not resource_id and not catalog_url:
            raise ValueError('Save this source in IHP before saving its dashboard.')
        if catalog_url is not None:
            catalog_url = text(catalog_url, 2000)
        filters = source.get('filters', [])
        if not isinstance(filters, list) or len(filters) > 12:
            raise ValueError('Too many source filters.')
        if source.get('resolution', 'monthly') not in ('daily', 'monthly', 'annual'):
            raise ValueError('Invalid temporal resolution.')
        if source.get('date_field') is not None and not isinstance(source['date_field'], str):
            raise ValueError('Invalid date column.')
        if source.get('product') is not None and not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', str(source['product'])):
            raise ValueError('Invalid product.')
        normalized.append({'id': sid, 'name': text(source.get('name', sid)), 'kind': kind,
                           'resource_id': resource_id, 'catalog_url': catalog_url,
                           'source': normalize_source(source.get('source')),
                           'date_field': source.get('date_field') or None,
                           'filters': filters, 'product': source.get('product'),
                           'resolution': source.get('resolution', 'monthly')})
    raw = value.get('blocks', [])
    if not isinstance(raw, list) or len(raw) > 6 or (not raw and not allow_empty):
        raise ValueError('Add between one and six blocks.')
    widgets = normalize_config({'widgets': raw}, allow_empty=allow_empty)['widgets']
    blocks = []
    for block, widget in zip(raw, widgets):
        if widget['type'] not in ('kpi', 'line', 'bar', 'table') or block.get('source_id') not in ids:
            raise ValueError('Choose a source and a supported block type.')
        body_id = block.get('body_id')
        if body_id is not None and (type(body_id) is not int or body_id < 0):
            raise ValueError('Choose a water body.')
        band = block.get('band', 1)
        if type(band) is not int or not 1 <= band <= 256:
            raise ValueError('Invalid raster band.')
        blocks.append(dict(widget, source_id=block['source_id'], body_id=body_id, band=band,
                           area=geometry(block.get('area'))))
    return {'version': 1, 'title': text(value.get('title', 'Dashboard')), 'sources': normalized,
            'blocks': blocks, 'state': state(value.get('state'))}
