"""The provenance record's git queries cannot stall a run or lock the repository.

A run records its code version through a handful of git queries. Two failure
modes of the earlier implementation are excluded here, in both packages:
a query that outlives its timeout must not be waited on without limit, and no
query may take .git/index.lock (a `git status` killed at the timeout left the
lock behind, which then blocked commits).

    conda run -n vc --no-capture-output pytest tests/test_provenance_git.py -v
"""
import importlib
import subprocess
import time

import pytest

MODULES = ('vivarium_angio.utils.provenance', 'vivarium_vcornea.utils.provenance')


@pytest.fixture(params=MODULES)
def prov(request):
    return importlib.import_module(request.param)


class _NeverAnswers:
    """A git that is still running at every timeout and never releases its pipe."""
    returncode = None
    stdout = None

    def __init__(self):
        self.killed, self.waits = False, []

    def communicate(self, timeout=None):
        self.waits.append(timeout)
        raise subprocess.TimeoutExpired('git', timeout)

    def kill(self):
        self.killed = True


def test_a_git_query_that_never_returns_is_given_up_not_waited_for(prov, monkeypatch, tmp_path):
    made = []
    monkeypatch.setattr(prov.subprocess, 'Popen',
                        lambda *a, **k: made.append(_NeverAnswers()) or made[-1])
    started = time.monotonic()
    assert prov._run_git(['status', '--porcelain'], tmp_path) is None
    assert time.monotonic() - started < 1
    [git] = made
    assert git.killed
    # Every wait had a limit: the query's own timeout, then the short wait after the kill.
    assert git.waits == [prov._GIT_TIMEOUT_S, prov._GIT_KILL_WAIT_S]
    assert all(w is not None for w in git.waits)


def test_git_queries_are_read_only_and_take_no_input(prov, monkeypatch, tmp_path):
    seen = {}

    class Answers:
        returncode = 0
        stdout = None

        def communicate(self, timeout=None):
            return 'abc123\n', None

    def popen(cmd, **kwargs):
        seen['cmd'], seen['kwargs'] = cmd, kwargs
        return Answers()
    monkeypatch.setattr(prov.subprocess, 'Popen', popen)
    assert prov._run_git(['rev-parse', 'HEAD'], tmp_path) == 'abc123'
    assert seen['cmd'][:2] == ['git', '--no-optional-locks']
    assert seen['kwargs']['stdin'] == subprocess.DEVNULL


def test_the_real_queries_leave_no_index_lock_behind(prov):
    from pathlib import Path
    here = Path(prov.__file__).resolve().parent
    top = prov._run_git(['rev-parse', '--show-toplevel'], here)
    if not top:
        pytest.skip('not a git checkout')
    lock = Path(top) / '.git' / 'index.lock'
    existed = lock.exists()
    assert prov._run_git(['status', '--porcelain', '--untracked-files=no'], here, allow_empty=True) is not None
    assert lock.exists() == existed
