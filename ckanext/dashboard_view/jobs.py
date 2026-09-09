"""RQ entry points. Actor identity is stored; credentials are never serialized."""
import logging
import os
import traceback
import uuid

from . import service
from .security import SourceError, authorize_resource

log = logging.getLogger(__name__)


def _failure(exc):
    import ckan.plugins.toolkit as tk
    if isinstance(exc, (tk.NotAuthorized, tk.ObjectNotFound)):
        return {'status': 'error', 'code': 'access_denied',
                'message': 'The source is unavailable or you no longer have permission to download it.'}
    if isinstance(exc, SourceError):
        return {'status': 'error', 'code': exc.code, 'message': str(exc)[:500]}
    if isinstance(exc, ValueError):
        return {'status': 'error', 'code': 'invalid_data', 'message': str(exc)[:500]}
    # Log the exception type, not source URLs, signed credentials or SQL values.
    frames = traceback.extract_tb(exc.__traceback__)
    location = '%s:%s' % (os.path.basename(frames[-1].filename), frames[-1].lineno) if frames else 'unknown'
    log.error('Dashboard processing failed (%s at %s)', type(exc).__name__, location)
    return {'status': 'error', 'code': 'processing_failed',
            'message': 'Dashboard processing failed. Check the source or try refreshing it.'}


def build_source(work_key, claim, **kwargs):
    try:
        result = service.build(**kwargs)
    except Exception as exc:
        result = _failure(exc)
    if result['status'] == 'error' and result.get('code') not in ('source_temporarily_unavailable', 'queue_unavailable', 'job_interrupted'):
        service.invalidate_generation(kwargs['cache_key'], result['code'])
    service.finish_work(work_key, claim, result, ttl=30 if result['status'] == 'error' else None)
    try:
        service.cleanup()
    except OSError:
        log.warning('Some expired dashboard cache files could not be removed')
    return result['status']


def execute_query(resource_id, actor, cache_key, generation, config, filters,
                  bounds, pages, export, expected_stamp, work_key, claim):
    temporary = None
    try:
        from .engine import export_csv, query_table
        resource, _ = authorize_resource(resource_id, actor)
        if service.resource_stamp(resource) != expected_stamp:
            raise SourceError('The source changed. Refresh the dashboard.')
        cached = service.current_generation(cache_key)
        if not cached or cached[0]['generation'] != generation or cached[0].get('blocked'):
            raise SourceError('The source was updated. Please retry the dashboard.')
        manifest, _, directory = cached
        if export:
            target = service.export_path(work_key)
            target.parent.mkdir(mode=0o700, exist_ok=True)
            temporary = target.with_name('.%s.%s.tmp' % (target.name, uuid.uuid4().hex))
            size = 0
            with open(temporary, 'xb') as stream:
                os.chmod(temporary, 0o600)
                for chunk in export_csv(str(directory / 'table.duckdb'), config, filters=filters, bounds=bounds):
                    size += len(chunk)
                    if size > service.setting('max_export_bytes'):
                        raise SourceError('This CSV export exceeds the configured export limit. Apply more filters.')
                    stream.write(chunk)
            fresh, _ = authorize_resource(resource_id, actor)
            if service.resource_stamp(fresh) != expected_stamp:
                raise SourceError('The source changed. Please retry the export.')
            os.replace(temporary, target)
            result = {'status': 'ready', 'export_key': work_key, 'generation': generation,
                      'updated_at': manifest['updated_at']}
        else:
            result = query_table(str(directory / 'table.duckdb'), config, filters=filters,
                                 bounds=bounds, pages=pages)
            fresh, _ = authorize_resource(resource_id, actor)
            if service.resource_stamp(fresh) != expected_stamp:
                raise SourceError('The source changed. Please retry the dashboard.')
            result.update(status='ready', generation=generation, updated_at=manifest['updated_at'])
        service.finish_work(work_key, claim, result)
    except Exception as exc:
        result = _failure(exc)
        if type(exc).__module__ in ('duckdb', '_duckdb') and type(exc).__name__ in ('IOException', 'FatalException', 'InternalException', 'CatalogException'):
            service.invalidate_generation(cache_key, 'cache_corrupt', generation)
            result = {'status': 'error', 'code': 'cache_corrupt', 'message': 'The prepared data needs rebuilding. Refresh the dashboard to recover it.'}
        service.finish_work(work_key, claim, result, ttl=30)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def remove_expired_cache():
    service.cleanup()
