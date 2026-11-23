"""One exposed parameter, described in the common descriptor format.

This file is the worked example for the manuscript (Section 2.2, "the schema as
a model knowledge layer"). It shows every field of the common format populated
for a single real parameter — ``jem``, the endothelial-cell/medium contact
energy of the angiogenesis model — followed by the same format applied to a
V-Cornea parameter, to show that the format is independent of the model and of
the integrated/decoupled implementation pattern.

Values are taken from the current schemas verbatim. Where neither schema
asserts something, the field is left ``None`` rather than invented; the format
makes such gaps visible instead of hiding them.

The field groups follow the three handoffs the manuscript describes:
    developer -> operator  (what it is, what it does, what is safe)
    schema    -> machine   (what the simulator and GUI need to run and render)
    run       -> auditor   (where the value came from, what evidence backs it)

Run ``python docs/parameter_descriptor_example.py`` to check both examples
against the field list in ``parameter_descriptor_format.md``.
"""

# --------------------------------------------------------------------------
# The common field set, grouped. Order here is the canonical presentation
# order. "required" fields must be present on every exposed parameter (None
# is allowed where the fact is unknown); the rest are optional and may be
# omitted when they do not apply to a parameter at all.
# --------------------------------------------------------------------------
FIELD_GROUPS = {
    'execution contract': {                   # consumed by the simulator / Vivarium
        'required': ['_default', '_updater', '_emit', '_scope', '_parameter_type'],
        'optional': ['_validation_pattern', '_max_length', '_auto_generate',
                     '_debug_parameter'],
    },
    'identity and meaning': {                 # developer -> operator
        'required': ['_display_name', '_description', '_category', '_subcategory',
                     '_expert_level'],
        'optional': ['_long_description', '_conceptual_hint', '_biological_meaning',
                     '_model_context', '_implementation_pattern', '_ontology_term'],
    },
    'units': {
        'required': ['_unit', '_dimension'],
        'optional': ['_unit_long', '_display_unit', '_conversion_factor',
                     '_value_mapping'],
    },
    'admissible and supported values': {      # three tiers + their rationale
        'required': ['_range_evidence'],   # always present, one entry per tier; None = tier not declared
        'optional': ['_mathematical_range', '_physiological_range',
                     '_recommended_range', '_warning_threshold', '_presets'],
    },
    'relationships and expected effect': {
        'required': ['_related_parameters', '_dependencies', '_affects_output'],
        'optional': ['_expected_behavior', '_equations', '_output_files',
                     '_performance_impact', '_storage_impact'],
    },
    'evidence': {                             # run -> auditor
        'required': ['_reference_paper', '_literature', '_fitting_method'],
        'optional': ['_measurable', '_experimental_assay'],
    },
    'presentation': {                         # GUI only; never affects execution
        'required': [],
        'optional': ['_hidden_basic', '_depends_on_display', '_conditional_display',
                     '_gui_hints'],
    },
}


