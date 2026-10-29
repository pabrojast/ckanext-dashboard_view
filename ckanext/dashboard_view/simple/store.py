"""PostgreSQL persistence, immutable revisions and optimistic edit concurrency."""
import json
import time
import uuid
import sqlalchemy as sa

metadata = sa.MetaData()
dashboards = sa.Table('simple_dashboard', metadata,
    sa.Column('id', sa.String(36), primary_key=True),
    sa.Column('owner', sa.Unicode(100), nullable=False, index=True),
    sa.Column('title', sa.Unicode(200), nullable=False),
    sa.Column('revision', sa.Integer, nullable=False),
    sa.Column('published_revision', sa.Integer),
    sa.Column('deleted', sa.Boolean, nullable=False, default=False),
    sa.Column('updated_at', sa.Float, nullable=False))
revisions = sa.Table('simple_dashboard_revision', metadata,
    sa.Column('dashboard_id', sa.String(36), sa.ForeignKey('simple_dashboard.id'), primary_key=True),
    sa.Column('revision', sa.Integer, primary_key=True),
    sa.Column('config', sa.Text, nullable=False),
    sa.Column('published', sa.Boolean, nullable=False, default=False),
    sa.Column('created_at', sa.Float, nullable=False))
cache = sa.Table('simple_dashboard_result', metadata,
    sa.Column('key', sa.String(64), primary_key=True),
    sa.Column('value', sa.Text, nullable=False),
    sa.Column('checked_at', sa.Float, nullable=False))


def engine():
    from ckan import model
    return model.meta.engine


def init_db(bind=None):
    metadata.create_all(bind or engine())


def get(dashboard_id, revision=None):
    with engine().connect() as conn:
        row = conn.execute(sa.select(dashboards).where(sa.and_(dashboards.c.id == dashboard_id, dashboards.c.deleted == False))).mappings().first()  # noqa: E712
        if not row:
            raise LookupError('Dashboard not found.')
        item = dict(row)
        number = revision or item['revision']
        rev = conn.execute(sa.select(revisions).where(sa.and_(revisions.c.dashboard_id == dashboard_id, revisions.c.revision == number))).mappings().first()
        if not rev:
            raise LookupError('Dashboard revision not found.')
        item.update(config=json.loads(rev['config']), selected_revision=number, published=bool(rev['published']))
        return item


def listing(actor, public=False):
    with engine().connect() as conn:
        condition = dashboards.c.published_revision.isnot(None) if public else dashboards.c.owner == actor
        return [dict(row) for row in conn.execute(sa.select(dashboards).where(sa.and_(condition, dashboards.c.deleted == False)).order_by(dashboards.c.updated_at.desc()).limit(100)).mappings()]  # noqa: E712


def save(config, actor, dashboard_id=None, expected=None):
    now = time.time()
    with engine().begin() as conn:
        if dashboard_id:
            row = conn.execute(sa.select(dashboards).where(dashboards.c.id == dashboard_id).with_for_update()).mappings().first()
            if not row or row['deleted']:
                raise LookupError('Dashboard not found.')
            if expected != row['revision']:
                raise ValueError('This dashboard changed. Reopen it before saving a new revision.')
            number = row['revision'] + 1
            conn.execute(dashboards.update().where(dashboards.c.id == dashboard_id).values(title=config['title'], revision=number, updated_at=now))
        else:
            dashboard_id, number = str(uuid.uuid4()), 1
            conn.execute(dashboards.insert().values(id=dashboard_id, owner=actor, title=config['title'], revision=number, deleted=False, updated_at=now))
        conn.execute(revisions.insert().values(dashboard_id=dashboard_id, revision=number, config=json.dumps(config, allow_nan=False), published=False, created_at=now))
    return get(dashboard_id)


def visibility(dashboard_id, revision, publish):
    with engine().begin() as conn:
        conn.execute(dashboards.update().where(dashboards.c.id == dashboard_id).values(published_revision=revision if publish else None))
        condition = revisions.c.dashboard_id == dashboard_id
        if publish:
            condition = sa.and_(condition, revisions.c.revision == revision)
        conn.execute(revisions.update().where(condition).values(published=publish))


def delete(dashboard_id):
    with engine().begin() as conn:
        conn.execute(dashboards.update().where(dashboards.c.id == dashboard_id).values(deleted=True, published_revision=None))


def cached(key):
    with engine().connect() as conn:
        row = conn.execute(sa.select(cache).where(cache.c.key == key)).mappings().first()
        return (json.loads(row['value']), row['checked_at']) if row else (None, 0)


def put(key, value):
    # A unique request claim serializes writes for each key. Immutable block keys
    # may race across layouts: ON CONFLICT handles this without lost transactions.
    values = dict(key=key, value=json.dumps(value, allow_nan=False), checked_at=time.time())
    from sqlalchemy.dialects.postgresql import insert
    with engine().begin() as conn:
        if conn.dialect.name == 'postgresql':
            stmt = insert(cache).values(**values)
            conn.execute(stmt.on_conflict_do_update(index_elements=['key'], set_={k: v for k, v in values.items() if k != 'key'}))
        else:
            conn.execute(cache.delete().where(cache.c.key == key))
            conn.execute(cache.insert().values(**values))
