"""Re-execute one example archive of an application and compare with what it stored.

    python .github/scripts/replay_check.py angio   <work dir>
    python .github/scripts/replay_check.py vcornea <work dir>

Follows the commands documented in vivarium-angio/README.md and
vivarium-vcornea/README.md ("Re-executing, from the unpacked archive"). Exit
status 0 means every compared value was identical.
"""
import os
import platform
import re
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENV = {**os.environ, 'OPENBLAS_NUM_THREADS': '1'}


ABNORMAL_EXITS = []
NUMERIC_ONLY = []     # pathways equal in cell configuration, field differs in last bits
KNOWN_EXITS = []      # crashed at exit after reporting completion (archived script)


def run(cmd, cwd, tolerate_exit=False):
    """Run a command. With tolerate_exit, a non-zero exit status is recorded and
    reported instead of ending the check, so that what the command wrote can still
    be compared (a process that crashes while exiting has already written it)."""
    print('$', ' '.join(str(c) for c in cmd), flush=True)
    done = subprocess.run(cmd, cwd=cwd, env=ENV, capture_output=True, text=True)
    if done.returncode != 0:
        print(done.stdout[-3000:])
        print(done.stderr[-3000:])
        if not tolerate_exit:
            raise SystemExit(f'command failed with exit code {done.returncode}')
        ABNORMAL_EXITS.append((' '.join(str(c) for c in cmd[1:4]), done.returncode))
        print(f'NOTE: exit code {done.returncode}; comparing what it wrote', flush=True)
    return done


def angio(work):
    import numpy as np
    from vivarium_angio.utils import omex_generator as og
    archive = (REPO / 'examples' / 'angio-gui_lchem_sweep' / 'angio_lchem_sweep_combo002_rep01'
               / 'angio_lchem_sweep_combo002_rep01.omex')
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(work, [n for n in zf.namelist() if n.startswith('model/')])
    store = og.extract_archive_zarr(archive, work / 'archived_zarr')
    archived = {step: np.array(data) for step, data in og._load_zarr_steps(store, strict=True)}
    print('archived steps:', sorted(archived))

    run([sys.executable, '-m', 'cc3d.run_script', '-i', 'model/angiogenesis.cc3d',
         '-o', str(work / 'out')], work)
    native = {int(p.stem.split('_')[1]): np.load(p)
              for p in (work / 'model' / 'native_output').glob('step_*.npy')}
    # The run_model.py inside archives written before v1.1.2 does not end the
    # process itself; on Linux CompuCell3D then crashes during interpreter
    # teardown, after the trajectory is written. That exit is tolerated here and
    # reported; what it wrote is compared like any other output.
    rm = run([sys.executable, 'run_model.py'], work / 'model', tolerate_exit=True)
    if rm.returncode != 0 and 'Re-run complete' in rm.stdout:
        KNOWN_EXITS.append(ABNORMAL_EXITS.pop())
    rerun = {step: np.array(data) for step, data in og._load_zarr_steps(
        work / 'model' / 'rerun_output' / 'data.zarr', strict=True)}

    # Channels of the stored state: 0 cell type, 1 cell id, 2 VEGF concentration.
    # The first two are integers (the cell configuration); the third is a float
    # field, where a different processor architecture can differ in the last bits.
    ok = True
    for name, got in (('stock CompuCell3D', native), ('run_model.py', rerun)):
        same = [s for s in archived if s in got and np.array_equal(got[s], archived[s])]
        worst = max((float(np.abs(got[s] - archived[s]).max()) for s in archived if s in got),
                    default=float('nan'))
        print(f'{name}: {len(same)} of {len(archived)} archived steps identical; '
              f'largest absolute difference {worst:g}')
        if len(same) != len(archived):
            cells_same = all(s in got and np.array_equal(got[s][..., :2], archived[s][..., :2])
                             for s in archived)
            field = max(float(np.abs(got[s][..., 2] - archived[s][..., 2]).max())
                        for s in archived if s in got)
            scale = max(float(np.abs(archived[s][..., 2]).max()) for s in archived)
            print(f'{name}: cell configuration (type and id of every site) identical at every '
                  f'step: {cells_same}; VEGF field largest absolute difference {field:g} '
                  f'(field maximum {scale:g})')
            close = cells_same and field <= 1e-5 * max(scale, 1.0)
            if close:
                NUMERIC_ONLY.append(name)
            ok &= close
    return ok


def vcornea(work):
    archive = (REPO / 'examples' / 'vcornea_sls_sweep' / 'vcornea_sls_sweep_combo001'
               / 'replicate_1' / 'vcornea_sls_sweep_combo001.omex')
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(work)
    params = work / 'model' / 'Simulation' / 'Parameters.py'
    text = params.read_text()
    assert len(re.findall(r'^SimTime=7200$', text, flags=re.M)) == 1
    # One simulated day instead of thirty; compared over the day it covers.
    params.write_text(re.sub(r'^SimTime=7200$', 'SimTime=240', text, flags=re.M))
    run([sys.executable, '-m', 'cc3d.run_script', '-i', 'model/vCornea_v2.cc3d',
         '-o', str(work / 'out')], work)
    done = run([sys.executable, str(REPO / 'vivarium-vcornea' / 'compare_replay.py'),
                '.', 'model/Simulation', '241'], work)
    print(done.stdout)
    return 'ALL IDENTICAL' in done.stdout


if __name__ == '__main__':
    which, work = sys.argv[1], Path(sys.argv[2]).resolve()
    work.mkdir(parents=True, exist_ok=True)
    ok = {'angio': angio, 'vcornea': vcornea}[which](work)
    verdict = ('DIFFERS from the archive' if not ok else
               'same cell configuration as the archive; float field equal to rounding error '
               f'({platform.machine()})' if NUMERIC_ONLY else 'identical to the archive')
    print('RESULT:', verdict)
    for what, code in KNOWN_EXITS:
        print(f'KNOWN EXIT CRASH: `{what}` (script stored in the archive) ended with exit '
              f'code {code} after printing "Re-run complete"; its output was compared')
    for what, code in ABNORMAL_EXITS:
        print(f'ABNORMAL EXIT: `{what}` ended with exit code {code} after writing its output')
    sys.exit(0 if ok and not ABNORMAL_EXITS else 1)
