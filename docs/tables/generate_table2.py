"""Generate manuscript Table 2 (the fields of a schema parameter entry) from the code.

    python docs/tables/generate_table2.py          # (re)write table2.md, table2_full.md
    python docs/tables/generate_table2.py --check  # exit 1 if stale

Sources, so the table cannot drift from the software:
  * fields and groups:  FIELD_GROUPS in docs/parameter_descriptor_example.py (the
    list the descriptor tests check both schemas against);
  * field meanings:     the field tables in docs/parameter_descriptor_format.md;
  * example values:     the live Angio-GUI entry for VEGF diffusion (`vedir`), and
                        V-Cornea's `EGF_SUPERDiffCoef` for unit conversion, which
                        the Angio model does not use;
  * coverage:           how many parameters of each model populate each field.

table2.md is the compact main-text table (one row per field group);
table2_full.md lists every field with its meaning, example and coverage (a
candidate supplementary table). tests/test_table2.py fails when either is stale.
"""
from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DOCS = HERE.parent
sys.path.insert(0, str(DOCS / 'supplementary'))

EXAMPLE = ('angio', 'vedir')
CONVERSION_EXAMPLE = ('vcornea', 'EGF_SUPERDiffCoef')

GROUP_TITLES = {
    'execution contract': ('Execution contract', 'what the simulator receives'),
    'identity and meaning': ('Identity and meaning', 'what the parameter is (developer → operator)'),
    'units': ('Units', 'what the stored number means'),
    'admissible and supported values': ('Admissible and supported values',
                                        'what the implementation accepts and what the evidence supports'),
    'relationships and expected effect': ('Relationships and expected effect',
                                          'what else it interacts with, and how changing it should act'),
    'evidence': ('Evidence', 'where the default came from (run → auditor)'),
    'presentation': ('Presentation', 'how the GUI shows it; never affects execution'),
}

# Fields whose values the compact table shows for each group (from the example entry).
COMPACT_EXAMPLES = {
    'execution contract': ['_default', '_scope', '_parameter_type'],
    'identity and meaning': ['_display_name', '_category', '_expert_level', '_ontology_term'],
    'units': ['_unit', '_dimension'],
    'admissible and supported values': ['_mathematical_range', '_physiological_range',
                                        '_recommended_range', '_range_evidence'],
    'relationships and expected effect': ['_dependencies', '_expected_behavior'],
    'evidence': ['_reference_paper', '_fitting_method', '_experimental_assay'],
    # _gui_hints is left out on purpose: vedir's hint asks for a slider, but the Angio
    # GUI renders float parameters as text fields (Figure 2B), so the example would
    # contradict the figure.
    'presentation': [],
}


