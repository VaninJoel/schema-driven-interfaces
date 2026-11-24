"""Compare the tables of a V-Cornea replay with the archived ones.

    python vivarium-vcornea/compare_replay.py <unpacked archive> <replay Simulation dir> <final step of the replay>

A replay shorter than the archived run is compared over the period it covers.
"""
import sys
from pathlib import Path

import pandas as pd

archive, replay, mcs = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])


def read(p):
    return pd.read_parquet(p) if p.suffix == '.parquet' else pd.read_csv(p)


ok = True
for stem in ('cell_count', 'surfactant', 'thickness_rep'):
    [a] = list(archive.glob(f'{stem}_*.*'))
    [r] = list(replay.glob(f'{stem}_{mcs}.*'))
    A, R = read(a), read(r)
    # hours covered by the replay: the final step itself is one past the period
    last = R['Time'].max()
    Aw = A[A['Time'] <= last].reset_index(drop=True)
    R = R.reset_index(drop=True)
    same = Aw.shape == R.shape and Aw.equals(R)
    ok &= same
    print(f"{stem}: archived {a.name} {len(A)} rows; replay {r.name} {len(R)} rows up to "
          f"{last:g} h; archived rows in that period {len(Aw)}; identical: {same}")
    if not same and Aw.shape == R.shape:
        diff = (Aw != R).any(axis=1)
        print('   first differing row:', int(diff.idxmax()), Aw[diff].head(1).to_dict('records'),
              R[diff].head(1).to_dict('records'))
print('ALL IDENTICAL' if ok else 'DIFFERENCES FOUND')
