"""
Simulation worker for running angiogenesis simulations with progress tracking.

This worker leverages the Integrated Architecture pattern:
- Uses Vivarium Engine + AngiogenesisComposer for execution
- Runs simulation in subprocess for process isolation (prevents CC3D state conflicts)
- Monitors Zarr store for incremental progress updates (data written every 10 MCS)
- Emits signals for GUI progress bar and completion handling
"""

from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot, QTimer
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import zarr


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

    def __init__(self, parameters, output_dir='experiments'):
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

    @pyqtSlot()
    def run(self):
        """Main method executed on background thread."""
        try:
            self.progress.emit(0, f"Initializing simulation: {self.exp_name}")

            # Create temporary script for subprocess execution
            self.temp_script = self._create_simulation_script()

            self.progress.emit(5, "Launching simulation process...")

            # Create experiment directory structure
            self.exp_dir.mkdir(parents=True, exist_ok=True)
            self.logs_dir.mkdir(exist_ok=True)

            stdout_log_path = self.logs_dir / 'stdout.log'
            stderr_log_path = self.logs_dir / 'stderr.log'

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

            # Start monitoring Zarr store for progress
            self._monitor_progress()

            # Wait for process to complete (24 hour timeout)
            try:
                exit_code = self.process.wait(timeout=86400)
            except subprocess.TimeoutExpired:
                self.process.kill()
                raise
            finally:
                # Close log files
                self.stdout_log.close()
                self.stderr_log.close()

                # Read logs for reporting
                with open(stdout_log_path, 'r') as f:
                    stdout = f.read()
                with open(stderr_log_path, 'r') as f:
                    stderr = f.read()

            # Get final step to see how far we got
            final_step = self._get_final_step()

            # Analyze exit code (including Windows CC3D crashes)
            exit_code_msg = self._interpret_exit_code(exit_code)

            # Save run metadata to experiment directory
            self._save_run_metadata(exit_code, final_step)

            # Always package the run into a COMBINE/OMEX archive (no opt-out) —
            # successful AND failed. A failed run produces a typed archive marked
            # failed (no executable SED-ML, status.json=failed) carrying params,
            # provenance, logs and any partial Zarr outputs, instead of being left
            # as a loose directory.
            run_succeeded = (exit_code == 0 and self.zarr_path.exists())
            self._generate_omex_archive(final_step, failed=not run_succeeded)

            if exit_code == 0:
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
            else:
                error_msg = (
                    f"Simulation failed with exit code {exit_code}\n"
                    f"{exit_code_msg}\n\n"
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
                self.error.emit(error_msg)

        except subprocess.TimeoutExpired:
            self.error.emit("Simulation timed out after 24 hours")
            if self.process:
                self.process.kill()
        except Exception as e:
            import traceback
            error_msg = f"{str(e)}\n\n{traceback.format_exc()}"
            self.error.emit(error_msg)
        finally:
            # Cleanup
            if self.temp_script and self.temp_script.exists():
                self.temp_script.unlink()

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
        """
        self.monitoring = True
        last_reported_step = 0

        while self.monitoring and self.process.poll() is None:
            time.sleep(2)  # Check every 2 seconds

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

    def _save_run_metadata(self, exit_code, final_step):
        """
        Save run metadata to a JSON file in the experiment directory.

        This creates a complete record of the simulation run including
        parameters, timing, success status, and file locations.
        """
        import json
        from datetime import datetime

        metadata = {
            'experiment_name': self.exp_name,
            'timestamp': datetime.now().isoformat(),
            'parameters': self.parameters,
            'simulation_status': 'success' if exit_code == 0 else 'failed',
            'run_reference': self._build_run_reference(),  # Task B (None for single runs)
            'execution': {
                'exit_code': exit_code,
                'success': exit_code == 0,
                'final_step': final_step,
                'expected_steps': int(self.sim_time),
                'completion_percentage': (final_step / self.sim_time * 100) if self.sim_time > 0 else 0
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

    def _generate_omex_archive(self, final_step, failed=False):
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
                'created_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
                'model_name': 'Angiogenesis',
                'model_version': '1.0.0',
                'parameters': self.parameters,
                'final_step': final_step,
                'final_mcs': final_step,
                'zarr_store_path': str(self.zarr_path),
                'simulation_status': 'failed' if failed else 'success',
                'run_reference': self._build_run_reference(),  # Task B (None for single runs)
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
            )
            print(f"Generated {'FAILED ' if failed else ''}OMEX archive: {omex_path}")
        except Exception as e:
            print(f"Warning: Could not generate OMEX archive: {e}")

