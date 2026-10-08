"""Parameter audit record: what the schema says about the values a run used.

The schema documents each parameter (meaning, units, default, admissible /
evidence-supported / recommended ranges and the evidence behind them, default
provenance, literature, ontology term). A run record holds the values that were
executed. This module joins the two so the audit bundle can answer, for every
parameter and without the operator present:

* which value ran, and whether it differs from the documented default;
* where that value sits relative to each declared range tier, and therefore
  whether the run is *supported* by the documented evidence, an
  *extrapolation* beyond it, *inadmissible* for the implementation, or
  *unassessable* because no range is documented;
* what evidence (basis, citation, locator) backs each bound and the default.

The result is plain JSON, written into the COMBINE/OMEX archive as
``parameter_audit.json`` and summarised in the PDF reports. It is built where
the live schema exists (the process, or the GUI main window) and handed down
to the archive writer, which has no schema of its own.

Credibility vocabulary (per parameter):
    inadmissible          outside the mathematical/implementation range
    extrapolation         admissible, but outside the physiological range
    outside_recommended   within evidence, but outside the recommended range
    supported             within every declared tier, physiological declared
    admissible            within every declared tier, no physiological range
    unassessable          numeric value, but no range declared at all
    not_applicable        boolean / categorical / text parameter (ranges do not apply)
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Callable, Dict, Optional

TIERS = ('mathematical', 'physiological', 'recommended')
TIER_KEYS = {'mathematical': '_mathematical_range',
             'physiological': '_physiological_range',
             'recommended': '_recommended_range'}

# Keys the GUI stamps on the resolved parameter set that are run identity or
# orchestration state, not schema parameters. They are reported separately.
_RUN_STATE_KEYS = frozenset((
    '_schema_fingerprint', 'creator', 'random_seed_origin', 'parameter_scan',
    'scan_point', 'combination_index', 'total_combinations', 'replicate_id',
    'total_replicates', 'parent_experiment_id',
))


def _default_resolver() -> Callable[[Any], Dict[str, Any]]:
    """The model's bibliography, however this module was imported.

    Works as a package submodule (relative import), as a bare module with the
    utils dir on sys.path (the report scripts do this), or not at all.
    """
    REFERENCES = {}
    for attempt in (lambda: __import__(__name__.rsplit('.', 1)[0] + '.references',
                                       fromlist=['REFERENCES']).REFERENCES
                    if '.' in __name__ else None,
                    lambda: __import__('references').REFERENCES):
        try:
            found = attempt()
        except Exception:
            found = None
        if isinstance(found, dict) and found:
            REFERENCES = found
            break

    def resolve(key):
        return REFERENCES.get(key, {}) if isinstance(REFERENCES, dict) else {}
    return resolve


def _cite(key, resolve) -> Dict[str, Any]:
    r = resolve(key) or {}
    return {'key': key,
            'cite': r.get('cite') or r.get('source') or r.get('title') or str(key),
            'doi': r.get('doi')}


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _position(value, rng) -> Optional[str]:
    if not _is_number(value):
        return 'not_applicable'
    if rng is None:
        return 'undeclared'
    try:
        lo, hi = rng
    except (TypeError, ValueError):
        return 'undeclared'
    if lo is not None and value < lo:
        return 'below'
    if hi is not None and value > hi:
        return 'above'
    return 'within'


def _credibility(positions: Dict[str, str]) -> str:
    if all(positions[t] in ('not_applicable', 'undeclared') for t in TIERS) \
            and any(positions[t] == 'not_applicable' for t in TIERS):
        return 'not_applicable'
    m, p, r = (positions[t] for t in TIERS)
    if m in ('below', 'above'):
        return 'inadmissible'
    if p in ('below', 'above'):
        return 'extrapolation'
    if r in ('below', 'above'):
        return 'outside_recommended'
    declared = [t for t in TIERS if positions[t] == 'within']
    if not declared:
        return 'unassessable'
    return 'supported' if p == 'within' else 'admissible'


def _range_evidence(info: Dict, resolve) -> Dict[str, Any]:
    out = {}
    ev = info.get('_range_evidence') or {}
    for tier in TIERS:
        e = ev.get(tier)
        if not isinstance(e, dict):
            out[tier] = None
            continue
        out[tier] = {
            'basis': e.get('basis'),
            'refs': [_cite(k, resolve) for k in (e.get('refs') or [])],
            'locator': e.get('locator'),
            'note': e.get('note'),
        }
    return out


def _default_provenance(info: Dict, resolve) -> Optional[Dict[str, Any]]:
    ref = info.get('_reference_paper')
    if not isinstance(ref, dict):
        return None
    out = {k: ref.get(k) for k in ('source', 'title', 'journal', 'year', 'doi',
                                   'value', 'locator', 'notes') if k in ref}
    return out


def _jsonable(v):
    if isinstance(v, tuple):
        return list(v)
    if callable(v):
        return None
    return v


def build_parameter_audit(schema: Dict[str, Any], params: Dict[str, Any],
                          schema_fingerprint: Optional[str] = None,
                          resolve_ref: Optional[Callable] = None,
                          port: str = 'inputs') -> Dict[str, Any]:
    """Join a ports_schema() with the resolved parameters of one run."""
    resolve = resolve_ref or _default_resolver()
    section = (schema or {}).get(port, {}) or {}
    params = params or {}
    entries: Dict[str, Any] = {}
    flagged = {'inadmissible': [], 'extrapolation': [], 'outside_recommended': [],
               'unassessable': [], 'changed_from_default': []}

    for key, info in section.items():
        if not isinstance(info, dict) or '_default' not in info:
            continue
        default = info.get('_default')
        value = params.get(key, default)
        ranges = {t: _jsonable(info.get(TIER_KEYS[t])) for t in TIERS}
        positions = {t: _position(value, ranges[t]) for t in TIERS}
        cred = _credibility(positions)
        is_control = info.get('_parameter_type') == 'control'
        changed = (value != default) and not is_control
        entry = {
            'display_name': info.get('_display_name', key),
            'value': value,
            'default': default,
            'changed_from_default': changed,      # always False for control parameters
            'unit': info.get('_unit'),
            'dimension': info.get('_dimension'),
            'scope': info.get('_scope'),
            'parameter_type': info.get('_parameter_type'),
            'category': info.get('_category'),
            'subcategory': info.get('_subcategory'),
            'ontology_term': info.get('_ontology_term'),
            'ranges': ranges,
            'position': positions,
            'credibility': cred,
            'range_evidence': _range_evidence(info, resolve),
            'default_provenance': _default_provenance(info, resolve),
            'literature': [_cite(k, resolve) for k in (info.get('_literature') or [])],
            'fitting_method': info.get('_fitting_method'),
            'dependencies': info.get('_dependencies') or {},
            'affects_output': list(info.get('_affects_output') or []),
            'model_context': info.get('_model_context'),
        }
        entries[key] = entry
        if cred in flagged:
            flagged[cred].append(key)
        if changed:
            flagged['changed_from_default'].append(key)

    run_state = {k: params[k] for k in params if k in _RUN_STATE_KEYS}
    undocumented = sorted(k for k in params
                          if k not in entries and k not in _RUN_STATE_KEYS)
    n = len(entries)
    summary = {
        'n_parameters': n,
        'n_changed_from_default': len(flagged['changed_from_default']),
        'n_supported': sum(1 for e in entries.values() if e['credibility'] == 'supported'),
        'n_admissible': sum(1 for e in entries.values() if e['credibility'] == 'admissible'),
        'n_outside_recommended': len(flagged['outside_recommended']),
        'n_extrapolation': len(flagged['extrapolation']),
        'n_inadmissible': len(flagged['inadmissible']),
        'n_unassessable': len(flagged['unassessable']),
        'n_not_applicable': sum(1 for e in entries.values() if e['credibility'] == 'not_applicable'),
        'n_with_range_evidence': sum(
            1 for e in entries.values()
            if any(v and v.get('basis') for v in e['range_evidence'].values())),
        'changed_from_default': flagged['changed_from_default'],
        'extrapolation': flagged['extrapolation'],
        'inadmissible': flagged['inadmissible'],
        'outside_recommended': flagged['outside_recommended'],
        'undocumented_parameters': undocumented,
    }
    return {
        'format': 'schema-driven-interfaces/parameter-audit/1',
        'generated_at': _dt.datetime.now().isoformat(timespec='seconds'),
        'schema_fingerprint': schema_fingerprint or params.get('_schema_fingerprint'),
        'summary': summary,
        'run_state': run_state,
        'parameters': entries,
    }


def audit_summary_line(audit: Dict[str, Any]) -> str:
    """One sentence for logs and report headers."""
    s = (audit or {}).get('summary') or {}
    return (f"{s.get('n_parameters', 0)} parameters, "
            f"{s.get('n_changed_from_default', 0)} changed from default; "
            f"{s.get('n_supported', 0)} within documented evidence, "
            f"{s.get('n_extrapolation', 0)} extrapolations, "
            f"{s.get('n_inadmissible', 0)} inadmissible, "
            f"{s.get('n_unassessable', 0)} numeric without a documented range, "
            f"{s.get('n_not_applicable', 0)} switches/categories")


# ---------------------------------------------------------------------------
# Report helpers (used by the PDF generators; plain data, no reportlab here)
# ---------------------------------------------------------------------------

CREDIBILITY_LABELS = {
    'supported': 'within documented evidence',
    'admissible': 'admissible (no physiological range documented)',
    'outside_recommended': 'outside recommended range',
    'extrapolation': 'EXTRAPOLATION beyond documented evidence',
    'inadmissible': 'INADMISSIBLE for the implementation',
    'unassessable': 'no documented range',
    'not_applicable': 'switch / category (ranges do not apply)',
}


def _short_cite(c: Dict[str, Any]) -> str:
    cite = str(c.get('cite') or c.get('key') or '')
    # "Author A, Author B, ... Title. Journal. 2010;..." -> "Author A et al. (2010)"
    import re as _re
    year = _re.search(r'\b(19|20)\d{2}\b', cite)
    first = cite.split(',')[0].strip()
    if len(first) > 40:
        first = first[:37] + '...'
    if not year:
        return first or cite
    if 'et al' in first or ',' not in cite:
        return f"{first} ({year.group(0)})"
    return f"{first} et al. ({year.group(0)})"


def evidence_phrase(entry: Dict[str, Any], tier: str = 'physiological') -> str:
    """'published evidence: Merks et al. (2006), Table 1, p. 47' or 'not recorded'."""
    ev = (entry.get('range_evidence') or {}).get(tier)
    if not ev:
        return 'range not declared' if entry['ranges'].get(tier) is None else 'not recorded'
    bits = [ev.get('basis') or 'basis unspecified']
    if ev.get('refs'):
        bits.append(', '.join(_short_cite(c) for c in ev['refs']))
    loc = ev.get('locator') or {}
    if isinstance(loc, dict):
        l = [str(loc[k]) for k in ('table', 'equation') if loc.get(k)]
        if loc.get('page'):
            l.append(f"p. {loc['page']}")
        if l:
            bits.append(', '.join(l))
    if len(bits) == 1 and ev.get('note'):
        note = str(ev['note'])
        bits.append(note if len(note) <= 80 else note[:77] + '...')
    return ': '.join(bits[:1]) + (': ' + '; '.join(bits[1:]) if len(bits) > 1 else '')


def deciding_tier(entry: Dict[str, Any]) -> str:
    """The range tier that fixed the verdict: the violated one, else physiological, else any declared."""
    pos = entry.get('position') or {}
    for tier in TIERS:
        if pos.get(tier) in ('below', 'above'):
            return tier
    if pos.get('physiological') == 'within':
        return 'physiological'
    for tier in ('recommended', 'mathematical'):
        if pos.get(tier) == 'within':
            return tier
    return 'physiological'


def audit_table_rows(audit: Dict[str, Any], include: str = 'attention'):
    """Rows for a report table.

    include='attention' -> parameters changed from default or not 'supported'
    (the ones an auditor must look at); include='all' -> every parameter.
    Returns (header, rows); each row is [name, value, default, unit, credibility,
    evidence-for-physiological-range].
    """
    header = ['Parameter', 'Run value', 'Default', 'Unit', 'Credibility',
              'Evidence for the range assessed']
    rows = []
    order = {'inadmissible': 0, 'extrapolation': 1, 'outside_recommended': 2,
             'unassessable': 3, 'admissible': 4, 'supported': 5, 'not_applicable': 6}
    items = sorted((audit.get('parameters') or {}).items(),
                   key=lambda kv: (order.get(kv[1]['credibility'], 9),
                                   not kv[1]['changed_from_default'], kv[0]))
    for key, e in items:
        if include == 'attention' and e['credibility'] in ('supported', 'admissible', 'not_applicable') \
                and not e['changed_from_default']:
            continue
        rows.append([
            f"{e.get('display_name') or key} ({key})",
            e['value'], e['default'], e.get('unit') or '',
            CREDIBILITY_LABELS.get(e['credibility'], e['credibility']),
            evidence_phrase(e, deciding_tier(e)),
        ])
    return header, rows


def load_parameter_audit(source) -> Optional[Dict[str, Any]]:
    """Read parameter_audit.json from a run directory or an .omex archive."""
    import json as _json
    import zipfile as _zip
    from pathlib import Path as _P
    p = _P(source)
    if p.is_dir():
        f = p / 'parameter_audit.json'
        return _json.loads(f.read_text()) if f.exists() else None
    if p.suffix == '.omex' and p.exists():
        with _zip.ZipFile(p) as zf:
            for name in ('parameter_audit.json', 'model/parameter_audit.json'):
                if name in zf.namelist():
                    return _json.loads(zf.read(name))
    return None