# ---------------------------------------------------------------- sources
def field_groups():
    spec = importlib.util.spec_from_file_location(
        'descriptor_example', DOCS / 'parameter_descriptor_example.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.FIELD_GROUPS


def field_meanings():
    """{field: meaning} from the 3-column field tables of the format document."""
    meanings = {}
    for line in (DOCS / 'parameter_descriptor_format.md').read_text(encoding='utf-8').splitlines():
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if len(cells) != 3 or not cells[0].startswith('`_'):
            continue
        for name in re.findall(r'`(_\w+)`', cells[0]):
            meanings.setdefault(name, cells[2])
    return meanings


def schemas():
    import generate_schema_tables as gst          # reuses its model loader
    out = {}
    for model in gst.MODELS.values():
        schema, _audit, _audit_mod, fingerprint, units = gst._load(model)
        key = 'angio' if model['package'] == 'vivarium_angio' else 'vcornea'
        params = {k: v for k, v in schema['inputs'].items()
                  if isinstance(v, dict) and '_default' in v}
        out[key] = {'params': params, 'fingerprint': fingerprint, 'units': units}
    return out


# ---------------------------------------------------------------- formatting
def _populated(v):
    return v is not None and v != [] and v != {} and v != ''


def _populated_field(info, field):
    v = info.get(field)
    if field == '_range_evidence':
        return isinstance(v, dict) and any(isinstance(e, dict) and e.get('basis') for e in v.values())
    return field in info and _populated(v)


def _short(text, n):
    """Shorten at a word boundary."""
    text = ' '.join(str(text).split())
    if len(text) <= n:
        return text
    cut = text[:n - 1].rsplit(' ', 1)[0].rstrip(' ,;:')
    return cut + ' …'


def _value(field, v, n=60):
    if field == '_range_evidence':
        return ' / '.join(f"{t}: {e.get('basis')}" for t, e in v.items() if isinstance(e, dict))
    if field == '_reference_paper':
        return _short(f"source: {v.get('source')}; value: {v.get('value')}", n)
    if field == '_expected_behavior':
        return _short(f"low: {v.get('low_value')}; high: {v.get('high_value')}", n)
    if field == '_dependencies':
        k, why = next(iter(v.items()))
        return _short(f"{k}: {why}", n)
    if field == '_gui_hints':
        return _short(', '.join(f"{k}={x}" for k, x in v.items()), n)
    if isinstance(v, tuple):
        return f"({', '.join(str(x) for x in v)})"
    if isinstance(v, str):
        return f"'{_short(v, n)}'"
    return _short(repr(v), n)


def _md(text):
    return str(text).replace('|', '\\|')


# ---------------------------------------------------------------- tables
def _example_cell(data, field):
    model, name = EXAMPLE
    info = data[model]['params'][name]
    if _populated_field(info, field):
        return f"`{_md(_value(field, info[field]))}`"
    return '—'


def render_compact(groups, data):
    model, name = EXAMPLE
    vmodel, vname = CONVERSION_EXAMPLE
    vinfo = data[vmodel]['params'][vname]
    units = data[vmodel]['units']
    disp = units.display_unit_label(vinfo['_dimension'], vinfo.get('_display_unit'))
    shown = units.to_display(vinfo['_default'], vinfo['_dimension'], vinfo.get('_display_unit'))
    out = [
        "# Table 2. Fields of a process-schema parameter entry, grouped by the handoff they serve",
        "",
        f"Example values are those of the Angio-GUI entry for VEGF diffusion (`{name}`) unless "
        f"marked VC (V-Cornea, `{vname}`). Required fields are in **bold**: they are present "
        "on every exposed parameter of both models (checked by the descriptor tests), but a "
        "value may be empty where the fact is not known. The full field list, with each "
        "field's meaning and how many parameters of each model actually populate it, is in "
        "`table2_full.md`.",
        "",
        "Generated by `docs/tables/generate_table2.py` from schema fingerprints "
        f"`{data['angio']['fingerprint']}` (Angio-GUI) and `{data['vcornea']['fingerprint']}` "
        "(V-Cornea). Do not edit by hand.",
        "",
        "| Group | Purpose | Fields | Example values |",
        "|---|---|---|---|",
    ]
    for g, spec in groups.items():
        title, purpose = GROUP_TITLES[g]
        used = [f for f in spec['optional']
                if any(_populated_field(i, f) for m in data.values() for i in m['params'].values())]
        fields = ', '.join([f"**`{f}`**" for f in spec['required']] + [f"`{f}`" for f in used])
        examples = []
        for f in COMPACT_EXAMPLES[g]:
            info = data[model]['params'][name]
            if _populated_field(info, f):
                examples.append(f"{f}: `{_md(_value(f, info[f], 70))}`")
        if g == 'units':
            examples.append(f"VC: stored `{vinfo['_default']} {vinfo['_unit']}`, shown as "
                            f"`{shown:.4g} {disp}`")
        out.append(f"| {title} | {_md(purpose)} | {fields} | {'<br>'.join(examples) or '—'} |")
    return '\n'.join(out) + '\n'


def render_full(groups, data, meanings):
    na, nv = len(data['angio']['params']), len(data['vcornea']['params'])
    out = [
        "# Fields of a process-schema parameter entry (full list)",
        "",
        "Every field of the common descriptor format, with its meaning (from "
        "`docs/parameter_descriptor_format.md`), an example value from the Angio-GUI "
        f"entry `{EXAMPLE[1]}`, and how many parameters of each model populate it "
        f"(Angio-GUI: {na} parameters, V-Cornea: {nv}). `_range_evidence` counts entries "
        "with at least one tier whose evidence basis is recorded.",
        "",
        "Generated by `docs/tables/generate_table2.py` from schema fingerprints "
        f"`{data['angio']['fingerprint']}` (Angio-GUI) and `{data['vcornea']['fingerprint']}` "
        "(V-Cornea). Do not edit by hand.",
        "",
        "| Group | Field | Req. | Meaning | Example (`vedir`) | Angio-GUI | V-Cornea |",
        "|---|---|---|---|---|---|---|",
    ]
    for g, spec in groups.items():
        title = GROUP_TITLES[g][0]
        for f in spec['required'] + spec['optional']:
            ca = sum(_populated_field(i, f) for i in data['angio']['params'].values())
            cv = sum(_populated_field(i, f) for i in data['vcornea']['params'].values())
            out.append(f"| {title} | `{f}` | {'yes' if f in spec['required'] else 'no'} | "
                       f"{_md(meanings.get(f, '—'))} | {_example_cell(data, f)} | "
                       f"{ca}/{na} | {cv}/{nv} |")
    return '\n'.join(out) + '\n'


def render_all():
    groups, meanings, data = field_groups(), field_meanings(), schemas()
    return {'table2.md': render_compact(groups, data),
            'table2_full.md': render_full(groups, data, meanings)}


def stale_files(out_dir=HERE):
    return [name for name, content in render_all().items()
            if not (Path(out_dir) / name).exists()
            or (Path(out_dir) / name).read_text(encoding='utf-8') != content]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--check', action='store_true', help='exit 1 if the tables are out of date')
    args = ap.parse_args(argv)
    if args.check:
        stale = stale_files()
        print("Out of date: " + ", ".join(stale) if stale else "Table 2 is up to date.")
        return 1 if stale else 0
    for name, content in render_all().items():
        (HERE / name).write_text(content, encoding='utf-8', newline='\n')
        print(f"wrote {name}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
