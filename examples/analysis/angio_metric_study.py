"""Shape and size measures of the Angio-GUI example sweep, from the run archives.

    python examples/analysis/angio_metric_study.py            # rewrites the two tables
    python examples/analysis/angio_metric_study.py --check    # compares with the stored tables

Reads only the .omex archives in examples/angio-gui_lchem_sweep (the Zarr
trajectory packed under zarr/ in each) and writes, beside this script:

  angio_metric_study.csv          one row per run and recorded step
  angio_metric_study_summary.csv  final step, mean and SD per chemotaxis strength

The measures use the package's own lattice functions
(vivarium_angio.utils.network_metrics, periodic boundaries, 4-neighbour
connectivity). The application itself writes only some of them to metrics.csv;
the rest are computed here.

Columns
  n_cells                       distinct cell ids on the lattice
  mean_cell_area                endothelial sites / n_cells (target area 50 sites)
  density                       endothelial sites / lattice sites
  clusters                      connected components of endothelial sites
  largest_cluster_frac          largest cluster / endothelial sites
  medium_components             connected components of medium (non-cell) sites
  medium_components_ge50        those of at least 50 sites (one target cell area)
  mean_medium_component_area    mean size of a medium component (sites)
  largest_medium_component_frac largest medium component / medium sites
  interior_frac                 1 - boundary sites / endothelial sites; the report's "compactness"
  cord_halfwidth                endothelial sites per boundary site

The medium components are NOT vascular lacunae. These runs last 100 Monte Carlo
steps; the components are the gaps left between cells that are still
aggregating, and nearly all the medium is one connected region.
"""
from __future__ import annotations

import json
import sys
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from vivarium_angio.utils import network_metrics as nm
from vivarium_angio.utils import omex_generator as og

HERE = Path(__file__).resolve().parent
SWEEP = HERE.parent / 'angio-gui_lchem_sweep'
TABLE = HERE / 'angio_metric_study.csv'
SUMMARY = HERE / 'angio_metric_study_summary.csv'


def measures(frame) -> dict:
    """The measures of one recorded lattice state (x, y, 1, channel)."""
    cell_type, cell_id = frame[..., 0, 0], frame[..., 0, 1]
    ec = cell_type > 0
    n_ec = int(ec.sum())
    clusters = nm.cluster_sizes(ec)
    medium = nm.cluster_sizes(~ec)
    boundary = nm.network_perimeter(ec)
    n_cells = len(np.unique(cell_id[ec]))
    return {
        'n_cells': n_cells,
        'mean_cell_area': n_ec / n_cells if n_cells else np.nan,
        'density': n_ec / ec.size,
        'clusters': len(clusters),
        'largest_cluster_frac': max(clusters) / n_ec if clusters else np.nan,
        'medium_components': len(medium),
        'medium_components_ge50': sum(1 for s in medium if s >= 50),
        'mean_medium_component_area': float(np.mean(medium)) if medium else np.nan,
        'largest_medium_component_frac': max(medium) / (~ec).sum() if medium else np.nan,
        'interior_frac': 1 - boundary / n_ec if n_ec else np.nan,
        'cord_halfwidth': n_ec / boundary if boundary else np.nan,
    }


def study(sweep: Path = SWEEP) -> pd.DataFrame:
    rows = []
    archives = sorted(p for p in sweep.glob('*/*.omex') if p.stem == p.parent.name)
    for omex in archives:
        with zipfile.ZipFile(omex) as zf:
            lchem = json.loads(zf.read('sim_params.json')).get('lchem')
        with tempfile.TemporaryDirectory(prefix='angio_study_', ignore_cleanup_errors=True) as tmp:
            store = og.extract_archive_zarr(omex, tmp)
            for step, data in og._load_zarr_steps(store, strict=True):
                rows.append({'run': omex.stem, 'lchem': lchem, 'step': int(step),
                             **measures(np.asarray(data))})
    return pd.DataFrame(rows).sort_values(['run', 'step']).reset_index(drop=True)


def summarise(table: pd.DataFrame) -> pd.DataFrame:
    final = table[table['step'] == table['step'].max()]
    cols = [c for c in table.columns if c not in ('run', 'lchem', 'step')]
    out = final.groupby('lchem')[cols].agg(['mean', 'std'])
    out.columns = [f'{c}_{stat}' for c, stat in out.columns]
    out.insert(0, 'n_runs', final.groupby('lchem').size())
    out.insert(1, 'step', int(table['step'].max()))
    return out.reset_index()


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    table = study()
    summary = summarise(table)
    if '--check' in argv:
        stored = pd.read_csv(TABLE)
        pd.testing.assert_frame_equal(table, stored, check_exact=False, rtol=1e-12, atol=1e-12)
        pd.testing.assert_frame_equal(summary, pd.read_csv(SUMMARY), check_exact=False,
                                      rtol=1e-12, atol=1e-12, check_dtype=False)
        print(f'{TABLE.name} and {SUMMARY.name} match the archives '
              f'({table["run"].nunique()} runs, {len(table)} rows)')
        return 0
    table.to_csv(TABLE, index=False, lineterminator='\n')
    summary.to_csv(SUMMARY, index=False, lineterminator='\n')
    print(f'wrote {TABLE.name} ({table["run"].nunique()} runs, {len(table)} rows) and {SUMMARY.name}')
    show = summary.set_index('lchem')[['n_cells_mean', 'mean_cell_area_mean', 'density_mean',
                                       'clusters_mean', 'interior_frac_mean']]
    print(show.round(4).to_string())
    return 0


if __name__ == '__main__':
    sys.exit(main())
