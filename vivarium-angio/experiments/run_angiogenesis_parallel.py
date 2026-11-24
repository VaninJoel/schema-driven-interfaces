"""Three angiogenesis runs at once, each through the headless runner.

Each run is a separate process (CompuCell3D keeps global state, so two
simulations cannot share an interpreter) started with
`angio-gui/run_headless.py`: the same specification check, run identity, logs
and status-typed COMBINE/OMEX archive as a run launched from the GUI, and its own
directory and Zarr store.

(An earlier version of this script called the Vivarium engine directly and let
all three runs write to the default `temp_store.zarr`; their snapshots
interleaved, two thirds were dropped without an error, and the script still
reported success. The process now refuses a store that already holds a run.)

    python run_angiogenesis_parallel.py [output_dir]
"""
import subprocess
import sys
import time
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[2] / 'angio-gui' / 'run_headless.py'
RUNS = {'jem_2_run': 2.0, 'jem_4_run': 4.0, 'jem_8_run': 8.0}


def main(out_dir='experiments_output'):
    print(f"Launching {len(RUNS)} runs in parallel (EC-medium adhesion jem = "
          f"{', '.join(str(v) for v in RUNS.values())}), 100 MCS each...")
    start = time.time()
    procs = {name: subprocess.Popen(
        [sys.executable, str(RUNNER), f'jem={jem}', 'sim_time=100', '--name', name,
         '--out', str(out_dir), '--no-report'])
        for name, jem in RUNS.items()}
    codes = {name: p.wait() for name, p in procs.items()}
    print(f"\nFinished in {time.time() - start:.1f} s")
    for name, code in codes.items():
        print(f"  {name}: {'succeeded' if code == 0 else f'FAILED (exit {code})'}")
    print(f"\nEach run has its own folder under {Path(out_dir).resolve()}:")
    print("  <name>_<timestamp>/<name>/  data.zarr, run_metadata.json, logs/, <name>.omex")
    return 0 if all(code == 0 for code in codes.values()) else 1


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:2]))
