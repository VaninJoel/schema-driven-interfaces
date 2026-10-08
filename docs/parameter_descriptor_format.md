# Common parameter descriptor format

One format for describing an exposed parameter, shared by both process schemas
(`vivarium-vcornea` and `vivarium-angio`) regardless of implementation pattern.
It is the union of every descriptor either schema uses today, organised into
seven groups and with the handful of naming clashes resolved. No information
either schema currently records is dropped.

The worked example is `parameter_descriptor_example.py` (one angiogenesis
parameter and one V-Cornea parameter in the same format; the file also holds
the machine-readable field list and a self-check).

## Why a common format

The manuscript (Section 2.2) says a parameter definition records: the
implementation key; a human-readable name and description; the process it
affects; units and default; relationships to other parameters, mechanisms and
outputs; the literature or calibration rationale; context-specific recommended
ranges; hard mathematical or implementation constraints; presentation metadata;
and optionally an ontology identifier. Both schemas record most of this, but
under different keys and with different depth, and the GUIs already read the
superset of both. The format below makes the two schemas comparable field for
field, which is what a reader of the paper will try to do.

## The seven groups

Fields marked **required** must appear on every exposed parameter; `None` is an
acceptable value and means "not known / not yet written", which keeps gaps
visible. Optional fields may be omitted when they cannot apply to a parameter.

### 1. Execution contract — what the simulator needs

| Field | Req. | Meaning |
|---|---|---|
| `_default` | yes | Value used when the operator sets nothing. Must satisfy `_mathematical_range`. |
| `_updater`, `_emit` | yes | Vivarium port contract (unchanged). |
| `_scope` | yes | `model` (passed to the simulator) or `wrapper` (consumed by the orchestration layer, e.g. output toggles, timeouts). |
| `_parameter_type` | yes | `biophysical`, `kinetic`, `geometric`, `initial_condition`, `control`. |
| `_validation_pattern`, `_max_length` | no | For string parameters (names, paths). |
| `_auto_generate` | no | Value can be derived if left blank (e.g. experiment name). |
| `_debug_parameter` | no | Diagnostic switch, hidden from operators by default. |

### 2. Identity and meaning — developer to operator

| Field | Req. | Meaning |
|---|---|---|
| `_display_name` | yes | Label shown in the GUI. |
| `_description` | yes | One or two sentences: what it is and which way it pushes the system. |
| `_category`, `_subcategory` | yes | Grouping by biological or experimental function. |
| `_expert_level` | yes | `basic`, `intermediate`, `advanced`. Controls editability, not visibility. |
| `_long_description` | no | Mechanistic/technical account (developer voice). |
| `_conceptual_hint` | no | Operator-level intuition in plain language. |
| `_biological_meaning` | no | What the quantity corresponds to in vivo / in vitro. |
| `_model_context` | no | Where it enters the model: equation, Hamiltonian term, rule. |
| `_implementation_pattern` | no | Where it is assigned in the code. |
| `_ontology_term` | no | CURIE (`CBO:0000016`) or list of CURIEs; ontology-agnostic. |

### 3. Units

| Field | Req. | Meaning |
|---|---|---|
| `_unit` | yes | Unit of the stored value, as the simulator sees it. |
| `_dimension` | yes | `energy`, `length`, `time`, `concentration`, `rate`, `count`, `dimensionless`, … Drives display conversion. |
| `_unit_long` | no | Spelled-out unit with caveats. |
| `_display_unit`, `_conversion_factor` | no | Operator-facing unit and `display = stored × factor`. |
| `_value_mapping` | no | Labels for enumerated or boolean values. |

### 4. Admissible and supported values — the three tiers

Each tier is a `(min, max)` tuple in the stored unit, which is what both GUIs
unpack today. The evidence for each tier sits beside the tuples in
`_range_evidence`, so an auditor can check a bound against its source and the
schema can say plainly when a bound is exploratory.

