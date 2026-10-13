"""The supplementary schema tables (S1/S2) are generated from the code and must
match it: a schema edit without regenerating the tables fails here.

    Regenerate:  python docs/supplementary/generate_schema_tables.py
"""
import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

GEN = Path(__file__).resolve().parents[1] / 'docs' / 'supplementary' / 'generate_schema_tables.py'


@pytest.fixture(scope='module')
def gen():
    spec = importlib.util.spec_from_file_location('generate_schema_tables', GEN)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_committed_tables_match_the_schemas(gen):
    stale = gen.stale_files()
    assert not stale, (f"{stale} are out of date with the schemas; regenerate with "
                       "`python docs/supplementary/generate_schema_tables.py`")


def test_check_detects_a_stale_table(gen, tmp_path):
    for name in gen.render_all():
        shutil.copy(GEN.parent / name, tmp_path / name)
    target = tmp_path / 'S2_vcornea_parameter_schema.md'
    target.write_text(target.read_text(encoding='utf-8').replace('voxel^2/MCS', 'µm²/min'),
                      encoding='utf-8')
    assert gen.stale_files(tmp_path) == ['S2_vcornea_parameter_schema.md']


def test_tables_carry_the_running_fingerprint(gen):
    from vivarium_angio.processes.angiogenesis_process import AngiogenesisProcess
    from vivarium_angio.utils.provenance import schema_fingerprint
    fp = schema_fingerprint(AngiogenesisProcess().ports_schema())
    assert f"`{fp}`" in (GEN.parent / 'S1_angio_parameter_schema.md').read_text(encoding='utf-8')
