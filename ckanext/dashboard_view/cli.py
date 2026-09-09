import click


@click.group()
def dashboard():
    """Dashboard preparation, query workers and cache maintenance."""


@dashboard.command()
@click.option('--queue', type=click.Choice(['build', 'query']), required=True)
@click.option('--burst', is_flag=True, help='Exit when this queue is empty.')
def worker(queue, burst):
    """Process one job at a time in a supervised, separate worker process."""
    from .worker import run
    run(queue=queue, burst=burst)


@dashboard.command('prune-cache')
def prune_cache():
    """Remove obsolete generations and exports older than one day."""
    from .service import cleanup
    cleanup()
    click.echo('Expired dashboard cache files removed.')


def get_commands():
    return [dashboard]
