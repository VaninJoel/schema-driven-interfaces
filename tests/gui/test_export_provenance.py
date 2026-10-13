"""Exported figures, tables and animations name the runs they came from
(requirement 2.5.2): a <file>.provenance.json sidecar, plus the record embedded
in PNG metadata, for every export path — explicit export buttons and the
matplotlib toolbar's save alike (both go through figure.savefig).
"""
import json

import pytest

from harness import load_gui


def _run_dir(path, run_id, seed):
    path.mkdir(parents=True)
    (path / 'run_metadata.json').write_text(json.dumps({
        'run_id': run_id, 'simulation_status': 'success', 'random_seed': seed,
        'schema_fingerprint': 'sha256:abc',
        'provenance': {'code': {'source': 'git', 'commit': 'deadbeef', 'dirty': False}}}))
    (path / f'{path.name}.omex').write_bytes(b'')
    return path


@pytest.mark.parametrize('gui_name', ['angio', 'vcornea'])
def test_savefig_writes_sidecar_and_png_metadata(qapp, tmp_path, gui_name):
    load_gui(gui_name)
    import export_provenance as ep
    from matplotlib.figure import Figure
    from PIL import Image

    runs = [_run_dir(tmp_path / 'r1', 'id-1', 11), _run_dir(tmp_path / 'r2', 'id-2', 22)]
    fig = Figure()
    fig.add_subplot().plot([0, 1], [0, 1])
    ep.attach_to_figure(fig, lambda: ep.build_record(runs, f'{gui_name} test', {'view': 'x'}))
    out = tmp_path / 'plot.png'
    fig.savefig(out)                      # what the toolbar's save button calls

    sidecar = json.loads((tmp_path / 'plot.png.provenance.json').read_text())
    assert [r['run_id'] for r in sidecar['source_runs']] == ['id-1', 'id-2']
    assert [r['random_seed'] for r in sidecar['source_runs']] == [11, 22]
    assert sidecar['source_runs'][0]['archive'] == 'r1.omex'
    assert sidecar['source_runs'][0]['code']['commit'] == 'deadbeef'
    embedded = json.loads(Image.open(out).info['Description'])
    assert embedded['source_runs'] == sidecar['source_runs']


def test_vcornea_plot_panel_records_the_runs_behind_the_plot(qapp, tmp_path):
    load_gui('vcornea')
    import analysis_data
    from analysis_plot_panel import PlotPanel

    exp = tmp_path / 'exp'
    for combo, rid in (('combo_001', 'a'), ('combo_002', 'b')):
        d = _run_dir(exp / combo / 'replicate_1', rid, 1)
        (d / 'cell_count_240.csv').write_text('Time,Superficial,Wing,Basal,Stem\n0,1,2,3,4\n24,2,3,4,5\n')
    ds = analysis_data.AnalysisDataset(exp)
    panel = PlotPanel(ds, 'count')

    panel.figure.savefig(tmp_path / 'paper.png')          # paper style: one combination
    one = json.loads((tmp_path / 'paper.png.provenance.json').read_text())
    assert [r['run_id'] for r in one['source_runs']] == ['a']

    panel.family.setCurrentText('Enhanced')
    panel.mode.setCurrentText('Comparison')                 # compares all combinations
    panel.figure.savefig(tmp_path / 'compare.png')
    both = json.loads((tmp_path / 'compare.png.provenance.json').read_text())
    assert sorted(r['run_id'] for r in both['source_runs']) == ['a', 'b']
    assert both['view']['mode'] == 'comparison'
