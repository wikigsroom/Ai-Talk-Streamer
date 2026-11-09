"""Reuse pure calculations only within one immutable native observation.

Identity keys retain their objects, so a replaced state cannot reuse an id.
Context-local scopes never share entries between packets or bridge threads.
"""
from contextlib import contextmanager
from contextvars import ContextVar

_current = ContextVar('isaac_observation_cache', default=None)
_LIMIT = 2048


@contextmanager
def observation_scope():
    token = _current.set({})
    try:
        yield
    finally:
        _current.reset(token)


def observation_memo(namespace, objects, arguments, compute):
    cache = _current.get()
    if cache is None:
        return compute()
    key = (namespace, tuple(id(obj) for obj in objects), arguments)
    entry = cache.get(key)
    if entry is not None:
        return entry[1]
    result = compute()
    if len(cache) < _LIMIT:
        cache[key] = (objects, result)
    return result
