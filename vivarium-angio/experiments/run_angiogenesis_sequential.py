"""A three-point sweep of EC-medium adhesion, run one point after another.

One call to the headless runner (`angio-gui/run_headless.py`) with a sweep list:
the runner starts each run in its own process, with its own directory, Zarr
store, run record and COMBINE/OMEX archive, then builds the experiment-level
archive and the PDF reports — exactly what the GUI does for a sweep.

    python run_angiogenesis_sequential.py [output_dir]
"""
import subprocess
import sys
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[2] / 'angio-gui' / 'run_headless.py'


def main(out_dir='experiments_output'):
    return subprocess.call([sys.executable, str(RUNNER), 'jem=2,4,8', 'sim_time=100',
                            '--name', 'jem_sweep', '--out', str(out_dir)])


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:2]))