# --------------------------------------------------------------------------
# Example 1 — integrated pattern (Angio-GUI / vivarium-angio)
# --------------------------------------------------------------------------
JEM = {
    # ---- execution contract -------------------------------------------------
    '_default': 2.0,
    '_updater': 'set',
    '_emit': True,
    '_scope': 'model',                   # 'model' = passed to the simulator; 'wrapper' = consumed by the orchestration layer
    '_parameter_type': 'biophysical',    # biophysical | kinetic | geometric | initial_condition | control

    # ---- identity and meaning ----------------------------------------------
    '_display_name': 'EC-Medium Adhesion Energy',
    '_description': ('Contact energy between endothelial cells and the surrounding medium. '
                     'Higher values cause cells to minimise medium contact, promoting '
                     'aggregation into compact clusters.'),
    '_category': 'Cell Properties',
    '_subcategory': 'Adhesion',
    '_expert_level': 'basic',            # basic | intermediate | advanced
    '_long_description': ('Controls how much cells prefer contact with other cells over '
                          'exposure to medium. High values (>6) cause the initially connected '
                          'network to fragment into separate aggregates, so this parameter '
                          'decides whether the simulation produces a connected network or '
                          'isolated clusters.'),
    '_conceptual_hint': None,            # operator-level intuition; not yet written for this parameter
    '_biological_meaning': ('Cell-matrix adhesion strength. In vivo this corresponds to '
                            'integrin-mediated adhesion to the extracellular matrix. High '
                            'values simulate conditions where cells prefer cell-cell over '
                            'cell-matrix contact, leading to aggregation.'),
    '_model_context': ('EC-Medium contact energy J(EC, Medium) in the Cellular Potts '
                       'Hamiltonian; critical parameter controlling aggregation versus '
                       'network formation.'),
    '_implementation_pattern': None,     # code location of the assignment; not yet recorded for this parameter
    '_ontology_term': 'CBO:0000016',     # Cell Behavior Ontology: cell-matrix adhesion

    # ---- units --------------------------------------------------------------
    '_unit': 'Arbitrary Energy Units',
    '_dimension': 'energy',
    '_unit_long': 'Energy units (dimensionless in the Cellular Potts Model)',
    '_display_unit': None,               # shown as stored
    '_conversion_factor': None,          # display = stored x factor; None = identity
    '_value_mapping': None,              # only for enumerated/boolean parameters

    # ---- admissible and supported values -----------------------------------
    '_mathematical_range': (0.0, 100.0),   # the implementation accepts these; outside is an error
    '_physiological_range': (2.0, 16.0),   # supported by evidence; outside is an extrapolation
    '_recommended_range': (2.0, 10.0),     # advised for this model's context of use
    '_range_evidence': {                 # one entry per tier; 'basis' says what kind of justification it is
        'mathematical': {
            'basis': 'numerical_stability',   # numerical_stability | literature | calibration | expert_judgement | exploratory
            'refs': [],                        # keys into the model's references registry
            'locator': None,
            'note': 'Range over which the model stays numerically stable; not evidence-based.',
        },
        'physiological': {
            'basis': 'literature',
            'refs': ['merks2006'],
            'locator': {'table': 'Table 1', 'equation': None, 'page': 47},
            'note': 'Span of J values used in the reference study and its aggregation experiments (8-16).',
        },
        'recommended': {
            'basis': 'expert_judgement',
            'refs': [],
            'locator': None,
            'note': 'Upper bound still to be justified by the modeler.',
        },
    },
    '_warning_threshold': 12.0,
    '_presets': {
        'network_forming': 2.0,
        'moderate_aggregation': 4.0,
        'strong_aggregation': 8.0,
        'extreme_aggregation': 12.0,
    },

    # ---- relationships and expected effect ---------------------------------
    '_related_parameters': ['jee'],
    '_dependencies': {
        'jee': 'Ratio jem/jee determines aggregation behaviour: >1 promotes clustering, <1 promotes spreading',
    },
    '_affects_output': ['network_fragmentation', 'cell_cluster_count', 'cluster_compactness'],
    '_expected_behavior': {
        'low_value': 'Cells form connected networks',
        'high_value': 'Cells aggregate into separate compact clusters',
        'threshold': 6.0,                # approximate transition between regimes
    },
    '_equations': None,                  # key into an equation registry; vivarium-angio has none yet
    '_output_files': None,               # model parameters do not own output files
    '_performance_impact': None,
    '_storage_impact': None,

    # ---- evidence -----------------------------------------------------------
    '_reference_paper': {                # provenance of the DEFAULT value, with a locator
        'source': 'Merks et al., 2006',
        'title': 'Cell elongation is key to in silico replication of in vitro vasculogenesis and subsequent remodeling',
        'journal': 'Developmental Biology',
        'year': 2006,
        'doi': '10.1016/j.ydbio.2005.10.003',
        'value': 2.0,
        'locator': {'table': 'Table 1', 'equation': 'H_adhesion term in Eq. 1', 'page': 47},
        'notes': 'Default value. Higher values (8-16) tested for aggregation studies.',
    },
    '_literature': ['merks2006'],        # keys into the model's references registry
    '_fitting_method': 'literature_based',   # literature_based | fitted | estimated | calibrated
    '_measurable': False,                # directly measurable in an experiment?
    '_experimental_assay': None,

    # ---- presentation -------------------------------------------------------
    '_hidden_basic': False,
    '_depends_on_display': None,         # parameters whose values decide whether this one is shown
    '_conditional_display': None,        # predicate(params) -> bool; not part of the fingerprint
    '_gui_hints': {
        'widget_type': 'slider',
        'slider_step': 0.5,
        'show_preset_buttons': True,
        'highlight_major_changes': True,
    },
}


