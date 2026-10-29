"""Bounded server calculations with content-addressed block/date reuse."""
import json
import subprocess
import time
from . import store, sources
from .schema import ENGINE_VERSION
from .. import service
from ..security import SourceError


def node(payload):
    import ckan.plugins.toolkit as tk
    script = tk.config.get('ckanext.dashboard_view.simple_calculator', '/opt/terria-calculator/dist/calculator.mjs')
    try:
        result = subprocess.run(['node', '--max-old-space-size=512', script],
            input=json.dumps(payload, allow_nan=False), text=True, capture_output=True, timeout=180, check=True)
        return json.loads(result.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        raise SourceError('The satellite calculation could not finish. Narrow the area or period and retry.', 'source_temporarily_unavailable') from None


def result_from_points(block, points):
    valid = [p['value'] for p in points if p.get('value') is not None]
    kind, aggregate = block['type'], block['aggregate']
    if kind == 'kpi':
        import statistics
        value = (len(valid) if aggregate == 'count' else None if not valid else
                 sum(valid) if aggregate == 'sum' else min(valid) if aggregate == 'min' else
                 max(valid) if aggregate == 'max' else statistics.median(valid) if aggregate == 'median' else
                 len(set(valid)) if aggregate == 'count_distinct' else statistics.mean(valid))
        return {'type': kind, 'value': value, 'count': len(valid)}
    if kind == 'table':
        return {'type': kind, 'columns': ['date', 'value', 'coverage', 'count', 'partial'],
                'rows': [[p.get(k) for k in ['date', 'value', 'coverage', 'count', 'partial']] for p in points], 'count': len(points)}
    return {'type': kind, 'labels': [p['date'] for p in points],
            'datasets': [{'label': block['title'], 'data': [p.get('value') for p in points]}],
            'count': len(valid), 'points': points}


def in_period(day, state):
    day = (day or '')[:10]
    return (not state.get('start') or day >= state['start'][:len(day)]) and (not state.get('end') or day <= state['end'])


def water(source, blocks, state, directory):
    base = sources.trusted_url(source['catalog_url']).rstrip('/')
    meta, mv = sources.json_snapshot(base + '/meta.json', directory)
    product = source.get('product')
    if product not in meta['products'] or source['resolution'] not in ('daily', 'monthly', 'annual'):
        raise SourceError('Choose a supported satellite product and resolution.')
    bodies, bv = sources.json_snapshot(base + '/bodies.json', directory)
    series, sv = sources.json_snapshot(base + '/series/' + product + '.json', directory)
    output = {}
    for block in blocks:
        body = block.get('body_id')
        if body not in series['ids']:
            output[block['id']] = {'type': block['type'], 'error': 'Choose an available water body.'}
            continue
        detail, dv = (None, '')
        if source['resolution'] == 'daily':
            detail, dv = sources.json_snapshot(base + '/lake/' + str(body) + '.json', directory)
        key = service.digest([ENGINE_VERSION, mv, bv, sv, dv, block, state, product, source['resolution']])
        result, _ = store.cached(key)
        if result is None:
            value = node(dict(operation='water', body=body, series=series, detail=detail,
                              product=product, resolution=source['resolution'], meta=meta))
            points = [p for p in value['points'] if in_period(p['date'], state)]
            result = dict(result_from_points(block, points), unit=meta['products'][product]['unit'],
                          method='Water-body core: daily median, monthly median, annual mean of monthly medians.',
                          resolution=source['resolution'], trend=value.get('trend'), source_version=meta.get('sourceVersion') or meta.get('generatedAt'))
            store.put(key, result)
        output[block['id']] = result
    return output, {'bodies': bodies['bodies'], 'products': meta['products'], 'resolution': source['resolution']}


def raster(source, resource, blocks, state, directory):
    url = resource['url']
    # Stored CKAN metadata, never client-supplied conversion parameters.
    config = json.loads(resource.get('simple_dashboard_cog') or '{}')
    if urlsplit_path(url).endswith('.json'):
        manifest, version = sources.json_snapshot(url, directory)
        entries = manifest.get('times', [])
        config.update({k: manifest[k] for k in ('valueScale', 'valueOffset', 'noDataValues', 'unit') if k in manifest})
    else:
        entries, version = [{'time': '', 'cogs': [url]}], service.resource_stamp(resource)
    entries = [e for e in entries if not e.get('time') or in_period(e['time'], state)]
    if not entries or len(entries) > 366:
        raise SourceError('Select a period containing between one and 366 raster dates.')
    output = {}
    for block in blocks:
        area = state.get('area') or block.get('area')
        if not area:
            output[block['id']] = {'type': block['type'], 'error': 'Select a point or draw an area.'}
            continue
        points, resolutions = [], []
        for entry in entries:
            urls = entry.get('cogs', [])
            if len(urls) != 1:
                raise SourceError('This raster series must provide one COG per date.')
            # Validated transport checks every DNS address and redirect at runtime.
            probe = node({'operation': 'probe', 'url': urls[0]})
            stamp = probe if probe.get('etag') or probe.get('modified') else int(time.time() // 300)
            key = service.digest([ENGINE_VERSION, urls[0], version, stamp, config, block['band'], area])
            result, _ = store.cached(key)
            if result is None:
                result = node({'url': urls[0], 'area': area, 'band': block['band'],
                               'scale': config.get('valueScale'), 'offset': config.get('valueOffset'),
                               'noDataValues': config.get('noDataValues')})
                store.put(key, result)
            stats = result.get('statistics', {})
            points.append({'date': entry.get('time', ''), 'value': result.get('value', stats.get('mean')),
                           'count': stats.get('count', 1 if result.get('value') is not None else 0)})
            if result.get('pixelResolution'):
                resolutions.append(result['pixelResolution'])
        output[block['id']] = dict(result_from_points(block, points), unit=config.get('unit', block['unit']),
            method='Pixel value' if area['type'] == 'Point' else 'Polygon mean', band=block['band'],
            pixel_resolutions=resolutions, source_version=version)
    return output, {'fields': [], 'dates': [e.get('time') for e in entries]}


def urlsplit_path(url):
    from urllib.parse import urlsplit
    return urlsplit(url).path.lower()


def calculate(config, actor, directory):
    resources = sources.authorize_all(config, actor)
    results, profiles, warnings = {}, {}, []
    for source, resource in zip(config['sources'], resources):
        blocks = [b for b in config['blocks'] if b['source_id'] == source['id']]
        if source['kind'] == 'water':
            values, profile = water(source, blocks, config['state'], directory)
        elif source['kind'] == 'cog':
            values, profile = raster(source, resource, blocks, config['state'], directory)
        else:
            db, version, profile = sources.tabular(source, resource, actor, directory)
            values = {}
            for block in blocks:
                key = service.digest([ENGINE_VERSION, version, source, block, config['state']])
                value, _ = store.cached(key)
                if value is None:
                    result, notices = sources.query_blocks(source, [block], db, config['state'])
                    warnings.extend(notices)
                    value = dict(result[block['id']], source_version=version, unit=block['unit'])
                    store.put(key, value)
                values[block['id']] = value
        results.update(values)
        profiles[source['id']] = profile
    sources.authorize_all(config, actor)
    return {'results': results, 'profiles': profiles, 'warnings': list(dict.fromkeys(warnings)),
            'calculated_at': time.time(), 'engine_version': ENGINE_VERSION}
