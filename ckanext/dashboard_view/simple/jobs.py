"""One dedicated queue, persistent results and expiring Redis work claims."""
import tempfile
import time
import uuid
from .. import service
from ..security import SourceError
from . import store, sources, result_cache
from .schema import ENGINE_VERSION


def query(config, actor):
    resources = sources.authorize_all(config, actor)
    key = service.digest([ENGINE_VERSION, config, [service.resource_stamp(r) for r in resources]])
    previous, checked = result_cache.cached(key, config['state'])
    redis = service.redis_connection()
    lock = 'simple-dashboard:lock:' + key
    if time.time() - checked >= 300:
        claim = uuid.uuid4().hex
        if redis.set(lock, claim, nx=True, ex=1200):
            slot = 'simple-dashboard:actor:' + service.digest(actor or 'anonymous')
            reserved = redis.eval("redis.call('zremrangebyscore',KEYS[1],'-inf',ARGV[1]); if redis.call('zcard',KEYS[1]) >= 3 then return 0 end; redis.call('zadd',KEYS[1],ARGV[2],ARGV[3]); redis.call('expire',KEYS[1],1200); return 1", 1, slot, time.time(), time.time() + 1200, claim)
            if not reserved:
                release(redis, lock, claim)
                return {'status': 'pending', 'message': 'Waiting for your earlier calculations.'}
            try:
                from ckan.lib.jobs import enqueue
                enqueue(execute, kwargs=dict(key=key, config=config, actor=actor, claim=claim),
                    queue='simple-dashboard', title='Calculate simple dashboard',
                    rq_kwargs={'timeout': 900, 'result_ttl': 0, 'failure_ttl': 300, 'job_id': claim})
            except Exception:
                release(redis, lock, claim)
                redis.zrem(slot, claim)
                return {'status': 'stale' if previous and previous.get('results') else 'error',
                        **(previous or {}), 'error': 'Calculation queue unavailable. Please retry.'}
    pending = bool(redis.get(lock))
    sources.authorize_all(config, actor)
    if not previous:
        return {'status': 'pending', 'checked_at': None}
    return {**previous, 'checked_at': checked,
            'status': ('stale' if previous.get('results') else 'error') if previous.get('error') else 'stale' if pending else 'ready', 'refreshing': pending}


def release(redis, lock, claim):
    redis.eval("if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) end return 0", 1, lock, claim)


def execute(key, config, actor, claim):
    from .calculations import calculate
    redis = service.redis_connection()
    lock = 'simple-dashboard:lock:' + key
    try:
        with tempfile.TemporaryDirectory(prefix='simple-dashboard-') as directory:
            value = calculate(config, actor, directory)
    except Exception as exc:
        # Only transient source failures retain the previous valid calculation.
        previous, _ = result_cache.cached(key, config['state'])
        transient = isinstance(exc, SourceError) and exc.code == 'source_temporarily_unavailable'
        value = dict(previous or {}) if transient else {}
        value.update(error=str(exc) if isinstance(exc, (SourceError, ValueError)) else 'The source is unavailable or access has changed.')
    if redis.get(lock) in (claim, claim.encode()):
        result_cache.put(key, value, config['state'])
    release(redis, lock, claim)
    redis.zrem('simple-dashboard:actor:' + service.digest(actor or 'anonymous'), claim)
