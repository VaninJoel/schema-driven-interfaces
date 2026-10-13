"""Manuscript Table 2 (docs/tables) is generated from the descriptor format and
the live schemas; a change to either without regenerating the table fails here.

    Regenerate:  python docs/tables/generate_table2.py
"""
import importlib.util
import sys
from pathlib import Path

GEN = Path(__file__).resolve().parents[1] / 'docs' / 'tables' / 'generate_table2.py'


def _gen():
    spec = importlib.util.spec_from_file_location('generate_table2', GEN)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_table2_matches_the_format_and_schemas():
    stale = _gen().stale_files()
    assert not stale, (f"{stale} out of date; regenerate with "
                       "`python docs/tables/generate_table2.py`")


def test_every_format_field_has_a_documented_meaning():
    gen = _gen()
    meanings = gen.field_meanings()
    missing = [f for g in gen.field_groups().values()
               for f in g['required'] + g['optional'] if f not in meanings]
    assert not missing, f"fields without a meaning in parameter_descriptor_format.md: {missing}"
