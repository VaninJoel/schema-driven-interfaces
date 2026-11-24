"""Will the files of a run fit in a Windows path?

Windows refuses a path of 260 characters or more unless long paths are switched
on for the machine. A V-Cornea replicate copies the model project into its own
run directory, and the run directory's name is built from the changed
parameters, so a deep output folder can push the copy over the limit. The copy
then fails half-way with "No such file or directory" for a file that exists,
which says nothing about the cause.

This check runs before any directory is created. It works out the longest path
the run is known to create and, if that does not fit, refuses the run with the
number of characters by which the output folder has to be shortened.

Counted: every file of the model project inside the replicate's working copy
(`<output folder>/<run name>/replicate_<n>/vcornea_sim_<6 hex>/...`) and the
run's archive (`.../replicate_<n>/<run name>.omex`). Not counted: files that
CompuCell3D or Python may add on their own (bytecode caches, screenshots);
`MARGIN` leaves room for those.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

WINDOWS_MAX_PATH = 260            # includes the terminating NUL: 259 usable characters
MARGIN = 12                       # head-room for files not counted here
_WORKING_COPY_NAME_LENGTH = len('vcornea_sim_') + 6


class OutputPathTooLong(ValueError):
    """The run was refused because its files would not fit in a Windows path.
    `.record` holds the numbers (see `path_budget`)."""

    def __init__(self, message, record):
        super().__init__(message)
        self.record = record


def windows_long_paths_enabled() -> bool:
    """True when this machine has Windows long-path support switched on."""
    if os.name != 'nt':
        return True
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r'SYSTEM\CurrentControlSet\Control\FileSystem') as key:
            return int(winreg.QueryValueEx(key, 'LongPathsEnabled')[0]) == 1
    except Exception:
        return False


def limit_applies() -> bool:
    """Whether the 260-character limit holds for runs started here."""
    return os.name == 'nt' and not windows_long_paths_enabled()


def _longest_project_file(project_path) -> str:
    project = Path(project_path)
    longest = ''
    if project.is_dir():
        for f in project.rglob('*'):
            if f.is_file() and '__pycache__' not in f.parts:
                rel = str(f.relative_to(project))
                if len(rel) > len(longest):
                    longest = rel
    return longest


def path_budget(output_base, run_name: str, project_path, n_replicates: int = 1,
                limit: int = WINDOWS_MAX_PATH - 1) -> Dict[str, Any]:
    """The longest path a run will create, against the limit.

    Returns {'longest_path', 'length', 'limit', 'margin', 'fits', 'excess',
    'output_folder', 'output_folder_length', 'run_name_length'}; `excess` is the
    number of characters by which the output folder must be shortened (0 when
    the run fits, margin included)."""
    base = Path(os.path.abspath(str(output_base)))
    replicate = base / run_name / f'replicate_{max(int(n_replicates), 1)}'
    candidates = [
        replicate / ('vcornea_sim_' + 'x' * 6) / _longest_project_file(project_path),
        replicate / f'{run_name}.omex',
    ]
    longest = max(candidates, key=lambda p: len(str(p)))
    length = len(str(longest))
    excess = max(0, length + MARGIN - limit)
    return {
        'longest_path': str(longest), 'length': length, 'limit': limit, 'margin': MARGIN,
        'fits': excess == 0, 'excess': excess,
        'output_folder': str(base), 'output_folder_length': len(str(base)),
        'run_name_length': len(run_name),
    }


def require_path_budget(output_base, run_name: str, project_path, n_replicates: int = 1,
                        enforce: Optional[bool] = None) -> Dict[str, Any]:
    """Refuse (OutputPathTooLong) a run whose files would not fit; otherwise
    return the `path_budget` record. `enforce=None` applies the limit only where
    it holds (Windows without long-path support)."""
    record = path_budget(output_base, run_name, project_path, n_replicates)
    record['enforced'] = limit_applies() if enforce is None else bool(enforce)
    if record['enforced'] and not record['fits']:
        raise OutputPathTooLong(
            f"Run not started: its files would not fit in a Windows path. The longest "
            f"one would be {record['length']} characters "
            f"({record['longest_path']}); Windows allows {record['limit']}, and "
            f"{record['margin']} are kept free for files the simulator adds. Choose an "
            f"output folder whose path is at least {record['excess']} characters shorter "
            f"(it is now {record['output_folder_length']} characters: "
            f"{record['output_folder']}). The run name ({record['run_name_length']} "
            f"characters) is built from the changed parameters and appears twice in the "
            f"path, so changing fewer parameters in one run also shortens it. "
            f"Alternatively, switch on long-path support in Windows.",
            record)
    return record
