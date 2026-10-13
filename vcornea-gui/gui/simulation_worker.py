"""
Simulation worker for running vCornea cell fate simulations.

Runs the black-box Vivarium wrapper in a subprocess and reports completion.
"""

from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


class SimulationWorker(QObject):
    """Worker that runs a vCornea simulation in a subprocess."""

    progress = pyqtSignal(int, str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, parameters, output_dir='experiments'):
        super().__init__()
        self.parameters = parameters
        self.output_dir = Path(output_dir)
        self.exp_name = parameters.get('exp_name', 'unnamed_run')
        self.sim_time = parameters.get('sim_time', 100.0)

        self.exp_dir = self.output_dir / self.exp_name
        self.logs_dir = self.exp_dir / 'logs'
        self.metadata_path = self.exp_dir / 'run_metadata.json'

        self.process = None
        self.temp_script = None
        self._cancelled = False  # set by cancel(); checked before emit/finish

    @pyqtSlot()
    def cancel(self):
        """Kill the entire subprocess tree spawned by this worker.

        The outer subprocess we launched is a Python interpreter running
        Vivarium, which in turn forks `conda run ... cc3d.run_script` for
        each replicate. Plain self.process.kill() only stops the Python
        interpreter — the conda + CC3D grandchildren keep running on
        Windows, eating CPU long after the user clicked Cancel. We use
        psutil if available (best, cross-platform), and fall back to
        `taskkill /F /T /PID <pid>` on Windows or `process.kill()` on
        Unix-style systems. After the kill, drop a `cancelled.json` audit
        marker in the experiment dir so reviewers can tell a cancelled run
        apart from a crashed or never-started one.
        """
        self._cancelled = True
        was_running = self.process is not None and self.process.poll() is None
        if was_running:
            pid = self.process.pid
            killed = False
            try:
                import psutil
                try:
                    parent = psutil.Process(pid)
                    for child in parent.children(recursive=True):
                        try:
                            child.kill()
                        except psutil.NoSuchProcess:
                            pass
                    parent.kill()
                    killed = True
                except psutil.NoSuchProcess:
                    killed = True
            except ImportError:
                pass
            if not killed and sys.platform == 'win32':
                try:
                    subprocess.run(
                        ['taskkill', '/F', '/T', '/PID', str(pid)],
                        capture_output=True, timeout=10,
                    )
                    killed = True
                except Exception:
                    pass
            if not killed:
                try:
                    self.process.kill()
                except Exception:
                    pass

        # Write an audit marker so the run is recognizable as user-cancelled
        # rather than crashed or never started.
        self._write_status_marker('cancelled', 'cancelled.json',
                                  'User clicked Cancel in the GUI',
                                  was_running_at_cancel=was_running)

        # Package the interrupted run. The wrapper process was just killed, so it
        # never reached its own archiving step — without this a cancelled run is
        # the ONLY outcome that leaves no archive, which is exactly the gap
        # requirement 2.5.4 warns about when it names interrupted attempts
        # alongside failed and timed-out ones.
        # Replicates the wrapper already finalized keep their own outcome: one
        # that completed before the cancel is a completed run, not a cancelled one.
        self._generate_interrupted_archives(
            'cancelled', 'Run interrupted by the operator before completion.',
            only_unfinalized=True)

    def _write_status_marker(self, status, filename, reason, **extra):
        """Drop a small JSON audit marker in the experiment dir. Best-effort: the
        exp_dir may not exist yet if the worker was stopped very early."""
        try:
            from datetime import datetime as _datetime
            self.exp_dir.mkdir(parents=True, exist_ok=True)
            (self.exp_dir / filename).write_text(json.dumps({
                'exp_name': self.exp_name,
                'status': status,
                f'{status}_at': _datetime.now().isoformat(),
                'reason': reason,
                **extra,
            }, indent=2))
        except Exception as e:
            print(f"  > Could not write {filename} for {self.exp_name}: {e}")

    def _generate_interrupted_archives(self, status, reason, only_unfinalized=False):
        """Write a status-typed OMEX archive (cancelled / timed_out) for each
        replicate directory.

        Best-effort and deliberately quiet about missing pieces: a run stopped
        seconds after launch may have no replicate directories, no outputs and no
        metadata, and the marker file alone is then the record. Whatever partial
        outputs DO exist are preserved and marked interrupted, so they can never be
        mistaken for a completed experiment.

        only_unfinalized: skip replicates whose run_metadata.json already carries
        a final simulation_status (VCorneaProcess finished and archived them).
        """
        try:
            from vivarium_vcornea.utils.omex_generator import create_omex_archive
            from vivarium_vcornea.utils.provenance import run_provenance
        except Exception as e:
            print(f"  > Cancelled-run archive skipped ({e})")
            return

        if not self.exp_dir.exists():
            return
        targets = sorted(d for d in self.exp_dir.iterdir()
                         if d.is_dir() and d.name.startswith('replicate_'))
        if not targets:
            targets = [self.exp_dir]

        from datetime import datetime as _dt
        for target in targets:
            try:
                # Prefer metadata the process managed to write; otherwise synthesize
                # enough to identify what was intended.
                meta_path = target / 'run_metadata.json'
                if meta_path.exists():
                    metadata = json.loads(meta_path.read_text())
                    if only_unfinalized and metadata.get('simulation_status'):
                        continue
                else:
                    metadata = {
                        'run_name': self.exp_dir.name,
                        'created_at': _dt.now().isoformat(),
                        'simulation_config': {},
                        'key_parameters': {},
                    }
                metadata.update({
                    'simulation_status': status,
                    'simulation_success': False,
                    'timed_out': status == 'timed_out',
                    f'{status}_at': _dt.now().isoformat(),
                    'error_message': reason,
                    'creator': self.parameters.get('creator'),
                })
                metadata.setdefault('provenance', run_provenance())
                if target != self.exp_dir:
                    # Replicate-level record now agrees with its archive. (exp_dir's
                    # own run_metadata.json is the worker's record; leave it.)
                    meta_path.write_text(json.dumps(metadata, indent=2, default=str))
                create_omex_archive(
                    run_output_dir=target,
                    run_metadata=metadata,
                    sim_params=self.parameters,
                    include_model=False,   # the run never proved the project ran
                    status=status,
                )
                print(f"  > {status} archive written for {target.name}")
            except Exception as e:
                print(f"  > Could not archive {status} run {target.name}: {e}")

    # Headroom between the per-replicate limit enforced inside VCorneaProcess and
    # this outer wait. The two must NOT expire together: when a replicate times out
    # the process still has to terminate it, collect whatever partial outputs exist,
    # write the run metadata and build the failure-typed archive. Killing the whole
    # batch at the same instant would destroy exactly the failure evidence that
    # requirement 2.5.4 asks us to preserve.
    _TIMEOUT_GRACE_S = 1800

    def _outer_timeout(self):
        """Wall-clock ceiling for the batch subprocess.

        Derived from the same `run_timeout_seconds` the process applies per
        replicate, so one setting governs both layers, plus grace for the process
        to record the timeout rather than be killed mid-write.
        """
        try:
            per_replicate = int(self.parameters.get('run_timeout_seconds', 86400) or 86400)
        except (TypeError, ValueError):
            per_replicate = 86400
        return max(per_replicate, 1) + self._TIMEOUT_GRACE_S

    @pyqtSlot()
    def run(self):
        try:
            self.progress.emit(0, f"Initializing simulation: {self.exp_name}")
            start_time = time.time()
            self.temp_script = self._create_simulation_script()

            self.exp_dir.mkdir(parents=True, exist_ok=True)
            self.logs_dir.mkdir(exist_ok=True)

            stdout_log_path = self.logs_dir / 'stdout.log'
            stderr_log_path = self.logs_dir / 'stderr.log'

            self.stdout_log = open(stdout_log_path, 'w')
            self.stderr_log = open(stderr_log_path, 'w')

            self.progress.emit(10, "Launching simulation process...")
            self.process = subprocess.Popen(
                [sys.executable, str(self.temp_script)],
                stdout=self.stdout_log,
                stderr=self.stderr_log,
                text=True
            )

            exit_code = self.process.wait(timeout=self._outer_timeout())

            self.stdout_log.close()
            self.stderr_log.close()

            with open(stdout_log_path, 'r') as f:
                stdout = f.read()
            with open(stderr_log_path, 'r') as f:
                stderr = f.read()

            final_step = self.sim_time if exit_code == 0 else 0

            # Note: an earlier version scanned `self.output_dir` (the BATCH
            # folder shared by every parallel worker in a sweep) for the
            # "latest" subdir and repointed self.exp_dir there. That was a
            # cross-worker race: every parallel worker would land on the
            # same target dir (whichever was last touched on disk), then
            # move its logs into that single dir — leaving the other workers'
            # logs/ folders empty. With run_name=exp_name now enforced in
            # VCorneaProcess._generate_run_name, the initial
            # self.exp_dir = self.output_dir / self.exp_name is already the
            # correct, unique-per-worker target. No repointing needed.

            self._save_run_metadata(exit_code, final_step)

            # If the user clicked Cancel, the subprocess was killed by
            # cancel() above; emit nothing and let the main thread's
            # finalize_batch handle the summary.
            if self._cancelled:
                return

            # Reality check: a clean subprocess exit (code 0) is necessary but
            # not sufficient. CC3D can exit normally even when it crashed on
            # startup before writing any output (e.g. UNC-cwd failures on
            # Windows). Confirm by reading the VCorneaProcess-written
            # run_metadata.json (its simulation_success field reflects whether
            # cell_count_*.csv was actually produced) and, as a fallback,
            # checking for any cell_count_*.csv anywhere under the run dir.
            true_success = self._verify_real_outputs(exit_code)

            if true_success:
                self.progress.emit(100, "Simulation completed successfully!")
                self.finished.emit({
                    'exp_name': self.exp_name,
                    'exp_dir': str(self.exp_dir),
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
                error_msg = self._format_failure_message(exit_code, stdout, stderr,
                                                        stdout_log_path, stderr_log_path)
                self.error.emit(error_msg)

        except subprocess.TimeoutExpired:
            # Kill the whole tree (the wrapper plus its CC3D grandchildren), then
            # record the outcome: any replicate the wrapper had not finalized gets
            # a timed_out archive instead of being left as a bare directory.
            try:
                from vivarium_vcornea.utils.process_tree import kill_process_tree
                kill_process_tree(self.process)
            except ImportError:
                if self.process:
                    self.process.kill()
            limit = self._outer_timeout()
            self._write_status_marker('timed_out', 'timed_out.json',
                                      f'Batch exceeded its {limit}s wall-clock limit',
                                      timeout_seconds=limit)
            self._generate_interrupted_archives(
                'timed_out',
                f'Batch exceeded its {limit}s wall-clock limit and was terminated.',
                only_unfinalized=True)
            self.error.emit(
                f"Simulation timed out after {limit}s ({limit / 3600:.1f}h) and was "
                f"terminated. This is the batch-level limit (per-replicate limit "
                f"{self.parameters.get('run_timeout_seconds', 86400)}s plus "
                f"{self._TIMEOUT_GRACE_S}s for result collection); the process did not "
                f"report its own per-replicate timeout first, so it may have hung "
                f"outside the simulation itself. Check "
                f"{self.logs_dir / 'stderr.log'}.")
        except Exception as e:
            import traceback
            error_msg = f"{str(e)}\n\n{traceback.format_exc()}"
            self.error.emit(error_msg)
        finally:
            if self.temp_script and self.temp_script.exists():
                self.temp_script.unlink()

    def _create_simulation_script(self):
        params_with_store = self.parameters.copy()
        params_with_store['output_base_dir'] = str(self.output_dir)

        project_root = Path(__file__).resolve().parents[2]
        # Prefer the clean paper-version model from github.com/VaninJoel/vCornea
        # (no MaBoSS coupling) and fall back to the cellfate-augmented copy
        # only if the clean source isn't present. The cellfate version's
        # `from maboss_helpers import ...` was crashing CC3D silently on
        # startup, producing the long string of "exit 0, no output" failures.
        candidates = [
            project_root / 'vcornea_paper' / 'Local' / 'Project' / 'paper_version',
            project_root / 'vcornea_cellfate_updated',
        ]
        vcornea_project_path = next((p for p in candidates if p.exists()), None)
        vivarium_vcornea_dir = project_root / 'vivarium-vcornea'

        if vcornea_project_path is not None:
            params_with_store['vcornea_project_path'] = str(vcornea_project_path)

        script_content = f"""
import sys
from vivarium.core.engine import Engine

sys.path.insert(0, {repr(str(vivarium_vcornea_dir))})
from vivarium_vcornea.composites.vcornea_composer import VCorneaComposer

params = {{
    'vcornea': {repr(params_with_store)}
}}

print("Starting vCornea CellFate simulation", flush=True)
# Diagnostic: surface what params actually reached this subprocess so we
# can spot any cross-worker contamination in batch sweeps.
_inner = params.get('vcornea', {{}})
print(f"  [worker-diag] exp_name = {{_inner.get('exp_name')!r}}", flush=True)
print(f"  [worker-diag] output_base_dir = {{_inner.get('output_base_dir')!r}}", flush=True)
print(f"  [worker-diag] EGF_STEM_HalfMaxValue = {{_inner.get('EGF_STEM_HalfMaxValue')!r}}", flush=True)
print(f"  [worker-diag] replicates = {{_inner.get('replicates')!r}}", flush=True)
try:
    composer = VCorneaComposer(params)
    composite = composer.generate()
    engine = Engine(composite=composite)
    engine.update(1.0)
    print("Simulation completed successfully", flush=True)
    sys.exit(0)
except Exception as e:
    print(f"ERROR: {{e}}", file=sys.stderr, flush=True)
    import traceback
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)
"""

        # Include the exp_name AND a uuid so parallel workers in a sweep
        # never collide on the same temp script path. The earlier
        # `int(time.time())` only had per-second resolution, so two workers
        # launched in the same second would write to the SAME file — the
        # second overwriting the first, and both subprocesses then running
        # whichever script content won the race. That's what caused all
        # parameter sweep combos to land in one combo's output directory.
        import uuid as _uuid
        safe_name = ''.join(c if c.isalnum() else '_' for c in self.exp_name)[:40]
        temp_file = Path(tempfile.gettempdir()) / (
            f"vcornea_cellfate_{safe_name}_{_uuid.uuid4().hex[:8]}.py"
        )
        temp_file.write_text(script_content)
        return temp_file

    def _save_run_metadata(self, exit_code, final_step):
        metadata = {
            'experiment_name': self.exp_name,
            'parameters': self.parameters,
            'execution': {
                'exit_code': exit_code,
                'success': exit_code == 0,
                'final_step': final_step,
            }
        }
        if self.metadata_path.exists():
            return
        try:
            self.metadata_path.write_text(json.dumps(metadata, indent=2))
        except Exception:
            pass

    def _find_latest_run_dir(self, output_dir: Path, start_time: float):
        candidates = [p for p in output_dir.iterdir() if p.is_dir()]
        recent = [p for p in candidates if p.stat().st_mtime >= start_time - 5]
        if not recent:
            return None
        return max(recent, key=lambda p: p.stat().st_mtime)

    def _move_logs(self, run_dir: Path, stdout_log: Path, stderr_log: Path):
        logs_dir = run_dir / 'logs'
        logs_dir.mkdir(exist_ok=True)
        try:
            shutil.move(str(stdout_log), str(logs_dir / stdout_log.name))
            shutil.move(str(stderr_log), str(logs_dir / stderr_log.name))
        except Exception:
            pass

    def _verify_real_outputs(self, exit_code: int) -> bool:
        """Return True only if the run produced real simulation output.

        Subprocess exit code 0 alone is unreliable: CC3D can return 0 after
        crashing on startup (e.g. UNC-cwd failures on Windows). We trust the
        VCorneaProcess-written run_metadata.json if present, and fall back to
        scanning the run dir for cell_count_*.csv.
        """
        if exit_code != 0:
            return False

        # Trust VCorneaProcess's own verdict if it wrote one (Fix B at the
        # process layer sets simulation_success: False when no real outputs
        # appeared even with exit 0).
        if self.exp_dir.exists():
            for meta_path in self.exp_dir.rglob('run_metadata.json'):
                try:
                    meta = json.loads(meta_path.read_text())
                except Exception:
                    continue
                if meta.get('simulation_success') is False:
                    return False

        # Fallback: any cell_count CSV anywhere under the run dir counts.
        if self.exp_dir.exists():
            for _ in self.exp_dir.rglob('cell_count_*.csv'):
                return True

        return False

    def _format_failure_message(self, exit_code, stdout, stderr,
                                stdout_log_path, stderr_log_path) -> str:
        cause = (
            f"Subprocess exit code: {exit_code} (0 = OS-level clean exit, "
            f"but no cell_count_*.csv was produced — CC3D likely crashed on startup)."
            if exit_code == 0
            else f"Subprocess exit code: {exit_code}."
        )
        tail = (stderr or stdout or '').strip().splitlines()[-15:]
        tail_block = "\n".join(tail) if tail else "(no log output)"
        return (
            f"Simulation failed.\n\n"
            f"{cause}\n\n"
            f"Experiment directory:\n  {self.exp_dir}/\n\n"
            f"Log files:\n  stdout: {stdout_log_path}\n  stderr: {stderr_log_path}\n\n"
            f"Last 15 lines of stderr/stdout:\n{tail_block}"
        )
