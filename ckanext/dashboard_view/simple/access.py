"""Visibility gates are evaluated before and after every cached query."""
from . import store
from . import sources


def owner(item, actor):
    import ckan.model as model
    user = model.User.get(actor) if actor else None
    return bool(user and (item['owner'] == actor or user.sysadmin))


def read(dashboard_id, actor='', revision=None):
    item = store.get(dashboard_id, revision)
    if not owner(item, actor):
        if revision is None and item['published_revision']:
            item = store.get(dashboard_id, item['published_revision'])
        if not item['published_revision'] or not item['published']:
            raise PermissionError('This dashboard is private.')
        sources.authorize_all(item['config'], public=True)
        item['title'] = item['config']['title']
    sources.authorize_all(item['config'], actor)
    return item


def edit(dashboard_id, actor):
    item = store.get(dashboard_id)
    if not owner(item, actor):
        raise PermissionError('Only the dashboard owner can edit it.')
    return item
