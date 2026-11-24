#!/usr/bin/env python
"""Run Angio-GUI experiments without a window: the program-facing path.

Executes a specification through the SAME machinery as the graphical interface —
the same schema check, per-run identity, logs, time-out handling, and a
status-typed COMBINE/OMEX archive for every outcome (success, failure, time-out).
Only the window is absent, so a specification saved from the GUI and one written
by a script are run and recorded identically.

    python run_headless.py --params my_parameters.json --out results
    python run_headless.py lchem=100,500,1000 sim_time=100 --replicates 10 --name sweep
    python run_headless.py vedir=12 --allow-inadmissible     # recorded with the run

A specification is the schema defaults, overlaid by the parameter file (JSON as
written by the GUI's "Save Parameters"), overlaid by key=value arguments. A
comma-separated list for a numeric parameter is a sweep over those values, as in
the GUI. Every run gets its own directory under <out>/<name>_<timestamp>/ and its
own random seed (a pinned `random_seed` applies to the first replicate only).

What is refused, and what needs a flag (see vivarium_angio/utils/spec_validation.py):
  * a key that is not a parameter, or a value of the wrong type  -> never runs
  * a value outside a declared implementation limit               -> runs only with
    --allow-inadmissible, and the permission is written into the run record
  * a value outside a documented working/recommended range        -> runs, recorded

Exit status: 0 if every run succeeded, 1 if any run failed or was refused, 2 for a
malformed command line or specification.
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import random
import subprocess
import sys
from datetime import datetime
from pathlib import Path

os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')     # QObject signals only; no display

HERE = Path(__file__).resolve().parent


def _worker_class():
    """The GUI's SimulationWorker, loaded by path under its own module name (the
    V-Cornea GUI has a `simulation_worker` module too, and both may be loaded in
    one process)."""
    import importlib.util
    name = 'angio_gui_simulation_worker'
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, HERE / 'gui' / 'simulation_worker.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name].SimulationWorker


def _typed(text, default):
    """One command-line or file value, converted to the type of the schema default."""
    if isinstance(default, bool):
        if str(text).strip().lower() in ('true', '1', 'yes'):
            return True
        if str(text).strip().lower() in ('false', '0', 'no'):
            return False
        return text
    if isinstance(default, int):
        try:
            number = float(text)
            return int(number) if number == int(number) else number
        except (TypeError, ValueError):
            return text
    if isinstance(default, float):
        try:
            return float(text)
        except (TypeError, ValueError):
            return text
    return text


def resolve_specification(schema_inputs, file_params=None, overrides=None):
    """(base parameters, sweep lists) from defaults + file + key=value overrides.

    Values are typed by the schema default; a value that cannot be converted is
    left as given so the specification check reports it instead of this function
    guessing. A comma-separated list for a numeric parameter becomes a sweep."""
    params = {k: v['_default'] for k, v in schema_inputs.items() if '_default' in v}
    given = dict(file_params or {})
    given.update(overrides or {})
    sweeps = {}
    for key, value in given.items():
        info = schema_inputs.get(key)
        if not isinstance(info, dict) or '_default' not in info:
            params[key] = value                      # not a schema parameter: checked later
            continue
        default = info['_default']
        numeric = isinstance(default, (int, float)) and not isinstance(default, bool)
        if numeric and isinstance(value, str) and ',' in value:
            sweeps[key] = [_typed(part.strip(), default) for part in value.split(',')
                           if part.strip()]
            params[key] = sweeps[key][0]
        elif isinstance(value, str):
            params[key] = _typed(value, default)
        else:
            params[key] = value
    return params, sweeps


def plan_runs(params, sweeps, replicates, name):
    """[(run name, run parameters)] with the GUI's naming and seed policy."""
    keys = list(sweeps)
    combos = [dict(zip(keys, values)) for values in itertools.product(*sweeps.values())] or [{}]
    seed_rng = random.SystemRandom()
    try:
        pinned = int(params.get('random_seed', -1))
    except (TypeError, ValueError):
        pinned = -1
    runs = []
    for c_idx, combo in enumerate(combos):
        for r_idx in range(replicates):
            if len(combos) > 1 and replicates > 1:
                run_name = f"{name}_combo{c_idx + 1:03d}_rep{r_idx + 1:02d}"
            elif len(combos) > 1:
                run_name = f"{name}_combo{c_idx + 1:03d}"
            elif replicates > 1:
                run_name = f"{name}_rep{r_idx + 1:02d}"
            else:
                run_name = name
            run = {**params, **combo, 'exp_name': run_name}
            if pinned >= 0 and r_idx == 0:
                run['random_seed'], run['random_seed_origin'] = pinned, 'explicit'
            else:
                run['random_seed'] = seed_rng.randrange(1, 2 ** 31 - 1)
                run['random_seed_origin'] = 'drawn'
            if len(combos) > 1 or replicates > 1:
                run['parent_experiment_id'] = name
                run['total_combinations'] = len(combos)
                run['total_replicates'] = replicates
            if len(combos) > 1:
                run['parameter_scan'] = {k: list(v) for k, v in sweeps.items()}
                run['scan_point'] = dict(combo)
                run['combination_index'] = c_idx + 1
            if replicates > 1:
                run['replicate_id'] = r_idx + 1
            runs.append((run_name, run))
    return runs


