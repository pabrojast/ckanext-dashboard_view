import click


@click.group()
def dashboard():
    """Dashboard preparation, query workers and cache maintenance."""


@dashboard.command()
@click.option('--queue', type=click.Choice(['build', 'query', 'simple']), required=True)
@click.option('--burst', is_flag=True, help='Exit when this queue is empty.')
def worker(queue, burst):
    """Process one job at a time in a supervised, separate worker process."""
    from .worker import run, DashboardWorker
    if queue == 'simple':
        DashboardWorker(['simple-dashboard']).work(burst=burst)
    else:
        run(queue=queue, burst=burst)


@dashboard.command('prune-cache')
def prune_cache():
    """Remove obsolete generations and exports older than one day."""
    from .service import cleanup
    cleanup()
    click.echo('Expired dashboard cache files removed.')


def get_commands():
    return [dashboard]


@dashboard.command('simple-init-db')
def simple_init_db():
    """Create native dashboard tables without changing existing resource views."""
    from .simple.store import init_db
    init_db()
    click.echo('Simple dashboard schema ready.')