# --------------------------------------------------------------------------
# Example 2 — decoupled pattern (V-Cornea GUI / vivarium-vcornea)
# Same format, different model, different implementation pattern.
# --------------------------------------------------------------------------
SLS_CONCENTRATION = {
    '_default': 750.0,
    '_updater': 'set',
    '_emit': True,
    '_scope': 'model',
    '_parameter_type': 'initial_condition',

    '_display_name': 'Initial Chemical Concentration',
    '_description': ('Initial concentration of the applied SLS chemical insult. Three '
                     'depth-of-injury presets follow the Scott et al. 2010 classification: '
                     'slight = 750, mild = 1500, moderate = 2500.'),
    '_category': 'Injury Settings',
    '_subcategory': 'Chemical Injury',
    '_expert_level': 'basic',
    '_long_description': None,
    '_conceptual_hint': ('Initial strength of the chemical insult, in arbitrary units mapped to '
                         'injury DEPTH: 750 = slight (superficial only), 1500 = mild (full '
                         'epithelium, basement membrane intact), 2500 = moderate (destroys the '
                         'basement membrane). A depth-of-injury proxy, not a molar concentration.'),
    '_biological_meaning': None,
    '_model_context': 'Sets c0_chem (Eq. 32/33).',
    '_implementation_pattern': ('Initial value seeded into the SLS field at injury time by the '
                                'injury steppable (Gaussian pulse or uniform coating). From '
                                '`Parameters.py`.'),
    '_ontology_term': 'cbo:ChemicalDensity',

    '_unit': 'Arbitrary Units',
    '_dimension': 'concentration',
    '_unit_long': None,
    '_display_unit': None,
    '_conversion_factor': None,
    '_value_mapping': None,

    # no _mathematical_range / _physiological_range declared: the gap is recorded
    # in _range_evidence below instead of as a None tuple (GUIs unpack tuples)
    '_recommended_range': (100.0, 5000.0),
    '_range_evidence': {
        'mathematical': None,            # no admissible range declared yet
        'physiological': None,           # arbitrary units: no physiological range exists
        'recommended': {
            'basis': 'exploratory',
            'refs': [],
            'locator': None,
            'note': 'Normalised/arbitrary concentration; the three presets are the evidence-backed operating points.',
        },
    },
    '_warning_threshold': None,
    '_presets': {'slight': 750.0, 'mild': 1500.0, 'moderate': 2500.0},

    '_related_parameters': None,
    '_dependencies': {
        'IsInjury': 'Only meaningful when an injury is applied',
        'InjuryType': 'Only meaningful for chemical exposure (InjuryType = False)',
    },
    '_affects_output': None,
    '_expected_behavior': None,
    '_equations': None,                  # Eq. 32/33 are not yet in equations.py
    '_output_files': None,
    '_performance_impact': None,
    '_storage_impact': None,

    '_reference_paper': {
        'source': 'Vanin et al., 2025',
        'title': None,
        'journal': 'PLOS Computational Biology',
        'year': 2025,
        'doi': None,
        'value': 750.0,
        'locator': {'table': 'S10 Table', 'equation': None, 'page': None},
        'notes': 'Depth-of-injury classification after Scott et al. 2010.',
    },
    '_literature': [3],                  # Scott et al. 2010, via the model's references registry
    '_fitting_method': None,             # schema does not say how 750 was chosen
    '_measurable': None,
    '_experimental_assay': None,

    '_hidden_basic': False,
    '_depends_on_display': ['IsInjury', 'InjuryType'],
    '_conditional_display': lambda params: params.get('IsInjury', False) and not params.get('InjuryType', False),
    '_gui_hints': None,
}


def all_fields():
    out = []
    for g in FIELD_GROUPS.values():
        out += g['required'] + g['optional']
    return out


def check(descriptor, name):
    fields = all_fields()
    required = [f for g in FIELD_GROUPS.values() for f in g['required']]
    unknown = [k for k in descriptor if k not in fields]
    missing = [f for f in required if f not in descriptor]
    assert not unknown, f'{name}: keys outside the format: {unknown}'
    assert not missing, f'{name}: required keys absent: {missing}'
    unpopulated = [k for k, v in descriptor.items() if v is None]
    print(f'{name}: {len(descriptor)} fields, {len(unpopulated)} left None: {unpopulated}')


if __name__ == '__main__':
    assert len(all_fields()) == len(set(all_fields())), 'duplicate field in FIELD_GROUPS'
    print(f'common format: {len(all_fields())} fields in {len(FIELD_GROUPS)} groups')
    check(JEM, 'jem (angio)')
    check(SLS_CONCENTRATION, 'SLS_Concentration (vcornea)')
