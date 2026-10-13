"""The cross-run experiment log is shared by concurrent writers (replicates,
sweep worker processes, GUI cancellation rows). It must never lose or
interleave rows, and must never rewrite an earlier log.

Run:  conda run -n vc --no-capture-output pytest vivarium-vcornea/test_experiment_log.py -v
"""
import csv
import subprocess
import sys
from pathlib import Path

from vivarium_vcornea.utils import experiment_log

WRITER = """
import sys
from vivarium_vcornea.utils.experiment_log import append_rows
for i in range(25):
    append_rows(sys.argv[1], [{'run_id': f'{sys.argv[2]}-{i}', 'status': 'success'}])
"""


def _rows(log_dir):
    with open(Path(log_dir) / experiment_log.LOG_NAME, newline='', encoding='utf-8') as fh:
        reader = csv.reader(fh)
        header = next(reader)
        return header, list(reader)


def test_concurrent_processes_lose_no_rows(tmp_path):
    procs = [subprocess.Popen([sys.executable, '-c', WRITER, str(tmp_path), f'w{n}'])
             for n in range(4)]
    assert all(p.wait(timeout=120) == 0 for p in procs)
    header, rows = _rows(tmp_path)
    assert header == experiment_log.FIELDS
    assert all(len(r) == len(experiment_log.FIELDS) for r in rows)
    assert sorted(r[0] for r in rows) == sorted(f'w{n}-{i}' for n in range(4) for i in range(25))
    assert not (tmp_path / (experiment_log.LOG_NAME + '.lock')).exists()


def test_legacy_log_is_set_aside_not_rewritten(tmp_path):
    legacy = tmp_path / experiment_log.LOG_NAME
    legacy.write_text("run_name,created_at,simulation_success\nold,2025-01-01,True\n")
    experiment_log.append_rows(tmp_path, [{'run_id': 'new'}])
    aside = list(tmp_path.glob('experiment_log.legacy-*.csv'))
    assert len(aside) == 1 and 'old,2025-01-01,True' in aside[0].read_text()
    header, rows = _rows(tmp_path)
    assert header == experiment_log.FIELDS and [r[0] for r in rows] == ['new']


def test_row_from_run_metadata_flattens_changes():
    row = experiment_log.row_from_run_metadata({
        'run_id': 'abc', 'simulation_status': 'timed_out', 'timed_out': True,
        'parameter_changes': {'SimTime': {'current_value': 5, 'default_value': 24}},
        'simulation_config': {'sim_time': 5},
    }, 'combo/replicate_1')
    assert row['status'] == 'timed_out' and row['sim_time'] == 5
    assert row['parameter_changes'] == '{"SimTime": 5}'
    assert set(row) == set(experiment_log.FIELDS)
