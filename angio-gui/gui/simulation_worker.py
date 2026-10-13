"""
Simulation worker for running angiogenesis simulations with progress tracking.

This worker leverages the Integrated Architecture pattern:
- Uses Vivarium Engine + AngiogenesisComposer for execution
- Runs simulation in subprocess for process isolation (prevents CC3D state conflicts)
- Monitors Zarr store for incremental progress updates (data written every 10 MCS)
- Emits signals for GUI progress bar and completion handling
"""

from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot, QTimer
import json
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
import zarr

# Default per-run wall-clock limit (seconds); override with the
# `run_timeout_seconds` parameter. Recorded with every run.
DEFAULT_RUN_TIMEOUT_S = 86400


def _kill_tree(process):
    """Kill a subprocess and all its descendants (CC3D survives its parent on
    Windows). Falls back to killing the direct child if the helper is missing."""
    try:
        from vivarium_angio.utils.process_tree import kill_process_tree
    except ImportError:
        try:
            process.kill()
        except Exception:
            pass
        return
    kill_process_tree(process)


class SimulationWorker(QObject):
    """
    Worker that runs angiogenesis simulation in a subprocess with progress monitoring.

    The simulation writes data to Zarr every 10 steps, and we monitor the store
    to track progress in real-time without blocking the GUI.
    """

    # Signals
    progress = pyqtSignal(int, str)  # (percentage, message)
    finished = pyqtSignal(dict)      # {exp_name, store_path, final_step}
    error = pyqtSignal(str)          # Error message

    def __init__(self, parameters, output_dir='experiments', parameter_audit=None):
        """
        Initialize simulation worker.

        Parameters
        ----------
        parameters : dict
            Dictionary containing all simulation parameters including:
            - exp_name: Experiment name
            - jee, jem, lchem, etc.: Model parameters
            - sim_time: Total simulation time (MCS)
        output_dir : str
            Base directory for experiment outputs (can be local or cloud path)
        """
        super().__init__()
        self.parameters = parameters
        # Built by the main window, which holds the live schema (this worker and
        # its subprocess do not): what the schema documents about every value in
        # `parameters`. Stored into the archive and alongside run_metadata.json.
        self.parameter_audit = parameter_audit
        self.output_dir = Path(output_dir)
        self.exp_name = parameters.get('exp_name', 'unnamed_run')
        self.sim_time = parameters.get('sim_time', 100.0)
        self.write_frequency = self.parameters.get('write_frequency', 10)  # NEW

        # Create experiment directory structure
        self.exp_dir = self.output_dir / self.exp_name
        self.zarr_path = self.exp_dir / 'data.zarr'
        self.logs_dir = self.exp_dir / 'logs'
        self.metadata_path = self.exp_dir / 'run_metadata.json'

        self.process = None
        self.temp_script = None
        self.monitoring = False
        self._cancelled = False  # set by cancel(); suppresses the normal result path
        # Wall-clock start, stamped when run() begins. Recorded with the run so a
        # reviewer can distinguish a run that finished quickly from one that was
        # cut short, and so batch cost is auditable.
        self._started_at = None
        # Durable identity of this attempt (exp_name is a human label that a
        # rerun can repeat); recorded in run_metadata.json and the archive.
        self.run_id = uuid.uuid4().hex
        try:
            self._timeout_s = max(int(parameters.get('run_timeout_seconds',
                                                     DEFAULT_RUN_TIMEOUT_S)), 1)
        except (TypeError, ValueError):
            self._timeout_s = DEFAULT_RUN_TIMEOUT_S
        self._timed_out = False
        self._launch_error = None

    @pyqtSlot()
    def cancel(self):
        """Kill the entire subprocess tree spawned by this worker.

        Cancelling previously called only QThread.quit(), which does nothing while
        the worker is blocked waiting on the subprocess: the CC3D simulation kept
        running to completion, consuming CPU, while the interface reported the
        batch as cancelled. Killing only our direct child is not enough either —
        it is a Python interpreter whose CC3D grandchildren survive it on Windows.

        A cancellation marker and a status='cancelled' archive are then written so
        an interrupted attempt is recorded rather than silently absent.
        """
        self._cancelled = True
        was_running = self.process is not None and self.process.poll() is None
        if was_running:
            _kill_tree(self.process)

        self.monitoring = False
        try:
            from datetime import datetime as _dt
            self.exp_dir.mkdir(parents=True, exist_ok=True)
            (self.exp_dir / 'cancelled.json').write_text(json.dumps({
                'exp_name': self.exp_name,
                'run_id': self.run_id,
                'status': 'cancelled',
                'cancelled_at': _dt.now().isoformat(),
                'was_running_at_cancel': was_running,
                'reason': 'User clicked Cancel in the GUI',
            }, indent=2))
        except Exception as e:
            print(f"  > Could not write cancelled.json for {self.exp_name}: {e}")

        self._generate_omex_archive(self._get_final_step(), status='cancelled')

    @pyqtSlot()
    def run(self):
        """Main method executed on background thread.

        Every attempt that gets as far as owning its run directory ends with a
        run_metadata.json and a status-typed archive — success, failure, timeout
        or cancellation — and the GUI is told success only when the archive says
        success (one predicate, _outcome, decides both).
        """
        exit_code = None
        stdout = stderr = ''
        stdout_log_path = self.logs_dir / 'stdout.log'
        stderr_log_path = self.logs_dir / 'stderr.log'
        self._started_at = time.time()
        self.progress.emit(0, f"Initializing simulation: {self.exp_name}")

        # A run directory is single-use. The Zarr writer opens its store in
        # append mode and skips steps that already exist, so a rerun into the
        # same directory would silently mix the earlier run's snapshots into
        # this one. Refuse before touching anything, so the earlier run's
        # records are left intact.
        if self.zarr_path.exists():
            self.error.emit(
                f"Refusing to reuse {self.zarr_path}: it already holds a run. Reusing it "
                f"would mix that run's snapshots into this one. Choose a new experiment "
                f"name or output folder.")
            return

        try:
            # Create temporary script for subprocess execution
            self.temp_script = self._create_simulation_script()

            self.progress.emit(5, "Launching simulation process...")

            # Create experiment directory structure
            self.exp_dir.mkdir(parents=True, exist_ok=True)
            self.logs_dir.mkdir(exist_ok=True)

            self.stdout_log = open(stdout_log_path, 'w')
            self.stderr_log = open(stderr_log_path, 'w')

            # Launch simulation subprocess with log file redirection
            self.process = subprocess.Popen(
                [sys.executable, str(self.temp_script)],
                stdout=self.stdout_log,
                stderr=self.stderr_log,
                text=True
            )

            self.progress.emit(10, f"Simulation running (PID: {self.process.pid}), monitoring progress...")

            # Monitor the Zarr store until the process exits or its wall-clock
            # limit passes (in which case the whole tree is killed).
            self._monitor_progress()
            try:
                exit_code = self.process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                _kill_tree(self.process)
                exit_code = None
        except Exception as e:
            import traceback
            self._launch_error = f"{e}\n\n{traceback.format_exc()}"
        finally:
            for handle in (getattr(self, 'stdout_log', None), getattr(self, 'stderr_log', None)):
                if handle is not None and not handle.closed:
                    handle.close()
            for path, name in ((stdout_log_path, 'stdout'), (stderr_log_path, 'stderr')):
                try:
                    text = path.read_text()
                except Exception:
                    text = ''
                if name == 'stdout':
                    stdout = text
                else:
                    stderr = text
            if self.temp_script and self.temp_script.exists():
                self.temp_script.unlink()

        final_step = self._get_final_step()

        # If the operator cancelled, cancel() already killed the process tree and
        # wrote the cancellation marker and archive. Record the run as cancelled
        # (not failed) and emit nothing: an interruption is not a model failure.
        if self._cancelled:
            self._save_run_metadata(exit_code, final_step, 'cancelled')
            return

        status = self._outcome(exit_code)
        self._save_run_metadata(exit_code, final_step, status)
        # Always package the run into a COMBINE/OMEX archive (no opt-out), typed
        # with its status: a non-successful run carries params, provenance, logs
        # and any partial Zarr outputs but no executable SED-ML.
        self._generate_omex_archive(final_step, status=status, exit_code=exit_code)

        if status == 'success':
            self.progress.emit(100, "Simulation completed successfully!")
            self.finished.emit({
                'exp_name': self.exp_name,
                'exp_dir': str(self.exp_dir),
                'zarr_path': str(self.zarr_path),
                'final_step': final_step,
                'parameters': self.parameters,
                'stdout': stdout,
                'stderr': stderr,
                'log_files': {
                    'stdout': str(stdout_log_path),
                    'stderr': str(stderr_log_path)
                },
                'success': True
            })
            return

        if status == 'timed_out':
            headline = (f"Simulation exceeded its {self._timeout_s}s wall-clock limit and "
                        f"was terminated (whole process tree killed).")
        elif self._launch_error:
            headline = f"Simulation could not be run:\n{self._launch_error}"
        elif exit_code == 0:
            headline = "Simulation process exited cleanly but produced no Zarr store."
        else:
            headline = (f"Simulation failed with exit code {exit_code}\n"
                        f"{self._interpret_exit_code(exit_code)}")
        self.error.emit(
            f"{headline}\n\n"
            f"Reached step: {final_step}/{int(self.sim_time)}\n\n"
            f"Experiment directory:\n"
            f"  {self.exp_dir}/\n\n"
            f"Log files:\n"
            f"  stdout: {stdout_log_path}\n"
            f"  stderr: {stderr_log_path}\n\n"
            f"Last 20 lines of stdout:\n"
            f"{self._get_tail(stdout, 20)}\n\n"
            f"Last 20 lines of stderr:\n"
            f"{self._get_tail(stderr, 20)}"
        )

    def _outcome(self, exit_code):
        """The run's status: the single success predicate for metadata, archive
        and GUI signal alike."""
        if self._launch_error:
            return 'failed'
        if self._timed_out:
            return 'timed_out'
        if exit_code == 0 and self.zarr_path.exists():
            return 'success'
        return 'failed'

    def _create_simulation_script(self):
        """Create temporary Python script to run simulation in subprocess."""
        # Pass zarr path to the simulation
        params_with_store = self.parameters.copy()
        params_with_store['store_path'] = str(self.zarr_path)

        script_content = f"""
import sys, os
from vivarium.core.engine import Engine
from vivarium_angio.composites.angiogenesis_composer import AngiogenesisComposer

# Parameters from GUI (includes custom store_path)
params = {{
    'angiogenesis_process': {repr(params_with_store)}
}}

print(f"Starting simulation: {{params['angiogenesis_process']['exp_name']}}", flush=True)
print(f"Duration: {{params['angiogenesis_process']['sim_time']}} MCS", flush=True)
print(f"Zarr output: {{params['angiogenesis_process']['store_path']}}", flush=True)

try:
    # Create composer and engine
    print("Creating composer...", flush=True)
    composer = AngiogenesisComposer(params)
    composite = composer.generate()

    print("Creating engine...", flush=True)
    engine = Engine(composite=composite)

    # Run simulation
    sim_time = params['angiogenesis_process']['sim_time']
    print(f"Running engine.update({{sim_time}})...", flush=True)
    engine.update(sim_time)

    print(f"Simulation completed successfully", flush=True)

    # Capture the model from the LIVE process instance BEFORE we hard-exit:
    # serialize the native CC3D project from the executed self.specs and record the
    # live source path (Tasks D & E). os._exit() below bypasses Process.finish(),
    # so this is the only point at which the live instance is still in memory. The
    # parent worker's OMEX builder discovers <exp_dir>/model_export/ and bundles it.
    try:
        proc = composite['processes']['angiogenesis']
        exp_dir = os.path.dirname(params['angiogenesis_process']['store_path'])
        proc.export_model_export_dir(exp_dir)
        print("Captured native CC3D model export", flush=True)
    except Exception as _e:
        print(f"Warning: model export capture failed: {{_e}}", flush=True)

    # CompuCell3D 4.7.0's simservice segfaults during Python interpreter
    # teardown after a run (process exits 139), which the parent worker would
    # otherwise misread as a failed simulation and skip OMEX packaging. All
    # results are already flushed to the Zarr store by this point, so exit
    # cleanly with os._exit() to bypass CC3D's crashing C++ destructors.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)

except Exception as e:
    print(f"ERROR: {{e}}", file=sys.stderr, flush=True)
    import traceback
    traceback.print_exc(file=sys.stderr)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(1)
"""

        # Write to temporary file
        temp_file = Path(tempfile.gettempdir()) / f"angio_sim_{self.exp_name}_{int(time.time())}.py"
        temp_file.write_text(script_content)
        return temp_file

    def _monitor_progress(self):
        """
        Monitor Zarr store for simulation progress.

        The simulation writes data to the Zarr store at a configurable frequency.
        We periodically check what timesteps exist to calculate progress.

        This loop is also where the wall-clock limit is enforced: it runs until
        the process exits, so a limit applied after it (the old 24 h
        process.wait timeout) could never fire.
        """
        self.monitoring = True
        last_reported_step = 0
        deadline = (self._started_at or time.time()) + self._timeout_s

        while self.monitoring and self.process.poll() is None:
            remaining = deadline - time.time()
            if remaining <= 0:
                print(f"  > {self.exp_name}: exceeded {self._timeout_s}s limit; "
                      f"terminating the process tree")
                self._timed_out = True
                _kill_tree(self.process)
                break
            time.sleep(min(2, remaining))  # Check every 2 seconds

            try:
                current_step = self._get_latest_step()

                if current_step > last_reported_step:
                    # Calculate progress percentage
                    progress_pct = int((current_step / self.sim_time) * 100)
                    progress_pct = min(95, progress_pct)  # Cap at 95% until confirmed done

                    self.progress.emit(
                        progress_pct,
                        f"Step {current_step}/{int(self.sim_time)} MCS"
                    )
                    last_reported_step = current_step

            except Exception as e:
                # Store might not exist yet or experiment not created
                pass

        self.monitoring = False

    def _get_latest_step(self):
        """
        Get the latest timestep written to Zarr store.

        Returns
        -------
        int
            Latest timestep number, or 0 if no data written yet
        """
        try:
            # Open the experiment's Zarr store
            if not self.zarr_path.exists():
                return 0

            root = zarr.open(str(self.zarr_path), mode='r')

            # Get all timestep keys (they're stored as strings)
            timesteps = [int(key) for key in root.keys() if key.isdigit()]

            if timesteps:
                return max(timesteps)
            else:
                return 0

        except Exception:
            return 0

    def _get_final_step(self):
        """Get final timestep after simulation completion."""
        return self._get_latest_step()

    def _interpret_exit_code(self, exit_code):
        """
        Interpret exit codes, especially Windows CC3D crashes.

        Common exit codes:
        - 0: Success
        - 1: Python exception
        - -11: SIGSEGV (Linux crash)
        - 3221225477 / -1073741819: Windows ACCESS_VIOLATION (CC3D C++ crash)
        """
        if exit_code == 0:
            return "Success"
        elif exit_code == 1:
            return "Python exception (check stderr)"
        elif exit_code == -11:
            return "Segmentation fault (SIGSEGV) - CC3D crashed"
        elif exit_code == 3221225477 or exit_code == -1073741819:
            return (
                "Windows ACCESS_VIOLATION - Known CC3D crash issue\n"
                "This is a known CC3D Windows bug (exit code 3221225477).\n"
                "The crash may be related to:\n"
                "  - Cumulative memory corruption after ~40 steps\n"
                "  - Zarr write triggering corrupted state\n"
                "  - Windows-specific file locking issues\n"
                "Try: Reduce write frequency or use smaller lattice size"
            )
        elif exit_code < 0:
            return f"Process killed by signal {-exit_code}"
        else:
            return f"Unknown error (exit code {exit_code})"

    def _get_tail(self, text, num_lines=20):
        """Get last N lines from text."""
        if not text:
            return "(empty)"
        lines = text.strip().split('\n')
        return '\n'.join(lines[-num_lines:])

    def _save_run_metadata(self, exit_code, final_step, status):
        """
        Save run metadata to a JSON file in the experiment directory.

        This creates a complete record of the simulation run including
        parameters, timing, success status, and file locations. `status` is
        the same outcome the archive records (see _outcome).
        """
        from datetime import datetime

        metadata = {
            'experiment_name': self.exp_name,
            'run_id': self.run_id,
            'timestamp': datetime.now().isoformat(),
            'parameters': self.parameters,
            'simulation_status': status,
            'error_message': self._launch_error,
            'run_reference': self._build_run_reference(),  # Task B (None for single runs)
            # The seed handed to the CPM kernel for THIS run (assigned per-run by
            # the scheduler, so it is never the -1 sentinel here).
            'random_seed': self.parameters.get('random_seed'),
            'provenance': self._collect_provenance(),
            'execution': {
                'exit_code': exit_code,
                'exit_interpretation': (self._interpret_exit_code(exit_code)
                                        if exit_code is not None else None),
                'success': status == 'success',
                'timed_out': self._timed_out,
                'run_timeout_seconds': self._timeout_s,
                'final_step': final_step,
                'expected_steps': int(self.sim_time),
                'completion_percentage': (final_step / self.sim_time * 100) if self.sim_time > 0 else 0,
                'duration_seconds': (round(time.time() - self._started_at, 3)
                                     if self._started_at else None),
                'started_at': (datetime.fromtimestamp(self._started_at).isoformat()
                               if self._started_at else None),
            },
            'files': {
                'stdout_log': 'logs/stdout.log',
                'stderr_log': 'logs/stderr.log',
                'zarr_store': 'data.zarr'
            },
            'paths': {
                'experiment_dir': str(self.exp_dir.resolve()),
                'zarr_path': str(self.zarr_path.resolve()),
                'logs_dir': str(self.logs_dir.resolve())
            },
            'system': {
                'python_executable': sys.executable,
                'platform': sys.platform
            }
        }

        try:
            with open(self.metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not save run metadata: {e}")

    def _collect_provenance(self):
        """Schema fingerprint + code identity for this run (requirement 2.5.1).

        Loaded from the source tree by path for the same reason _generate_omex_archive
        does: an older `vivarium_angio` may be installed in the active environment
        without this submodule. Best-effort — never blocks a run.
        """
        try:
            project_root = Path(__file__).resolve().parents[2]
            mod_path = (project_root / 'vivarium-angio' / 'vivarium_angio'
                        / 'utils' / 'provenance.py')
            if not mod_path.exists():
                return {'error': f'provenance module not found at {mod_path}'}
            import importlib.util as _ilu
            spec = _ilu.spec_from_file_location('angio_provenance', str(mod_path))
            mod = _ilu.module_from_spec(spec)
            spec.loader.exec_module(mod)
            record = mod.run_provenance(start_path=mod_path.parent)
            # The schema fingerprint is computed ONCE by the main window, which
            # already holds the schema, and handed to each worker. It is not
            # recomputed here: instantiating AngiogenesisProcess builds and starts
            # a CC3D simulation in its constructor, so a "just read the schema"
            # call would launch a stray simulation per run.
            fingerprint = self.parameters.get('_schema_fingerprint')
            if fingerprint:
                record['schema_fingerprint'] = fingerprint
            return record
        except Exception as e:
            return {'error': f'provenance capture failed: {e}'}

    def _build_run_reference(self):
        """Task B back-reference for sweep runs, derived from sweep/replicate
        provenance carried on the parameters. None for single runs."""
        p = self.parameters
        scan = p.get('parameter_scan')
        scan_point = p.get('scan_point')
        replicate_id = p.get('replicate_id')
        parent = (p.get('parent_experiment_id') or p.get('parent_experiment')
                  or p.get('batch_id'))
        if not (scan or scan_point or replicate_id is not None or parent):
            return None
        return {
            'parent_experiment_id': parent,
            'parameter_combination': scan_point or None,
            'replicate_index': replicate_id,
            'combination_index': p.get('combination_index'),
            'total_combinations': p.get('total_combinations'),
            'total_replicates': p.get('total_replicates'),
            'parameter_scan': scan or None,
        }

    def _generate_omex_archive(self, final_step, failed=False, status=None, exit_code=None):
        """Package the run into a COMBINE/OMEX archive sibling to the Zarr store.

        Standards-compliant provenance is always-on: every run — successful or
        failed — produces an .omex archive at exp_dir/<exp_name>.omex. A failed
        run is marked failed (no executable SED-ML); see create_omex_archive_from_zarr.
        Failures here are logged but never block the run from being reported.
        """
        try:
            # Load omex_generator directly from the source file so we don't
            # collide with an older `vivarium_angio` package that may already
            # be installed in the active env without the new utils submodule.
            project_root = Path(__file__).resolve().parents[2]
            generator_path = (
                project_root / 'vivarium-angio' / 'vivarium_angio'
                / 'utils' / 'omex_generator.py'
            )
            if not generator_path.exists():
                raise FileNotFoundError(
                    f"omex_generator.py not found at {generator_path}"
                )
            import importlib.util as _ilu
            spec = _ilu.spec_from_file_location(
                'angio_omex_generator', str(generator_path)
            )
            mod = _ilu.module_from_spec(spec)
            spec.loader.exec_module(mod)
            create_omex_archive_from_zarr = mod.create_omex_archive_from_zarr

            run_metadata = {
                'experiment_id': self.exp_name,
                'run_id': self.run_id,
                'created_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
                # Termination detail, so the audit bundle alone shows how the run
                # ended (previously only the on-disk run_metadata.json had it).
                'exit_code': exit_code,
                'exit_interpretation': (self._interpret_exit_code(exit_code)
                                        if exit_code is not None else None),
                'timed_out': status == 'timed_out',
                'run_timeout_seconds': self._timeout_s,
                'started_at': (time.strftime('%Y-%m-%dT%H:%M:%S',
                                             time.localtime(self._started_at))
                               if self._started_at else None),
                'error_message': self._launch_error,
                'model_name': 'Angiogenesis',
                'model_version': '1.0.0',
                'parameters': self.parameters,
                'final_step': final_step,
                'final_mcs': final_step,
                'zarr_store_path': str(self.zarr_path),
                'simulation_status': status or ('failed' if failed else 'success'),
                'cancelled_at': (time.strftime('%Y-%m-%dT%H:%M:%S')
                                 if status == 'cancelled' else None),
                'run_reference': self._build_run_reference(),  # Task B (None for single runs)
                # Run identity: which realization, which parameter definitions,
                # which code. Consumed by the SED-ML writer and the PDF report.
                'random_seed': self.parameters.get('random_seed'),
                'parameter_credibility': (self.parameter_audit or {}).get('summary'),
                'provenance': self._collect_provenance(),
                'duration_seconds': (round(time.time() - self._started_at, 3)
                                     if self._started_at else None),
            }
            # Surface sweep/replicate provenance so the SED-ML scan notes resolve.
            for key in ('parameter_scan', 'scan_point', 'combination_index',
                        'total_combinations', 'replicate_id', 'total_replicates'):
                if self.parameters.get(key) is not None:
                    run_metadata[key] = self.parameters[key]
            omex_path = create_omex_archive_from_zarr(
                zarr_store_path=self.zarr_path,
                run_metadata=run_metadata,
                sim_params=self.parameters,
                archive_path=self.exp_dir / f"{self.exp_name}.omex",
                exp_name=self.exp_name,
                creator=self.parameters.get('creator'),  # experimenter (provenance), if set
                logs_dir=self.logs_dir,                   # stdout/stderr captured by this worker
                failed=failed,
                status=status,
                parameter_audit=self.parameter_audit,
            )
            if self.parameter_audit:
                try:
                    (self.exp_dir / 'parameter_audit.json').write_text(
                        json.dumps(self.parameter_audit, indent=2, default=str))
                except Exception as e:
                    print(f"Warning: could not write parameter_audit.json: {e}")
            resolved = status or ('failed' if failed else 'success')
            print(f"Generated {'' if resolved == 'success' else resolved.upper() + ' '}"
                  f"OMEX archive: {omex_path}")
        except Exception as e:
            print(f"Warning: Could not generate OMEX archive: {e}")

