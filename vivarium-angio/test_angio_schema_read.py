"""Reading the schema must not start a simulation.

The GUI constructs AngiogenesisProcess only to read ports_schema() and
PRESETS. That used to start a full CC3D simulation inside the GUI process and
write a stray temp_store.zarr into the working directory.

Run:  conda run -n vc --no-capture-output pytest vivarium-angio/test_angio_schema_read.py -v
"""
from vivarium_angio.processes.angiogenesis_process import AngiogenesisProcess


def test_constructing_for_the_schema_starts_no_simulation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    proc = AngiogenesisProcess()
    schema = proc.ports_schema()
    assert schema['inputs'] and proc.PRESETS
    assert proc.core_sim is None
    assert list(tmp_path.iterdir()) == []      # no temp_store.zarr, nothing written
    proc.finish()                               # never stepped: a no-op, no archive
    assert list(tmp_path.iterdir()) == []
