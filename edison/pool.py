"""A process pool whose workers never outlive the run, however it ends.

    from edison.pool import worker_pool
    with worker_pool(8, initializer=pilots.init, initargs=(variant,)) as pool:
        futures = [pool.submit(...)]

ProcessPoolExecutor's own context manager is not enough: on Ctrl+C its __exit__ waits for every queued
job (hundreds of duels), and if the parent is killed its workers are orphaned and keep burning CPU. Here:
  * workers ignore SIGINT - Ctrl+C reaches the whole process group, and the parent decides;
  * SIGTERM in the parent is turned into SystemExit, so the finally block below runs;
  * on any exit - normal, exception, Ctrl+C, SIGTERM - queued jobs are cancelled and every worker is
    terminated (then killed if it does not stop within a few seconds) in a finally block.
tests/test_pool.py interrupts a real run and checks that no worker survives.
"""
from __future__ import annotations

import multiprocessing as mp
import signal
import threading
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager


def _worker_init(initializer, initargs):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    if initializer is not None:
        initializer(*initargs)


def _exit_on_sigterm(signum, frame):
    raise SystemExit(128 + signum)


@contextmanager
def worker_pool(workers: int, initializer=None, initargs=()):
    pool = ProcessPoolExecutor(workers, mp_context=mp.get_context("spawn"), initializer=_worker_init,
                               initargs=(initializer, initargs))
    on_main = threading.current_thread() is threading.main_thread()
    old = signal.signal(signal.SIGTERM, _exit_on_sigterm) if on_main else None
    ok = False
    try:
        yield pool
        ok = True
    finally:
        procs = list((getattr(pool, "_processes", None) or {}).values())
        if ok:
            pool.shutdown(wait=True)
        else:
            pool.shutdown(wait=False, cancel_futures=True)
        for p in procs:
            if p.is_alive():
                p.terminate()
        for p in procs:
            p.join(timeout=5)
            if p.is_alive():
                p.kill()
                p.join(timeout=5)
        if on_main:
            signal.signal(signal.SIGTERM, old)