\* A tier that has not been declared is **omitted** rather than written as
`None` (the GUIs unpack the tuples at 38 sites). `_range_evidence` is always
present and carries an explicit `None` for every undeclared tier, so the gap
stays visible in the schema, the fingerprint, and the generated documentation.

| Field | Req. | Meaning |
|---|---|---|
| `_mathematical_range` | no* | What the implementation accepts. Outside → error. |
| `_physiological_range` | no* | What the evidence supports. Outside → extrapolation warning. |
| `_recommended_range` | no* | Advised for this model's context of use. |
| `_range_evidence` | yes | One entry per tier: `{basis, refs, locator, note}`. `basis` is one of `numerical_stability`, `literature`, `calibration`, `expert_judgement`, `exploratory`; `refs` are keys into the model's references registry; `locator` is `{table, equation, page}`. **New field**: today the justification lives in code comments only, and a bound with no evidence can say so (`exploratory`) instead of implying evidence that does not exist. |
| `_warning_threshold` | no | Single value above which a warning is raised. |
| `_presets` | no | Named operating points `{label: value}`. |

### 5. Relationships and expected effect

| Field | Req. | Meaning |
|---|---|---|
| `_related_parameters` | yes | Parameters usually tuned together. |
| `_dependencies` | yes | `{parameter: why}` — parameters whose value changes this one's meaning or effect. |
| `_affects_output` | yes | Output metrics this parameter moves. |
| `_expected_behavior` | no | `{low_value, high_value, threshold}` qualitative regimes. |
| `_equations` | no | Keys into the model's equation registry. |
| `_output_files` | no | Files a `wrapper` parameter switches on or off. |
| `_performance_impact`, `_storage_impact` | no | `low`, `medium`, `high`. |

### 6. Evidence — run to auditor

Required for every parameter except those with `_parameter_type: control`
(experiment name, seed, duration, write frequency): execution controls have no
literature provenance, and pretending otherwise would be noise.

| Field | Req. | Meaning |
|---|---|---|
| `_reference_paper` | yes | **Provenance of the default value**: `{source, title, journal, year, doi, value, locator: {table, equation, page}, notes}`. A self-citation is fine; a locator is what makes it checkable. |
| `_literature` | yes | Keys into the model's `references.py` registry: the evidence base for the parameter beyond the default. |
| `_fitting_method` | yes | `literature_based`, `fitted`, `estimated`, `calibrated`. |
| `_measurable` | no | Directly measurable experimentally? |
| `_experimental_assay` | no | Which assay measures it. |

### 7. Presentation — GUI only, never affects execution

| Field | Req. | Meaning |
|---|---|---|
| `_hidden_basic` | no | Hide at basic level. |
| `_depends_on_display`, `_conditional_display` | no | Parameters that gate visibility, and the predicate. The predicate is a callable; the schema fingerprint replaces it with a stable marker. |
| `_gui_hints` | no | Widget type, step, preset buttons, highlighting. |

## Mapping from the current schemas

Counts are occurrences in the current `ports_schema()` (84 V-Cornea parameters,
13 angiogenesis parameters).

