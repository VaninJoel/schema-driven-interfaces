"""Which imports or calls make a Python process end abnormally on this machine?

Each probe runs in its own interpreter with faulthandler on; the exit code and
the last lines of stderr are printed. Used to find out why some processes
crash at exit on Linux after writing correct results.
"""
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
work = Path(sys.argv[1]).resolve()
work.mkdir(parents=True, exist_ok=True)
archive = (REPO / 'examples' / 'vcornea_sls_sweep' / 'vcornea_sls_sweep_combo001'
           / 'replicate_1' / 'vcornea_sls_sweep_combo001.omex')
with zipfile.ZipFile(archive) as zf:
    zf.extractall(work / 'vc', [n for n in zf.namelist() if '/' not in n])
pq = work / 'vc' / 'thickness_rep_7201.parquet'
csv = work / 'vc' / 'cell_count_7201.csv'
replay = REPO / 'examples' / 'reexecution' / 'vcornea_combo001_rep1_30day_replay'

PROBES = {
    'import pandas': "import pandas",
    'import pyarrow': "import pyarrow",
    'import pyarrow.parquet': "import pyarrow.parquet",
    'import fastparquet': "import fastparquet",
    'read_csv': f"import pandas as pd; print(len(pd.read_csv(r'{csv}')))",
    'read_parquet (default engine)': f"import pandas as pd; print(len(pd.read_parquet(r'{pq}')))",
    'read_parquet (pyarrow)': f"import pandas as pd; print(len(pd.read_parquet(r'{pq}', engine='pyarrow')))",
    'read_parquet (fastparquet)': f"import pandas as pd; print(len(pd.read_parquet(r'{pq}', engine='fastparquet')))",
    'read_parquet (pyarrow, threads off)': (
        f"import pyarrow as pa; pa.set_cpu_count(1); pa.set_io_thread_count(1); "
        f"import pandas as pd; print(len(pd.read_parquet(r'{pq}', engine='pyarrow', use_threads=False)))"),
    'pyarrow.parquet.read_table': f"import pyarrow.parquet as q; print(q.read_table(r'{pq}').num_rows)",
    'import cc3d': "import cc3d",
    'import cc3d then pandas parquet': f"import cc3d; import pandas as pd; print(len(pd.read_parquet(r'{pq}')))",
    'import numpy, scipy': "import numpy, scipy.stats",
    'import zarr': "import zarr",
}
print(sys.version)
for name, code in PROBES.items():
    done = subprocess.run([sys.executable, '-X', 'faulthandler', '-c', code],
                          capture_output=True, text=True)
    tail = ' | '.join(l for l in done.stderr.strip().splitlines()[-6:])
    print(f"{done.returncode:>4}  {name:38s} {done.stdout.strip()[:20]:20s} {tail[:500]}", flush=True)

done = subprocess.run([sys.executable, '-X', 'faulthandler',
                       str(REPO / 'vivarium-vcornea' / 'compare_replay.py'),
                       str(work / 'vc'), str(replay), '7201'], capture_output=True, text=True)
print(f"{done.returncode:>4}  compare_replay.py on the stored 30-day replay tables")
print(done.stdout[-600:])
print(done.stderr[-1500:])


# ---- one real V-Cornea day through the wrapper: how does the simulator process end?
print('\n=== V-Cornea, one day through VCorneaProcess', flush=True)
probe = r'''
import json, sys
from pathlib import Path
from vivarium_vcornea.processes.vcornea_process import VCorneaProcess
out = Path(sys.argv[1])
proc = VCorneaProcess({'output_base_dir': str(out), 'SimTime': 1, 'replicates': 1,
                       'random_seed': 20261124, 'IsInjury': False})
states = {'inputs': {k: v['_default'] for k, v in proc.ports_schema()['inputs'].items()}}
[rep] = proc.next_update(1, states)['outputs']['replicate_results']
d = Path(rep['output_directory'])
print('STATUS', rep['status'], '|', (rep.get('error_message') or '')[:300])
print('FILES', sorted(p.name for p in d.iterdir()))
for name in ('stderr.log', 'stdout.log'):
    for p in d.rglob(name):
        print('-----', p.relative_to(d), '(last lines)')
        print('\n'.join(p.read_text(errors='replace').splitlines()[-25:]))
'''
done = subprocess.run([sys.executable, '-X', 'faulthandler', '-c', probe, str(work / 'wrapper')],
                      capture_output=True, text=True)
keep = [l for l in done.stdout.splitlines() if l.startswith(('STATUS', 'FILES', '-----'))
        or 'rror' in l or 'ault' in l or 'Thread' in l or 'File "' in l or 'RUNTIME' in l]
print('\n'.join(keep[-60:]))
print(done.stdout[-2500:])
print(done.stderr[-1500:])

# ---- the same day with stock CompuCell3D, three times: exit status each time
print('\n=== stock CompuCell3D, repeated', flush=True)
import re, shutil
src = work / 'stock_src'
with zipfile.ZipFile(archive) as zf:
    zf.extractall(src, [n for n in zf.namelist() if n.startswith('model/')])
pfile = src / 'model' / 'Simulation' / 'Parameters.py'
pfile.write_text(re.sub(r'^SimTime=7200$', 'SimTime=60', pfile.read_text(), flags=re.M))
for i in range(3):
    d = work / f'stock{i}'
    shutil.copytree(src, d)
    r = subprocess.run([sys.executable, '-X', 'faulthandler', '-m', 'cc3d.run_script', '-i',
                        'model/vCornea_v2.cc3d', '-o', str(d / 'out')], cwd=d,
                       capture_output=True, text=True)
    wrote = sorted(p.name for p in (d / 'model' / 'Simulation').glob('*_61.*'))
    print(f'run {i}: exit {r.returncode}; tables written: {wrote}')
    if r.returncode != 0:
        print(r.stderr[-1800:])
