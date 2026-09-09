"""Add a clearly labelled synthetic dashboard to this run's dev QA dataset."""
import argparse
import json
from pathlib import Path

import requests

from dev_server import initial_config, make_data, SOURCE
from http_smoke import action, poll


def main(args):
    report = json.loads(Path(args.report).read_text())
    base = report['base']
    if base != 'https://data.dev-wins.com':
        raise SystemExit('This script only publishes the authorized dev example.')
    session = requests.Session()
    session.headers['Authorization'] = Path(args.token_file).read_text().strip()
    package = action(session, base, 'package_show', {'id': report['package_id']})
    if not package['name'].startswith('dashboard-qa-'):
        raise SystemExit('Expected the isolated Dashboard Builder QA dataset.')
    if not SOURCE.exists():
        make_data()
    config = initial_config()
    config['widgets'].append({
        'id': 'about', 'type': 'text', 'title': 'Datos de demostración',
        'x': 6, 'y': 0, 'w': 6, 'h': 2,
        'text': 'Observaciones sintéticas para explorar los filtros, gráficos y mapa. '
                'Estos datos no representan mediciones científicas reales.',
    })
    with SOURCE.open('rb') as source:
        resource = action(session, base, 'resource_create', {
            'package_id': package['id'], 'format': 'CSV',
            'name': 'Water quality explorer — synthetic demo',
            'description': '20,000 synthetic observations, six countries, 2024–2025. '
                           'For demonstration only; these are not research measurements.',
        }, files={'upload': ('citizen-science-demo.csv', source, 'text/csv')})
    views = action(session, base, 'resource_view_list', {'id': resource['id']})
    assert not any(v['view_type'] == 'dashboard_view' for v in views)
    view = action(session, base, 'resource_view_create', {
        'resource_id': resource['id'], 'view_type': 'dashboard_view',
        'title': 'Agua y ciencia ciudadana · Demo',
        'description': 'Interactive dashboard with clearly labelled synthetic data.',
        'dashboard_config': json.dumps(config),
    })
    # Validate the publicly embedded data path, without the administrative token.
    anonymous = requests.Session()
    api = base + '/dashboard-api/resource/' + resource['id']
    result = poll(anonymous, api + '/query', {'view_id': view['id']}).json()
    assert result['rows'] == 20000 and result['results']['records']['value'] == 20000
    assert 4 < result['results']['median']['value'] < 5
    assert all('error' not in block for block in result['results'].values())
    demo = {'resource_id': resource['id'], 'view_id': view['id'],
            'rows': result['rows'], 'median': result['results']['median']['value'],
            'dashboard_url': base + '/dashboard/' + view['id'],
            'embed_url': base + '/dashboard/' + view['id'] + '/embed',
            'resource_url': base + '/dataset/' + package['name'] + '/resource/' + resource['id']}
    Path(args.output).write_text(json.dumps(demo, ensure_ascii=False, indent=2))
    print(json.dumps(demo, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', default='output/http/data.dev-wins.com.json')
    parser.add_argument('--token-file', required=True)
    parser.add_argument('--output', default='output/http/dev-demo.json')
    main(parser.parse_args())
