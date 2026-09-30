"""Interrupting a run must not leave worker processes behind (edison/pool.py)."""
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TAG = "pooltest"


def _children(pid: int) -> list[int]:
    out = subprocess.run(["pgrep", "-P", str(pid)], capture_output=True, text=True).stdout
    return [int(x) for x in out.split()]


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM], ids=["ctrl-c", "sigterm"])
def test_interrupted_run_leaves_no_workers(sig):
    run = subprocess.Popen([sys.executable, "-m", "edison.pilot_eval", "--profile", "lightsworn",
                            "--duels", "400", "--workers", "2", "--tag", TAG], cwd=ROOT,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + 60
        workers: list[int] = []
        while time.time() < deadline and len(workers) < 2:   # both workers spawned (plus any helper)
            time.sleep(0.5)
            workers = _children(run.pid)
        assert len(workers) >= 2, "the run never started its workers"
        time.sleep(2)                                        # let them get into duels
        workers = _children(run.pid)
        run.send_signal(sig)
        run.wait(timeout=60)
        deadline = time.time() + 15
        while time.time() < deadline and any(_alive(p) for p in workers):
            time.sleep(0.25)
        survivors = [p for p in workers if _alive(p)]
        assert not survivors, f"worker processes survived the interrupt: {survivors}"
    finally:
        if run.poll() is None:
            run.kill()
        for p in _children(run.pid):
            os.kill(p, signal.SIGKILL)
        shutil.rmtree(ROOT / "runs" / f"lightsworn-{TAG}", ignore_errors=True)
