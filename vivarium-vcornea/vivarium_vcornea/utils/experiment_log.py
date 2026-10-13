"""Cross-run experiment log: one append-only CSV row per replicate attempt.

Several writers share one log: every replicate of a batch, every worker
subprocess of a parameter sweep, and the GUI recording cancellations. The log is
therefore append-only with a FIXED column set (variable per-run columns cannot be
appended safely) and every append happens under a lock file, so concurrent
writers cannot interleave rows or overwrite each other.

A log whose header differs from FIELDS (written by an older version) is renamed
aside rather than rewritten, so no earlier record is ever lost.
"""
import csv
import json
import os
import time
from datetime import datetime
from pathlib import Path

LOG_NAME = "experiment_log.csv"

FIELDS = [
    'run_id', 'run_name', 'replicate_id', 'total_replicates', 'status',
    'simulation_success', 'exit_code', 'timed_out', 'random_seed',
    'random_seed_origin', 'created_at', 'completed_at', 'duration_seconds',
    'sim_time', 'has_injury', 'injury_type', 'healing_time',
    'parameters_changed', 'parameter_changes', 'output_directory',
    'omex_archive', 'error_message',
]

_LOCK_TIMEOUT_S = 30.0
_LOCK_STALE_S = 120.0


def row_from_run_metadata(run_metadata, output_directory=None):
    """Flatten a replicate's run_metadata.json into one log row."""
    cfg = run_metadata.get('simulation_config') or {}
    changes = run_metadata.get('parameter_changes') or {}
    return {
        'run_id': run_metadata.get('run_id'),
        'run_name': run_metadata.get('run_name'),
        'replicate_id': run_metadata.get('replicate_id'),
        'total_replicates': run_metadata.get('total_replicates'),
        'status': run_metadata.get('simulation_status'),
        'simulation_success': run_metadata.get('simulation_success'),
        'exit_code': run_metadata.get('exit_code'),
        'timed_out': run_metadata.get('timed_out'),
        'random_seed': run_metadata.get('random_seed'),
        'random_seed_origin': run_metadata.get('random_seed_origin'),
        'created_at': run_metadata.get('created_at'),
        'completed_at': run_metadata.get('simulation_completed_at'),
        'duration_seconds': run_metadata.get('duration_seconds'),
        'sim_time': cfg.get('sim_time'),
        'has_injury': cfg.get('has_injury'),
        'injury_type': cfg.get('injury_type'),
        'healing_time': run_metadata.get('healing_time'),
        'parameters_changed': run_metadata.get('parameters_changed'),
        'parameter_changes': json.dumps(
            {k: v.get('current_value') if isinstance(v, dict) else v
             for k, v in changes.items()}, default=str, sort_keys=True),
        'output_directory': output_directory,
        'omex_archive': run_metadata.get('omex_archive'),
        'error_message': run_metadata.get('error_message'),
    }


def append_rows(log_dir, rows):
    """Append rows (dicts keyed by FIELDS; extra keys ignored) to the log."""
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / LOG_NAME
    with _locked(log_dir / (LOG_NAME + ".lock")):
        _set_aside_if_foreign(log_file)
        new_file = not log_file.exists()
        with open(log_file, 'a', newline='', encoding='utf-8') as fh:
            writer = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction='ignore')
            if new_file:
                writer.writeheader()
            for row in rows:
                writer.writerow({k: ('' if row.get(k) is None else row.get(k))
                                 for k in FIELDS})
    return log_file


def _set_aside_if_foreign(log_file):
    if not log_file.exists():
        return
    try:
        with open(log_file, newline='', encoding='utf-8') as fh:
            header = next(csv.reader(fh), None)
    except Exception:
        header = None
    if header == FIELDS:
        return
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    log_file.rename(log_file.with_name(f"experiment_log.legacy-{stamp}.csv"))


class _locked:
    """Exclusive lock via atomic lock-file creation (works across processes and
    on Windows without extra dependencies). A lock older than _LOCK_STALE_S is
    assumed to belong to a crashed writer and is broken."""

    def __init__(self, path):
        self.path = Path(path)

    def __enter__(self):
        deadline = time.monotonic() + _LOCK_TIMEOUT_S
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return self
            except (FileExistsError, PermissionError):
                # Windows reports PermissionError while another writer's lock
                # file is being deleted: contention, not a real failure.
                try:
                    if time.time() - self.path.stat().st_mtime > _LOCK_STALE_S:
                        self.path.unlink()
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() > deadline:
                    raise TimeoutError(f"could not acquire {self.path}")
                time.sleep(0.05)

    def __exit__(self, *exc):
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        return False
