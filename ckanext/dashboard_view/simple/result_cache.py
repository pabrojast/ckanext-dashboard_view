"""Camera-dependent results expire; source generations remain reusable."""
import json
import time
from .. import service
from . import store


def transient(state):
    return (state.get('spatial') or {}).get('mode') in ('viewport', 'fixed')


def cached(key, state):
    if not transient(state):
        return store.cached(key)
    value = service.redis_connection().get('simple-dashboard:extent:' + key)
    return tuple(json.loads(value)) if value else (None, 0)


def put(key, value, state):
    if not transient(state):
        return store.put(key, value)
    service.redis_connection().setex('simple-dashboard:extent:' + key, 3600,
                                    json.dumps([value, time.time()], allow_nan=False))