| Current key | V-Cornea | Angio | In the common format |
|---|---|---|---|
| `_default`, `_updater`, `_emit` | 84 | 13 | unchanged |
| `_display_name`, `_description`, `_category`, `_subcategory`, `_expert_level` | 79 | 11–13 | unchanged; now required |
| `_unit` | 79 | 12 | unchanged; now required |
| `_dimension` | 55 | 0 | unchanged; now required (angio must add) |
| `_unit_long`, `_conversion_factor`, `_value_mapping` | 0–3 | 1–10 | unchanged |
| `_mathematical_range` | 0 | 9 | unchanged; undeclared tiers recorded as `None` in `_range_evidence` |
| `_physiological_range` | 27 | 9 | unchanged |
| `_recommended_range` | 31 | 9 | unchanged |
| `_warning_threshold` | 0 | 6 | unchanged |
| `_presets` | 1 | 9 | unchanged |
| `_preset_values` | 1 | 0 | **merged into** `_presets` |
| `_reference_paper` | 79 | 7 | **redefined** as provenance of the default, with a `locator` sub-dict. Angio's `equation`/`page`/`notes` move under `locator`/`notes`; V-Cornea's bare self-cites gain a locator (issue #13). |
| `_literature` | 20 | 0 | unchanged; now required. Angio adopts a `references.py` registry (its inline `REFERENCES` dict already is one). |
| `_fitting_method`, `_measurable`, `_experimental_assay` | 0 | 4–8 | unchanged; `_fitting_method` now required |
| `_cbo_term` | 75 | 7 | **renamed** `_ontology_term`. Neither GUI displays it, so the rename costs nothing. V-Cornea's `cbo:AreaEnergy`-style strings should be resolved to CBO identifiers or kept as labels under a documented prefix. |
| `_model_context` | 76 | 7 | unchanged |
| `_conceptual_hint`, `_implementation_pattern` | 79 | 0 | unchanged (angio may add) |
| `_long_description`, `_biological_meaning` | 0–1 | 9–10 | unchanged (V-Cornea may add) |
| `_related_parameters` | 48 | 8 | unchanged; now required |
| `_dependencies` | 0 | 6 | unchanged; now required |
| `_depends_on` | 23 | 0 | **split**: semantic dependencies move into `_dependencies` with an explanation; display gating becomes `_depends_on_display` |
| `_affects_output` | 2 | 9 | unchanged; now required |
| `_visual_effects` | 0 | 5 | **renamed** `_expected_behavior` (the regimes are about model behaviour, not visuals; both GUIs read the key in six places total) |
| `_scope` | 10 | 0 | unchanged; now required (default `model`) |
| `_parameter_type` | 0 | 10 | unchanged; now required; gains `initial_condition` |
| `_output_files`, `_storage_impact`, `_debug_parameter` | 2–10 | 0 | unchanged |
| `_performance_impact`, `_auto_generate`, `_validation_pattern`, `_max_length` | 0 | 1 | unchanged |
| `_hidden_basic`, `_conditional_display`, `_gui_hints` | 1–20 | 1–11 | unchanged |
| — | — | — | **new**: `_range_evidence`, `_equations`, `_depends_on_display` |

Net effect: three renames (`_cbo_term`, `_visual_effects`, `_depends_on`), one
merge (`_preset_values`), one redefinition (`_reference_paper`), three new
fields (`_range_evidence`, `_equations`, `_depends_on_display`). Everything else keeps its name; the change is that the required set is
now the same for both models.

## Migration status (2026-10-06)

Both schemas were migrated mechanically (script kept out of the repo; the
result is the schema source itself). Renames and merges applied; every
parameter carries the required set; range comments became `_range_evidence`
notes, with `basis` set only where the comment said so (`exploratory`,
`stable`), `None` otherwise; V-Cornea `_reference_paper` sources of the form
`Vanin et al., 2025 (S10 Table; …)` were split into `source` + `locator` +
`notes`; angio `equation`/`page` moved under `locator`; `_literature` for angio
derived from the default's citation key; the angio bibliography moved to
`vivarium_angio/utils/references.py`. Only `jee`/`jem` got a literature-based
physiological range entry, because their own schema text already asserted it.
Everything else below is still content work.

## What becomes required that is missing today

| Requirement | V-Cornea gap | Angio gap |
|---|---|---|
| `_mathematical_range` | all 84 | 4 of 13 |
| `_physiological_range` | 57 of 84 (many legitimately `None`: arbitrary CPM units) | 4 of 13 |
| `_dimension` | 29 of 84 | all 13 |
| `_reference_paper.locator` | 67 bare self-cites | 0 |
| `_literature` | 64 of 84 | all 13 |
| `_dependencies` with explanations | 84 (23 have an unexplained `_depends_on`) | 7 of 13 |
| `_range_evidence` | all | all |
| `_fitting_method`, `_parameter_type`, `_scope` | all / all / 74 | 6 / 3 / all |

Filling these is content work for the modeler, not code work. The format makes
the gaps enumerable, which is the point Section 2.2 argues.

## Code consequences of adopting the format

- **Done (2026-10-06):** both GUIs' `utils/schema_utils.py` carry
  `get_range_evidence()` / `format_range_evidence()` and a `RANGE_TIERS`
  table. The parameter info dialog, the validation dialog and
  `extract_parameter_documentation()` in both GUIs render every range tier
  through them, resolving `refs` against the model's registry
  (`vivarium_vcornea.utils.references.REFERENCES`, keyed by citation number;
  `AngiogenesisProcess.REFERENCES`, keyed by string). A tier without a
  `_range_evidence` entry is shown as "evidence not recorded in the schema";
  the previous hard-coded notes and the borrowed default-value citation are
  gone. The OMEX/PDF writers still read no descriptors (see below).

- Both GUIs read `_cbo_term` nowhere and `_visual_effects` in six places; rename
  those reads. `_depends_on` is read once per GUI for display gating; point it
  at `_depends_on_display`.
- `schema_fingerprint()` already canonicalises every field, so adopting the
  format changes both fingerprints once; that is the intended behaviour.
- `extract_parameter_documentation()` and the OMEX metadata writers should emit
  `_ontology_term`, `_reference_paper`, `_literature` into the run record — this
  closes the "ontology terms are inert" gap in the readiness audit.
- A `references.py` registry is added to `vivarium-angio` (moving the inline
  `REFERENCES` dict), so `_literature` resolves the same way in both packages.
- A schema check (`test_parameters_golden.py` is the natural home) asserts every
  exposed parameter carries the required set and no key outside the format.

## How the descriptions reach the audit bundle (2026-10-06)

The schema documents parameters; the run record holds the values that ran.
`vivarium_*/utils/parameter_audit.py` joins the two into one JSON document,
`parameter_audit.json`, bundled into every COMBINE/OMEX archive (V-Cornea:
archive root; angio: `model/`) and listed in `manifest.xml`, with a copy beside
`run_metadata.json`. It is built wherever the live schema exists and handed to
the archive writer, which has no schema of its own:

| Path | Who builds it |
|---|---|
| V-Cornea process (success, failure, timeout) | `VCorneaProcess` before `create_omex_archive` |
| Angio GUI (the normal path; the subprocess exits with `os._exit`) | `AngiogenesisMainWindow._build_parameter_audit` per run, passed to `SimulationWorker(parameter_audit=…)` |
| Angio headless | `AngiogenesisProcess.finish()` |

For every parameter the record carries: run value, documented default and
whether they differ; the three range tiers and the value's position against
each (`within`, `below`, `above`, `undeclared`, `not_applicable`); a
**credibility** verdict — `supported` (inside the evidence-supported range),
`admissible` (inside the declared tiers, no physiological range documented),
`outside_recommended`, `extrapolation` (beyond the documented evidence),
`inadmissible` (outside what the implementation accepts), `unassessable`
(numeric, no range documented) or `not_applicable` (switch/category); the
`_range_evidence` for each tier with citations resolved through the model's
registry; the default's provenance (`_reference_paper`); `_literature`;
ontology term; fitting method; dependencies; affected outputs. A `summary`
block gives counts and the lists of flagged parameters, and is copied into
`run_metadata.json` as `parameter_credibility` so experiment logs can flag
extrapolations without opening the archive.

The PDF reports (`make_omex_summary_pdf.py`, both `make_omex_combo_report.py`)
render a **Parameter Credibility** section from it: a one-line summary, a table
of the parameters an auditor must look at (changed from default or not
`supported`), with the evidence recorded for the tier that decided the verdict,
and a note when replicates of one combination differ in a model parameter.
Control parameters (name, seed, duration, write policy) change by design and
are never reported as findings. Archives without the file render as before.

This closes the readiness-audit gap "schema carries metadata that nothing
downstream consumes": ontology terms, range evidence and literature now reach
the run record, and a bound whose justification is undocumented shows up in the
report as `not recorded`, which is itself an audit finding.
