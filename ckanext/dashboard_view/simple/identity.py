"""Recheck account state, including cookies and queued jobs predating revocation."""
import sqlalchemy as sa


def active_user(actor):
    if not actor:
        return None
    from ckan import model
    # Query current database state rather than a cached ORM/g.user identity.
    return model.Session.query(model.User).populate_existing().filter(
        sa.or_(model.User.name == actor, model.User.id == actor),
        model.User.state == 'active').first()
