"""Dedicated RQ workers inherit the CKAN initialized by its CLI exactly once."""
from ckan.lib.jobs import Worker
from rq import Worker as RQWorker


class DashboardWorker(Worker):
    def main_work_horse(self, job, queue):
        # CKAN's base worker disposes DB connections before fork and cleans the
        # child's session afterward. Avoid its second load_environment call.
        return RQWorker.main_work_horse(self, job, queue)


def run(queue='build', burst=False):
    from .service import setting
    DashboardWorker([setting('queue_' + queue)]).work(burst=burst)
