"""The manuscript's tables are generated from the schemas and cannot drift from them.

Supplementary Tables S1 and S2 (one row per exposed parameter), Table 1 and
Supplementary Table S3 (the field list with per-model coverage) are written by the
generators under docs/. These tests fail when a committed table no longer matches
what its generator produces from the current code — for instance after a schema
edit, or a change to how a range's basis is worded.

To refresh after an intended change:
    python docs/supplementary/generate_schema_tables.py
    python docs/tables/generate_table1.py
"""
import csv
import importlib.util
import io
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[1] / 'docs'


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module')
def schema_tables():
    return _load(DOCS / 'supplementary' / 'generate_schema_tables.py', 'sdi_generate_schema_tables')


@pytest.fixture(scope='module')
def table1():
    return _load(DOCS / 'tables' / 'generate_table1.py', 'sdi_generate_table1')


def test_supplementary_schema_tables_match_the_schemas(schema_tables):
    assert schema_tables.stale_files() == []


def test_table1_and_field_coverage_match_the_schemas(table1):
    assert table1.stale_files() == []


def test_tables_carry_the_fingerprint_every_run_records(schema_tables):
    from vivarium_angio.processes.angiogenesis_process import AngiogenesisProcess
    from vivarium_angio.utils.provenance import schema_fingerprint as angio_fp
    from vivarium_vcornea.processes.vcornea_process import VCorneaProcess
    from vivarium_vcornea.utils.provenance import schema_fingerprint as vcornea_fp
    angio = angio_fp(AngiogenesisProcess.__new__(AngiogenesisProcess).ports_schema())
    vcornea = vcornea_fp(VCorneaProcess({}).ports_schema())
    s1 = (DOCS / 'supplementary' / 'S1_angio_parameter_schema.md').read_text(encoding='utf-8')
    s2 = (DOCS / 'supplementary' / 'S2_vcornea_parameter_schema.md').read_text(encoding='utf-8')
    assert angio in s1 and vcornea in s2 and angio != vcornea


def test_one_row_per_exposed_parameter():
    from vivarium_angio.processes.angiogenesis_process import AngiogenesisProcess
    from vivarium_vcornea.processes.vcornea_process import VCorneaProcess
    for stem, inputs in (
            ('S1_angio_parameter_schema',
             AngiogenesisProcess.__new__(AngiogenesisProcess).ports_schema()['inputs']),
            ('S2_vcornea_parameter_schema', VCorneaProcess({}).ports_schema()['inputs'])):
        text = (DOCS / 'supplementary' / f'{stem}.csv').read_text(encoding='utf-8')
        rows = list(csv.DictReader(io.StringIO(
            '\n'.join(l for l in text.splitlines() if not l.startswith('#')))))
        assert sorted(r['parameter'] for r in rows) == sorted(inputs)
