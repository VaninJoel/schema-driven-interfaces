"""Cluster and perimeter measures on the model's periodic lattice.

The model declares periodic boundaries in x and y, so its network measures must
not depend on where the coordinate origin lies, and a site is on the network
boundary only if it touches medium.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pytest

from vivarium_angio.utils import network_metrics as nm
from vivarium_angio.utils import omex_generator as og

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT.parent / 'angio-gui'))


def _field(sites, shape=(5, 5)):
    m = np.zeros(shape, dtype=bool)
    for s in sites:
        m[s] = True
    return m


def test_two_sites_touching_across_a_periodic_edge_are_one_cluster():
    across = _field([(0, 2), (4, 2)])            # neighbours through the x edge
    assert nm.cluster_sizes(across) == [2]
    assert nm.cluster_sizes(np.roll(across, 1, axis=0)) == [2]   # same field, shifted
    # The cropped-image statistic, when asked for explicitly, still splits them.
    assert sorted(nm.cluster_sizes(across, periodic=(False, False))) == [1, 1]


@pytest.mark.parametrize('axis', [0, 1])
def test_cluster_count_does_not_depend_on_the_coordinate_origin(axis):
    rng = np.random.default_rng(3)
    field = rng.random((12, 9)) < 0.45
    expected = sorted(nm.cluster_sizes(field))
    for shift in range(field.shape[axis]):
        assert sorted(nm.cluster_sizes(np.roll(field, shift, axis=axis))) == expected


def test_periodicity_is_per_axis():
    across_y = _field([(2, 0), (2, 4)])
    assert nm.cluster_sizes(across_y, periodic=(True, False)) == [1, 1]
    assert nm.cluster_sizes(across_y, periodic=(False, True)) == [2]


def test_wrapping_merges_chains_of_clusters():
    # Three separate pieces in the cropped image, one cluster on the torus.
    field = _field([(0, 0), (4, 0), (4, 4), (0, 4)])
    assert nm.cluster_sizes(field) == [4]


def test_fully_occupied_periodic_lattice_has_no_boundary():
    full = np.ones((5, 5, 1), dtype=bool)
    assert nm.network_perimeter(full) == 0
    assert nm.network_perimeter(full, periodic=(False, False)) == 16   # the image rim


def test_perimeter_of_a_known_shape():
    block = np.zeros((7, 7), dtype=bool)
    block[2:5, 2:5] = True                        # 3 x 3 block: 8 rim sites, 1 interior
    assert nm.network_perimeter(block) == 8
    assert nm.network_perimeter(np.roll(block, (3, 3), axis=(0, 1))) == 8   # across the edges
    stripe = np.zeros((6, 6), dtype=bool)
    stripe[:, 2:4] = True                         # a band wrapping in x: both rows touch medium
    assert nm.network_perimeter(stripe) == 12
    stripe[:, 1:5] = True                         # 4 wide: the two inner rows are interior
    assert nm.network_perimeter(stripe) == 12


def test_empty_field():
    empty = np.zeros((5, 5), dtype=bool)
    assert nm.cluster_sizes(empty) == [] and nm.network_perimeter(empty) == 0


def test_gui_and_exporter_agree_on_the_same_trajectory(tmp_path):
    """One definition: the GUI analysis and the archive's metrics.csv must give
    the same cluster numbers for the same stored state."""
    import pandas as pd
    import zarr
    from gui.analysis_utils import compute_network_metrics

    rng = np.random.default_rng(11)
    store = zarr.open(str(tmp_path / 'data.zarr'), mode='w')
    fields = {}
    for step in (0, 10, 20):
        a = np.zeros((16, 16, 1, 3))
        a[..., 0, 0] = rng.random((16, 16)) < 0.4
        a[0, 5, 0, 0] = a[15, 5, 0, 0] = 1            # a pair across the x edge
        a[..., 2] = 0.25
        store.require_group(str(step))['data'] = a
        fields[step] = a[..., 0]

    csv = pd.read_csv(io.StringIO(og.extract_zarr_metrics(tmp_path / 'data.zarr')))
    for _, row in csv.iterrows():
        gui = compute_network_metrics(fields[int(row['Time'])])
        assert gui['num_clusters'] == row['num_clusters']
        assert gui['largest_cluster_size'] == row['largest_cluster_size']
        assert gui['cell_density'] == pytest.approx(row['cell_density'], abs=1e-6)
        assert 0 < gui['network_perimeter'] <= gui['total_ec_pixels']


# ---- the remaining morphology measures, on shapes with known answers -----------
def test_compactness_is_the_interior_fraction_and_stays_in_range():
    block = np.zeros((9, 9), dtype=bool)
    block[2:7, 2:7] = True                        # 5 x 5: 16 rim sites, 9 interior
    assert nm.compactness(block) == pytest.approx(9 / 25)
    cord = np.zeros((9, 9), dtype=bool)
    cord[4, 1:8] = True                           # one site wide: all boundary
    assert nm.compactness(cord) == 0.0
    assert nm.compactness(np.ones((5, 5), dtype=bool)) == 1.0     # no boundary at all
    assert np.isnan(nm.compactness(np.zeros((5, 5), dtype=bool)))
    rng = np.random.default_rng(5)
    for _ in range(20):
        assert 0.0 <= nm.compactness(rng.random((15, 15)) < rng.random()) <= 1.0


def test_gui_metrics_on_a_field_with_known_answers():
    from gui.analysis_utils import compute_network_metrics, metric_label, metric_definition
    field = np.zeros((10, 10, 1))
    field[1:4, 1:4, 0] = 1                        # 3 x 3 block: 9 sites, 8 on the rim
    field[7, 7, 0] = 1                            # and a single site
    m = compute_network_metrics(field)
    assert list(m) == list(nm.NETWORK_METRIC_KEYS)
    assert m['total_ec_pixels'] == 10 and m['cell_density'] == pytest.approx(0.10)
    assert m['num_clusters'] == 2 and m['largest_cluster_size'] == 9
    assert m['mean_cluster_size'] == pytest.approx(5.0)
    assert m['fragmentation_index'] == pytest.approx(2 / 10)
    assert m['connectivity_index'] == pytest.approx(9 / 10)
    assert m['network_perimeter'] == 9 and m['compactness'] == pytest.approx(1 / 10)
    # The key set is the same for an empty field, so exported columns cannot shift.
    empty = compute_network_metrics(np.zeros((10, 10, 1)))
    assert list(empty) == list(m) and np.isnan(empty['compactness'])
    assert empty['num_clusters'] == 0 and empty['network_perimeter'] == 0
    # Every reported metric has a unit and a definition to show beside it.
    for key in nm.NETWORK_METRIC_KEYS:
        assert '(' in metric_label(key) and metric_definition(key)


# ---- only completed runs, and only true replicates, enter the statistics --------
def _run_dir(root, name, status, rows=4, last_step=10, **params):
    import json
    import zarr
    d = root / name
    d.mkdir(parents=True)
    store = zarr.open(str(d / 'data.zarr'), mode='w')
    for step in range(10, last_step + 1, 10):
        a = np.zeros((12, 12, 1, 3))
        a[:rows, :, 0, 0] = 1
        store.require_group(str(step))['data'] = a
    if status is not None:
        (d / 'run_metadata.json').write_text(json.dumps(
            {'simulation_status': status, 'parameters': {'lchem': 500.0, 'random_seed': 1, **params}}))
    return d


def test_only_a_run_recorded_as_completed_can_be_analysed(tmp_path):
    from gui.analysis_utils import completed_run_problem
    assert completed_run_problem(_run_dir(tmp_path, 'ok', 'success')) is None
    for status in ('failed', 'timed_out', 'cancelled'):
        assert status in completed_run_problem(_run_dir(tmp_path, status, status))
    assert 'no run record' in completed_run_problem(_run_dir(tmp_path, 'unrecorded', None))
    (tmp_path / 'empty').mkdir()
    assert completed_run_problem(tmp_path / 'empty') == 'no data.zarr'


def test_replicate_statistics_need_equal_parameters_and_a_common_final_step(tmp_path):
    from gui.analysis_utils import ExperimentData, replicate_set_problem
    a = ExperimentData(_run_dir(tmp_path, 'a', 'success', last_step=30))
    b = ExperimentData(_run_dir(tmp_path, 'b', 'success', last_step=30, random_seed=2))
    assert replicate_set_problem([a, b]) is None          # differ in seed only
    short = ExperimentData(_run_dir(tmp_path, 'short', 'success', last_step=20))
    assert 'different steps' in replicate_set_problem([a, short])
    other = ExperimentData(_run_dir(tmp_path, 'other', 'success', last_step=30, lchem=100.0))
    assert 'lchem' in replicate_set_problem([a, other])
