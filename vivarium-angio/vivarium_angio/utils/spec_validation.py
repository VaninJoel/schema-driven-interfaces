"""Check a complete experiment specification against the process schema.

ONE check for both interfaces. The graphical interface calls it to mark a field
and to decide what the operator must confirm; the program-facing process calls it
before anything is executed. A specification is therefore judged the same way
whether it was typed into the GUI, loaded from a file or built by a script, and
the outcome is written into the run record either way.

Three kinds of finding, in decreasing severity:

    malformed      the specification cannot be used as written: a key that is not a
                   parameter of the model, a value of the wrong type, a text value
                   that breaks the parameter's declared pattern or length.
                   ALWAYS refused. There is nothing to confirm.
    inadmissible   a well-formed value outside the range the schema declares as
                   the implementation limit (`_mathematical_range`).
                   Refused unless the caller explicitly allows it
                   (`allow_inadmissible=True`), and that permission is recorded.
    outside_range  a well-formed, admissible value outside the documented working
                   range (`_physiological_range`) or the recommended range
                   (`_recommended_range`). Never refused: it runs, and is recorded.

Every message names what the range is based on (published literature, model
calibration, the modeler's judgement, a numerical or implementation limit,
exploratory presets), because "outside the working range" means something
different in each case.

Standard library only. This file is kept identical in vivarium_angio.utils and
vivarium_vcornea.utils.
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Dict, Iterable, List, Optional

MALFORMED, INADMISSIBLE, OUTSIDE_RANGE = 'malformed', 'inadmissible', 'outside_range'

_TIERS = (
    # (schema key, tier name, severity, how the range is described to a reader)
    ('_mathematical_range', 'mathematical', INADMISSIBLE, 'the declared implementation limit'),
    ('_physiological_range', 'physiological', OUTSIDE_RANGE, 'the documented working range'),
    ('_recommended_range', 'recommended', OUTSIDE_RANGE, 'the recommended range'),
)

_BASIS_PHRASES = {
    'literature': 'published literature',
    'calibration': 'model calibration',
    'expert_judgement': "the modeler's judgement",
    'numerical_stability': 'a numerical or implementation limit',
    'exploratory': 'exploratory presets',
}


class SpecificationError(ValueError):
    """The specification was refused. `.issues` holds the findings that caused it;
    `.record` the full check record (see `check_record`)."""

    def __init__(self, message, issues, record):
        super().__init__(message)
        self.issues = issues
        self.record = record


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _basis(info: Dict[str, Any], tier: str) -> Optional[str]:
    ev = (info.get('_range_evidence') or {}).get(tier)
    return ev.get('basis') if isinstance(ev, dict) else None


def _basis_phrase(basis) -> str:
    return _BASIS_PHRASES.get(basis, str(basis)) if basis else 'basis not recorded'


def _issue(parameter, severity, message, *, value=None, tier=None, rng=None, basis=None):
    return {'parameter': parameter, 'severity': severity, 'tier': tier, 'value': value,
            'range': list(rng) if rng is not None else None, 'basis': basis,
            'message': message}


def validate_value(key: str, info: Dict[str, Any], value: Any) -> List[Dict[str, Any]]:
    """Findings for one parameter value against its schema entry (possibly empty).

    A value equal to the schema default is never a finding: defaults may be
    sentinels (for example -1 for "draw a seed") that sit outside a range on purpose.
    """
    default = info.get('_default')
    if value == default and type(value) is type(default):
        return []
    name = info.get('_display_name') or key
    unit = info.get('_unit')
    unit_txt = f" {unit}" if unit and _is_number(value) else ""

    # ---- type ---------------------------------------------------------------
    if isinstance(default, bool):
        if not isinstance(value, bool):
            return [_issue(key, MALFORMED, f"{name}: expected true/false, got {value!r}",
                           value=value)]
        return []
    if _is_number(default):
        if not _is_number(value):
            return [_issue(key, MALFORMED, f"{name}: expected a number, got {value!r}",
                           value=value)]
        if isinstance(default, int) and float(value) != int(value):
            return [_issue(key, MALFORMED,
                           f"{name}: expected a whole number, got {value!r}", value=value)]
    elif isinstance(default, str):
        if not isinstance(value, str):
            return [_issue(key, MALFORMED, f"{name}: expected text, got {value!r}",
                           value=value)]
        found = []
        pattern = info.get('_validation_pattern')
        if pattern and not re.fullmatch(pattern, value):
            found.append(_issue(key, MALFORMED,
                                f"{name}: {value!r} does not match the allowed pattern "
                                f"{pattern!r}", value=value))
        max_len = info.get('_max_length')
        if max_len and len(value) > int(max_len):
            found.append(_issue(key, MALFORMED,
                                f"{name}: longer than the {max_len} characters allowed",
                                value=value))
        return found
    if not _is_number(value):
        return []

    # ---- ranges: report the outermost tier the value violates ----------------
    for schema_key, tier, severity, described in _TIERS:
        rng = info.get(schema_key)
        if rng is None:
            continue
        try:
            lo, hi = rng
        except (TypeError, ValueError):
            continue
        if (lo is not None and value < lo) or (hi is not None and value > hi):
            basis = _basis(info, tier)
            return [_issue(
                key, severity,
                f"{name}: {value:g}{unit_txt} is outside {described} [{lo:g}, {hi:g}] "
                f"(range set by {_basis_phrase(basis)})",
                value=value, tier=tier, rng=(lo, hi), basis=basis)]
    return []


def validate_specification(schema_inputs: Dict[str, Any], params: Dict[str, Any],
                           known_extra: Iterable[str] = ()) -> List[Dict[str, Any]]:
    """Findings for a whole specification.

    schema_inputs: the `inputs` port of a ports_schema(). params: the values given
    (a parameter that is absent runs at its default and raises no finding).
    known_extra: keys that are legitimately present but are not schema parameters
    (launcher settings, run identity). Any other key that is not in the schema is
    reported as malformed — a misspelt parameter must not silently run at the default.
    """
    known_extra = frozenset(known_extra)
    issues: List[Dict[str, Any]] = []
    for key, value in (params or {}).items():
        info = schema_inputs.get(key)
        if not isinstance(info, dict) or '_default' not in info:
            if key not in known_extra:
                issues.append(_issue(key, MALFORMED,
                                     f"{key!r} is not a parameter of this model",
                                     value=value))
            continue
        issues.extend(validate_value(key, info, value))
    return issues


def blocking_issues(issues, allow_inadmissible: bool = False) -> List[Dict[str, Any]]:
    """The findings that stop a run: malformed always, inadmissible unless allowed."""
    stop = {MALFORMED} if allow_inadmissible else {MALFORMED, INADMISSIBLE}
    return [i for i in issues if i['severity'] in stop]


def check_record(issues, *, allow_inadmissible: bool = False, checked_by: str,
                 confirmed_by_operator: Optional[bool] = None) -> Dict[str, Any]:
    """The JSON-serialisable record of one specification check, for the run record.

    checked_by: 'process' or 'gui'. confirmed_by_operator: True/False when an
    operator was asked to confirm the findings, None when nobody was asked (a
    programmatic run). allow_inadmissible: whether values outside an
    implementation limit were explicitly permitted for this run.
    """
    return {
        'format': 'schema-driven-interfaces/specification-check/1',
        'checked_at': _dt.datetime.now().isoformat(timespec='seconds'),
        'checked_by': checked_by,
        'allow_inadmissible': bool(allow_inadmissible),
        'confirmed_by_operator': confirmed_by_operator,
        'n_malformed': sum(1 for i in issues if i['severity'] == MALFORMED),
        'n_inadmissible': sum(1 for i in issues if i['severity'] == INADMISSIBLE),
        'n_outside_range': sum(1 for i in issues if i['severity'] == OUTSIDE_RANGE),
        'issues': list(issues),
    }


def enforce(schema_inputs: Dict[str, Any], params: Dict[str, Any], *,
            allow_inadmissible: bool = False, known_extra: Iterable[str] = (),
            checked_by: str = 'process',
            confirmed_by_operator: Optional[bool] = None) -> Dict[str, Any]:
    """Validate and either return the check record or raise SpecificationError.

    Call this before anything is executed, and store the returned record in the
    run record."""
    issues = validate_specification(schema_inputs, params, known_extra)
    record = check_record(issues, allow_inadmissible=allow_inadmissible,
                          checked_by=checked_by,
                          confirmed_by_operator=confirmed_by_operator)
    stop = blocking_issues(issues, allow_inadmissible)
    if stop:
        hint = ('' if all(i['severity'] == MALFORMED for i in stop) else
                ' Values outside an implementation limit run only with '
                'allow_inadmissible=True, which is recorded with the run.')
        raise SpecificationError(
            "Experiment specification refused: "
            + "; ".join(i['message'] for i in stop) + "." + hint, stop, record)
    return record
