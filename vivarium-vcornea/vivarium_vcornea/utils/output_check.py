"""Did a V-Cornea run complete, and did it deliver the outputs it was asked for?

A zero exit code is not evidence of a completed simulation: CompuCell3D can exit
cleanly after failing at start-up. Completion is therefore established from what
the run left behind, and judged against the outputs the RESOLVED configuration
requested, not against any one of them:

* The model writes each end-of-run table once, at the final step, and stamps the
  file name with that step (`cell_count_<SimTime+1>.csv`, ...). A table carrying
  the final step in its name is evidence the simulation reached its end. A table
  stamped with another step is not.
* Each table is switched by its own parameter (CellCount, ThicknessPlot,
  SurfactantTracking). Only the tables whose switch is on are required; a run
  configured to record thickness alone is complete without a cell-count file.
* A required table must also follow its planned sampling schedule over the whole
  requested period (see END_OF_RUN_OUTPUTS): the hourly cell-count table must hold
  every hour from 0 to the end, the per-step surfactant table one row per step. A
  table with the right name and a truncated or gapped series does not pass, and a
  table that cannot be read does not pass.
* A table counts only if THIS launch wrote it. A run directory can already hold
  the tables of an earlier run (a rerun under the same name); a simulator that
  then exits cleanly without writing anything must not inherit them. Files last
  modified before the launch are reported as stale and ignored.
* When no end-of-run table was requested at all, the only evidence left is
  CompuCell3D's own end-of-run performance report on standard output.

Sampling facts, from the model's steppables (vCornea_v2Steppables.py): time is
recorded in hours (`mcs / HOURtoMCS`, HOURtoMCS = 10); cell counts are sampled
every HOURtoMCS steps, surfactant every step, thickness every HOURtoMCS steps
(a time point with no superficial cell leaves no thickness row, so the thickness
series is not required to reach the last hour).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

MCS_PER_HOUR = 10                      # HOURtoMCS in the model's steppables

# (switch parameter, output key, file pattern with {mcs}, series must reach the end?)
# (switch parameter, output key, file pattern with {mcs}, sampling schedule)
#   'hourly'      one row per simulated hour, Time = 0, 1, ..., final_mcs // MCS_PER_HOUR
#   'every_step'  one row per MCS, final_mcs + 1 rows, last Time = final_mcs / MCS_PER_HOUR
#   'sparse'      rows only at hours where there was something to record (a time
#                 point with no superficial cell leaves no thickness row), so the
#                 table must be readable and carry a Time column, nothing more
END_OF_RUN_OUTPUTS = (
    ('CellCount', 'cell_count', 'cell_count_{mcs}.csv', 'hourly'),
    ('ThicknessPlot', 'thickness', 'thickness_rep*_{mcs}.parquet', 'sparse'),
    ('SurfactantTracking', 'surfactant', 'surfactant_{mcs}.csv', 'every_step'),
)

# Printed by CompuCell3D when a simulation run ends.
CC3D_END_OF_RUN_MARKER = 'PERFORMANCE REPORT'


# File-system timestamps are coarser than the clock on some volumes; a table
# written right at launch must not be mistaken for a stale one.
_MTIME_TOLERANCE_S = 2.0


def _final_stamped(output_dir: Path, pattern: str, final_mcs: int,
                   not_before: Optional[float] = None):
    """(fresh, stale) files of one output stamped with the final step. The model
    stamps SimTime + 1; SimTime itself is accepted too. With `not_before` (the
    launch time, seconds since the epoch), files last modified earlier are stale:
    they belong to a previous run in the same directory."""
    fresh: List[Path] = []
    stale: List[Path] = []
    for mcs in (final_mcs + 1, final_mcs):
        for path in sorted(output_dir.glob(pattern.format(mcs=mcs))):
            try:
                old = (not_before is not None
                       and path.stat().st_mtime < not_before - _MTIME_TOLERANCE_S)
            except OSError:
                old = True
            (stale if old else fresh).append(path)
    return fresh, stale


def _read_table(path: Path):
    import pandas as pd
    return pd.read_parquet(path) if path.suffix == '.parquet' else pd.read_csv(path)


def _schedule_finding(schedule: str, df, final_mcs: int):
    """Compare a table with its planned sampling schedule.

    Returns (state, last_time_hours, n_rows, detail): state is 'complete',
    'truncated' (the series stops before the end of the requested period),
    'incomplete' (samples are missing inside it) or 'unreadable' (no Time column).
    """
    if 'Time' not in df.columns:
        return 'unreadable', None, len(df), "has no Time column"
    n = len(df)
    last = float(df['Time'].max()) if n else None
    expected_last = float(final_mcs // MCS_PER_HOUR)
    if schedule == 'sparse':
        return 'complete', last, n, None
    if last is None or last < expected_last - 1e-9:
        return ('truncated', last, n,
                "ends at " + ("no sample" if last is None else f"{last:g} h")
                + f", before the end of the requested period ({expected_last:g} h)")
    if schedule == 'hourly':
        planned = int(final_mcs // MCS_PER_HOUR) + 1
        have = {round(float(t), 6) for t in df['Time']}
        missing = [h for h in range(planned) if float(h) not in have]
        if missing:
            return ('incomplete', last, n,
                    f"has {planned - len(missing)} of the {planned} planned hourly samples "
                    f"(first missing at {missing[0]} h)")
    elif schedule == 'every_step':
        planned = int(final_mcs) + 1
        if n < planned:
            return ('incomplete', last, n,
                    f"has {n} of the {planned} planned per-step samples")
    return 'complete', last, n, None


def cc3d_reported_end_of_run(stdout_log) -> bool:
    try:
        return CC3D_END_OF_RUN_MARKER in Path(stdout_log).read_text(errors='replace')
    except Exception:
        return False


def check_requested_outputs(output_dir, sim_params: Dict[str, Any], final_mcs: int,
                            stdout_log=None,
                            not_before: Optional[float] = None) -> Dict[str, Any]:
    """Compare what a run left in output_dir with what its configuration requested.

    sim_params: the resolved parameters of THIS replicate. A switch that is absent
    counts as on, which is the model's own default. final_mcs: SimTime in MCS.
    not_before: when this replicate was launched (seconds since the epoch); tables
    last modified before it are left over from an earlier run and do not count.

    Returns a JSON-serialisable record:
      ok                   True when the run is shown to have completed and every
                           requested output is present and covers the run
      completion_evidence  'end_of_run_output' | 'cc3d_end_of_run_report' | None
      final_mcs, expected_last_time_hours, cc3d_end_of_run_report
      outputs              one entry per end-of-run output: switch, requested,
                           state ('complete' | 'missing' | 'truncated' |
                           'incomplete' | 'unreadable' | 'not requested'), file, last_time_hours,
                           detail, and stale_files when tables from before the
                           launch were found and ignored
      problems             human-readable reasons, empty when ok
    """
    output_dir = Path(output_dir)
    expected_last = float(final_mcs // MCS_PER_HOUR)
    entries, problems = [], []
    reached_end = False

    for switch, key, pattern, schedule in END_OF_RUN_OUTPUTS:
        requested = bool(sim_params.get(switch, True))
        entry = {'output': key, 'switch': switch, 'requested': requested,
                 'state': 'not requested', 'file': None, 'last_time_hours': None,
                 'detail': None}
        entries.append(entry)
        files, stale = _final_stamped(output_dir, pattern, final_mcs, not_before)
        if stale:
            entry['stale_files'] = [p.name for p in stale]
        if files:
            # Stamped with the final step, so written at the final step —
            # whether or not this output was the one asked for.
            reached_end = True
            entry['file'] = files[0].name
        if not requested:
            continue
        if not files:
            stale_names = {p.name for p in stale}
            others = sorted(p.name for p in output_dir.glob(pattern.format(mcs='*'))
                            if p.name not in stale_names)
            entry['state'] = 'missing'
            entry['detail'] = (f"{switch} is on, but no {pattern.format(mcs=final_mcs + 1)} "
                               f"was written"
                               + (f" by this run ({', '.join(sorted(stale_names))} was already "
                                  f"in the directory before launch and is ignored)"
                                  if stale else "")
                               + (f" (found {', '.join(others)}, stamped with a different "
                                  f"step)" if others else ""))
            problems.append(entry['detail'])
            continue
        try:
            table = _read_table(files[0])
        except ImportError as e:
            # No parquet engine in this environment: the table exists and carries
            # the final step in its name; its contents are not judged.
            entry['state'] = 'complete'
            entry['detail'] = f"contents not read ({e})"
            continue
        except Exception as e:  # noqa: BLE001
            entry['state'] = 'unreadable'
            entry['detail'] = f"{files[0].name} could not be read: {e}"
            problems.append(entry['detail'])
            continue
        state, last, n_rows, detail = _schedule_finding(schedule, table, final_mcs)
        entry.update(state=state, last_time_hours=last, n_rows=n_rows, schedule=schedule)
        if state != 'complete':
            entry['detail'] = f"{files[0].name} {detail}"
            problems.append(entry['detail'])

    end_report = cc3d_reported_end_of_run(stdout_log) if stdout_log is not None else False
    any_requested = any(e['requested'] for e in entries)
    if reached_end:
        evidence = 'end_of_run_output'
    elif not any_requested and end_report:
        evidence = 'cc3d_end_of_run_report'
    else:
        evidence = None
        if not any_requested:
            problems.append(
                "no end-of-run output was requested (CellCount, ThicknessPlot and "
                "SurfactantTracking are all off) and CompuCell3D printed no end-of-run "
                "report, so nothing shows that the simulation ran")

    return {
        'ok': evidence is not None and not problems,
        'completion_evidence': evidence,
        'final_mcs': int(final_mcs),
        'expected_last_time_hours': expected_last,
        'cc3d_end_of_run_report': end_report,
        'outputs': entries,
        'problems': problems,
    }
