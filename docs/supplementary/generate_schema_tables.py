"""Generate the manuscript's supplementary parameter-schema tables from the code.

    python docs/supplementary/generate_schema_tables.py          # (re)write S1/S2
    python docs/supplementary/generate_schema_tables.py --check  # exit 1 if stale

S1 documents the Angio-GUI schema (AngiogenesisProcess.ports_schema()) and S2 the
V-Cornea schema (VCorneaProcess.ports_schema()): one row per exposed parameter,
as a readable Markdown table and as a CSV with every column (for the journal's
supplementary files).

The tables are generated, never hand-edited, so they cannot drift from the code:
each is stamped with the schema fingerprint (the same content hash every run
records), and tests/test_schema_supplement.py fails when the committed files no
longer match what this script produces. Ranges, positions and evidence are
phrased by the same functions the run audit uses (utils/parameter_audit.py), so
the supplement and a run's parameter_audit.json describe a parameter identically.

The output is deterministic: no timestamps or commit ids, only content derived
from the schema, so it changes exactly when the schema does.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import importlib
import io
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

MODELS = {
    'S1': {
        'package': 'vivarium_angio',
        'process': ('vivarium_angio.processes.angiogenesis_process', 'AngiogenesisProcess'),
        'title': 'Angio-GUI parameter schema (integrated pattern)',
        'source': '`AngiogenesisProcess.ports_schema()` in '
                  '`vivarium-angio/vivarium_angio/processes/angiogenesis_process.py`',
        'stem': 'S1_angio_parameter_schema',
    },
    'S2': {
        'package': 'vivarium_vcornea',
        'process': ('vivarium_vcornea.processes.vcornea_process', 'VCorneaProcess'),
        'title': 'V-Cornea parameter schema (decoupled pattern)',
        'source': '`VCorneaProcess.ports_schema()` in '
                  '`vivarium-vcornea/vivarium_vcornea/processes/vcornea_process.py`',
        'stem': 'S2_vcornea_parameter_schema',
    },
}

TIER_LABELS = {'mathematical': 'Admissible', 'physiological': 'Supported',
               'recommended': 'Recommended'}

CSV_COLUMNS = [
    'parameter', 'display_name', 'category', 'subcategory', 'expert_level',
    'parameter_type', 'description', 'stored_unit', 'dimension', 'default',
    'display_unit', 'display_default',
    'admissible_range', 'admissible_evidence', 'admissible_note',
    'supported_range', 'supported_evidence', 'supported_note',
    'recommended_range', 'recommended_evidence', 'recommended_note',
    'default_source', 'default_locator', 'fitting_method', 'literature',
    'ontology_term', 'measurable', 'experimental_assay', 'schema_fingerprint',
]


# ---------------------------------------------------------------- formatting
def _num(v):
    if isinstance(v, bool) or v is None:
        return '' if v is None else str(v)
    if isinstance(v, float):
        return f"{v:.6g}"
    return str(v)


def _range(r):
    if r is None:
        return ''
    try:
        lo, hi = r
    except (TypeError, ValueError):
        return str(r)
    return f"[{_num(lo)}, {_num(hi)}]"


def _one_line(text):
    return ' '.join(str(text or '').split())


def _locator(loc):
    """Locator values as the schema records them (they already say 'Table 2',
    'Eq. 10' or a code location), with page numbers marked."""
    if not isinstance(loc, dict):
        return _one_line(loc)
    parts = [_one_line(loc[k]) for k in ('table', 'figure', 'equation', 'section') if loc.get(k)]
    if loc.get('page'):
        parts.append(f"p. {loc['page']}")
    return ', '.join(parts)


# ---------------------------------------------------------------- rows
def _load(model):
    pkg = model['package']
    mod_name, cls_name = model['process']
    with contextlib.redirect_stdout(io.StringIO()):          # CC3D import chatter
        proc = getattr(importlib.import_module(mod_name), cls_name)()
        schema = proc.ports_schema()
    audit_mod = importlib.import_module(f'{pkg}.utils.parameter_audit')
    provenance = importlib.import_module(f'{pkg}.utils.provenance')
    try:
        units = importlib.import_module(f'{pkg}.utils.units')
    except ImportError:
        units = None                                         # Angio: no conversion layer
    defaults = {k: v['_default'] for k, v in schema['inputs'].items()
                if isinstance(v, dict) and '_default' in v}
    audit = audit_mod.build_parameter_audit(schema, defaults)
    return schema, audit, audit_mod, provenance.schema_fingerprint(schema), units


def build_rows(model):
    schema, audit, audit_mod, fingerprint, units = _load(model)
    rows = []
    for key, entry in audit['parameters'].items():
        info = schema['inputs'][key]
        display_unit = display_default = ''
        dim = info.get('_dimension')
        if units is not None and dim:
            du = info.get('_display_unit')
            if abs(units.factor(dim, du) - 1.0) > 1e-12:
                display_unit = units.display_unit_label(dim, du)
                display_default = _num(units.to_display(info['_default'], dim, du))
        row = {
            'parameter': key,
            'display_name': _one_line(entry.get('display_name')),
            'category': _one_line(entry.get('category')),
            'subcategory': _one_line(entry.get('subcategory')),
            'expert_level': _one_line(info.get('_expert_level')),
            'parameter_type': _one_line(entry.get('parameter_type')),
            'description': _one_line(info.get('_description')),
            'stored_unit': _one_line(entry.get('unit')),
            'dimension': _one_line(dim),
            'default': _num(entry.get('default')),
            'display_unit': display_unit,
            'display_default': display_default,
            'fitting_method': _one_line(entry.get('fitting_method')),
            'literature': '; '.join(_one_line(c.get('cite')) for c in entry.get('literature') or []),
            'ontology_term': _one_line(entry.get('ontology_term')),
            'measurable': _num(info.get('_measurable')),
            'experimental_assay': _one_line(info.get('_experimental_assay')),
        }
        for tier, label in TIER_LABELS.items():
            col = label.lower()
            declared = entry['ranges'].get(tier) is not None
            ev = (entry.get('range_evidence') or {}).get(tier) or {}
            row[f'{col}_range'] = _range(entry['ranges'].get(tier))
            row[f'{col}_evidence'] = (_one_line(audit_mod.evidence_phrase(entry, tier))
                                      if declared else '')
            row[f'{col}_note'] = _one_line(ev.get('note')) if declared else ''
        dp = entry.get('default_provenance') or {}
        row['default_source'] = _one_line(dp.get('source') or dp.get('title'))
        row['default_locator'] = _locator(dp.get('locator'))
        rows.append(row)
    rows.sort(key=lambda r: (r['category'], r['subcategory'], r['parameter']))
    return rows, fingerprint


# ---------------------------------------------------------------- writers
def _md_cell(text):
    return _one_line(text).replace('|', '\\|') or '&mdash;'


def render_markdown(sid, model, rows, fingerprint):
    n = len(rows)
    n_phys = sum(1 for r in rows if r['supported_range'])
    n_math = sum(1 for r in rows if r['admissible_range'])
    n_rec = sum(1 for r in rows if r['recommended_range'])
    n_ont = sum(1 for r in rows if r['ontology_term'])
    out = [
        f"# Table {sid}. {model['title']}",
        "",
        f"Generated from {model['source']} by "
        "`docs/supplementary/generate_schema_tables.py`. Do not edit by hand.",
        "",
        f"- **Schema fingerprint:** `{fingerprint}` (the content hash recorded with "
        "every run configured under these definitions)",
        f"- **Parameters:** {n}. Admissible range declared for {n_math}, evidence-supported "
        f"range for {n_phys}, recommended range for {n_rec}; ontology term for {n_ont}.",
        f"- **Full columns** (descriptions, evidence notes, assays): `{model['stem']}.csv`.",
        "",
        "Units: values are given in the unit the simulator stores (**Stored unit**). Where "
        "the interface converts for display, the operator-facing unit and default are shown "
        "after the arrow. **Admissible**: values the implementation accepts; "
        "**Supported**: values backed by the documented evidence; **Recommended**: the "
        "range advised for this model's context of use. Each range is followed by the "
        "basis and sources recorded for it.",
        "",
        "| Parameter | Category | Stored unit | Default | Admissible | Supported | "
        "Recommended | Default source | Ontology | Level |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        unit = r['stored_unit'] + (f" &rarr; {r['display_unit']}" if r['display_unit'] else '')
        default = r['default'] + (f" &rarr; {r['display_default']}" if r['display_default'] else '')

        def tier(col):
            if not r[f'{col}_range']:
                return ''
            return f"{r[f'{col}_range']}<br>*{r[f'{col}_evidence']}*"
        src = r['default_source'] + (f" ({r['default_locator']})" if r['default_locator'] else '')
        if r['fitting_method']:
            src = f"{src}; {r['fitting_method']}" if src else r['fitting_method']
        cells = [f"`{r['parameter']}`<br>{r['display_name']}",
                 f"{r['category']} / {r['subcategory']}" if r['subcategory'] else r['category'],
                 unit, default, tier('admissible'), tier('supported'), tier('recommended'),
                 src, r['ontology_term'], r['expert_level']]
        out.append('| ' + ' | '.join(_md_cell(c) if not c.startswith('`') else
                                     c.replace('|', '\\|') for c in cells) + ' |')
    return '\n'.join(out) + '\n'


def render_csv(rows, fingerprint):
    # The fingerprint is a column (not a comment line) so the file stays plain
    # CSV for spreadsheet and journal tooling.
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, lineterminator='\n')
    w.writeheader()
    w.writerows({**r, 'schema_fingerprint': fingerprint} for r in rows)
    return buf.getvalue()


def render_all():
    """{filename: content} for every supplementary table."""
    files = {}
    for sid, model in MODELS.items():
        rows, fingerprint = build_rows(model)
        files[f"{model['stem']}.md"] = render_markdown(sid, model, rows, fingerprint)
        files[f"{model['stem']}.csv"] = render_csv(rows, fingerprint)
    return files


def stale_files(out_dir=HERE):
    """Names of committed tables that differ from what the code now produces."""
    stale = []
    for name, content in render_all().items():
        path = Path(out_dir) / name
        if not path.exists() or path.read_text(encoding='utf-8') != content:
            stale.append(name)
    return stale


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--check', action='store_true',
                    help='exit 1 if the committed tables are out of date')
    args = ap.parse_args(argv)
    if args.check:
        stale = stale_files()
        if stale:
            print("Out of date (rerun without --check): " + ", ".join(stale))
            return 1
        print("Supplementary schema tables are up to date.")
        return 0
    for name, content in render_all().items():
        (HERE / name).write_text(content, encoding='utf-8', newline='\n')
        print(f"wrote {name}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