def run_specification(file_params=None, overrides=None, *, out_dir='experiments',
                      name=None, replicates=1, allow_inadmissible=False, report=True,
                      echo=print):
    """Run a specification headless. Returns (batch folder, [result per run]); each
    result is {'name', 'status', 'archive', 'error'}. A refused run is a result
    with status 'failed' and its own record and archive, like any other failure."""
    from vivarium_angio.processes.angiogenesis_process import AngiogenesisProcess
    from vivarium_angio.utils.parameter_audit import build_parameter_audit
    from vivarium_angio.utils.provenance import schema_fingerprint
    from vivarium_angio.utils.references import REFERENCES
    SimulationWorker = _worker_class()

    process = AngiogenesisProcess.__new__(AngiogenesisProcess)
    schema = process.ports_schema()
    fingerprint = schema_fingerprint(schema)
    params, sweeps = resolve_specification(schema['inputs'], file_params, overrides)
    name = name or str(params.get('exp_name') or 'headless_run')

    folder = Path(out_dir) / f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    suffix = 1
    while folder.exists():
        suffix += 1
        folder = Path(out_dir) / f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{suffix}"
    folder.mkdir(parents=True)

    results = []
    runs = plan_runs(params, sweeps, max(int(replicates), 1), name)
    for index, (run_name, run_params) in enumerate(runs, 1):
        run_params['_schema_fingerprint'] = fingerprint
        if allow_inadmissible:
            run_params['allow_inadmissible'] = True
        audit = None
        try:
            audit = build_parameter_audit(schema, run_params, schema_fingerprint=fingerprint,
                                          resolve_ref=lambda k: REFERENCES.get(k, {}))
        except Exception as e:  # noqa: BLE001
            echo(f"  warning: parameter audit not built for {run_name}: {e}")
        worker = SimulationWorker(run_params, str(folder), parameter_audit=audit)
        errors = []
        worker.error.connect(errors.append)
        echo(f"[{index}/{len(runs)}] {run_name}  (seed {run_params['random_seed']})")
        worker.run()
        try:
            status = json.loads(worker.metadata_path.read_text()).get('simulation_status')
        except Exception:  # noqa: BLE001
            status = 'failed'
        archive = worker.exp_dir / f"{run_name}.omex"
        results.append({'name': run_name, 'status': status,
                        'archive': str(archive) if archive.exists() else None,
                        'error': (errors[0].splitlines()[0] if errors else None)})
        echo(f"      -> {status}" + (f": {results[-1]['error']}" if errors else ""))

    if report:
        tool = HERE.parent / 'vivarium-angio' / 'make_omex_combo_report.py'
        try:
            subprocess.run([sys.executable, str(tool), str(folder)], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3600)
        except Exception as e:  # noqa: BLE001  (reports are best-effort, as in the GUI)
            echo(f"  warning: reports not generated: {e}")
    return folder, results


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Run Angio-GUI experiments without a window, through the GUI's own "
                    "check, run records and archives.",
        epilog="See the module docstring for the full rules.")
    parser.add_argument('overrides', nargs='*', metavar='key=value',
                        help="parameter values; a comma-separated list sweeps a numeric "
                             "parameter")
    parser.add_argument('--params', help="parameter file (JSON, as saved by the GUI)")
    parser.add_argument('--out', default='experiments', help="output directory")
    parser.add_argument('--name', help="experiment name (default: exp_name)")
    parser.add_argument('--replicates', type=int, default=1)
    parser.add_argument('--allow-inadmissible', action='store_true',
                        help="permit values outside a declared implementation limit; "
                             "recorded with every run")
    parser.add_argument('--no-report', action='store_true',
                        help="skip the PDF reports and the experiment-level archive")
    args = parser.parse_args(argv)

    overrides = {}
    for item in args.overrides:
        if '=' not in item:
            parser.error(f"expected key=value, got {item!r}")
        key, value = item.split('=', 1)
        overrides[key.strip()] = value.strip()
    file_params = None
    if args.params:
        try:
            file_params = json.loads(Path(args.params).read_text())
        except Exception as e:  # noqa: BLE001
            parser.error(f"cannot read parameter file {args.params}: {e}")
        if not isinstance(file_params, dict):
            parser.error(f"{args.params} does not hold a JSON object of parameters")

    folder, results = run_specification(
        file_params, overrides, out_dir=args.out, name=args.name,
        replicates=args.replicates, allow_inadmissible=args.allow_inadmissible,
        report=not args.no_report)
    ok = sum(r['status'] == 'success' for r in results)
    print(f"\n{ok} of {len(results)} run(s) succeeded. Records and archives: {folder}")
    return 0 if ok == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
