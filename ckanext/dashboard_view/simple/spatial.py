"""Spatial selection shared by immutable tables, satellite jobs and exports."""
import re
from pathlib import Path


def extent(state):
    value = state.get('spatial') or {}
    return value.get('bounds') if value.get('mode') in ('viewport', 'fixed') else None


def polygons(bounds):
    w, s, e, n = [bounds[k] for k in ('west', 'south', 'east', 'north')]
    spans = [(w, e)] if w < e else [(w, 180), (-180, e)]
    return [{'type': 'Polygon', 'coordinates': [[[a, s], [b, s], [b, n], [a, n], [a, s]]]}
            for a, b in spans if a != b]


def overlaps(box, bounds):
    if not isinstance(box, list) or len(box) != 4:
        return False
    west, south, east, north = box
    if south > bounds['north'] or north < bounds['south']:
        return False
    boxes = [(west, east)] if west <= east else [(west, 180), (-180, east)]
    views = [(p['coordinates'][0][0][0], p['coordinates'][0][1][0]) for p in polygons(bounds)]
    return any(a <= d and b >= c for a, b in boxes for c, d in views)


def coordinate_fields(source, profile):
    fields = profile.get('fields', [])
    selected = {}
    for axis, pattern in [('latitude', r'^_?(latitude|lat)$'), ('longitude', r'^_?(longitude|lon|lng)$')]:
        explicit = source.get(axis + '_field')
        matches = [f for f in fields if f['type'] == 'number' and
                   (f['key'] == explicit if explicit else re.match(pattern, f.get('label', f['key']), re.I))]
        if len(matches) != 1:
            if explicit:
                raise ValueError('Choose valid numeric coordinate columns.')
            return None
        selected['lat_field' if axis == 'latitude' else 'lon_field'] = matches[0]['key']
    return selected


def table_selection(source, db, state, profile):
    bounds = extent(state)
    area = state.get('area') if not bounds else None
    if not bounds and not area:
        return {}, 'configured'
    areas = polygons(bounds) if bounds else [area]
    if source['kind'] == 'geojson':
        from .calculations import node
        ids = node({'operation': 'intersects', 'path': str(Path(db).parent / 'geometry.json'), 'areas': areas})
        return {'row_ids': ids}, 'entities'
    coordinates = coordinate_fields(source, profile)
    if not coordinates:
        return {}, 'unfiltered'
    if bounds:
        return {'bounds': bounds, 'coordinates': coordinates}, 'observations'
    # A drawn polygon uses the same intersection routine as local previews.
    # Read only typed coordinates; the temporary file never accepts a client path.
    import json
    import tempfile
    from ..engine import _open_generation, _quote, _ROW_KEY
    from .calculations import node
    connection, _ = _open_generation(db)
    try:
        rows = connection.execute('SELECT %s,%s,%s FROM data' % tuple(_quote(k) for k in
                                  (_ROW_KEY, coordinates['lon_field'], coordinates['lat_field']))).fetchall()
    finally:
        connection.close()
    with tempfile.TemporaryDirectory(prefix='dashboard-geometry-') as folder:
        path = Path(folder) / 'points.json'
        path.write_text(json.dumps({'type': 'FeatureCollection', 'features': [
            {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [lon, lat]} if lon is not None and lat is not None and -180 <= lon <= 180 and -90 <= lat <= 90 else None}
            for _, lon, lat in rows]}))
        selected = node({'operation': 'intersects', 'path': str(path), 'areas': areas})
    return {'row_ids': [rows[i][0] for i in selected]}, 'observations'
