"""V-Cornea equation registry — the single source for the model's mathematical
formulations, in LaTeX.

Equations are model-level shared objects (one equation often governs many
parameters), so they live here as first-class entities rather than being
duplicated per parameter. A schema parameter links to the equations it
participates in via an `_equations: ['eq:volume_constraint', ...]` field; the GUI
info panel and the Obsidian vault both render the same LaTeX.

LaTeX is written for matplotlib `mathtext` (a subset of LaTeX, no external LaTeX
install needed) AND for MathJax (Obsidian) — both render these strings. Wrap a
`latex` value in `$...$` (inline) or `$$...$$` (display) at the render site.

Each entry:
    name        — human title
    latex       — the formula (no $ delimiters)
    description — one-line plain-language summary
    paper_ref   — where it appears in Vanin et al. 2025
    vault_id    — matching Obsidian note id (or None for sub-terms without a note)
    governs     — keywords / param families this equation drives
"""

EQUATIONS = {
    # ---- Growth & fate (main-text Eqs 1-6; S1/S2 Text) ----
    'eq:hill_egf': {
        'name': 'EGF-Dependent Growth Rate (Hill function)',
        'latex': r'G_{n_{EGF,i}} = \frac{EGF_{n,i}^4}{k_{m_{EGF,i}}^4 + EGF_{n,i}^4}',
        'description': 'Ultrasensitive (n=4) Hill response of growth to local EGF concentration.',
        'paper_ref': 'Eq. 1; S1 Text §S1.1',
        'vault_id': 'eq:hill_egf',
        'governs': ['EGF_STEM_HalfMaxValue', 'EGF_BASAL_HalfMaxValue', 'STEM_beta_EGF', 'BASAL_beta_EGF', 'growth'],
    },
    'eq:hill_density': {
        'name': 'Density-Dependent Growth Inhibition (Hill function)',
        'latex': r'G_{n_{density,i}} = \frac{k_{m_{density,i}}^4}{k_{m_{density,i}}^4 + P_{n,i}^4}',
        'description': 'Inverse Hill (n=4) contact inhibition: growth falls as effective pressure rises.',
        'paper_ref': 'Eq. 2; S1 Text §S1.2',
        'vault_id': 'eq:hill_density',
        'governs': ['DensitySTEM_HalfMaxValue', 'DensityBASAL_HalfMaxValue', 'growth'],
    },
    'eq:total_growth': {
        'name': 'Total Growth Rate',
        'latex': r'G_{n_{total,i}} = \delta_i \times G_{n_{density,i}} \times G_{n_{EGF,i}}',
        'description': 'Net growth = intrinsic doubling rate × density inhibition × EGF stimulation.',
        'paper_ref': 'Eq. 3; S1 Text §S1.4',
        'vault_id': 'eq:total_growth',
        'governs': ['growth', 'EGF_STEM_HalfMaxValue', 'EGF_BASAL_HalfMaxValue',
                    'DensitySTEM_HalfMaxValue', 'DensityBASAL_HalfMaxValue',
                    'InitSTEM_TargetVolume', 'InitBASAL_TargetVolume'],
    },
    'eq:effective_pressure': {
        'name': 'Effective Pressure',
        'latex': r'P_{n,i} = 2\,\lambda_{V,i}\,(v_{n,i} - V_{target,i})',
        'description': 'Pressure felt by a cell from its volume deviation; drives density inhibition.',
        'paper_ref': 'S1 Text §S1.3 (from the volume energy term)',
        'vault_id': None,
        'governs': ['InitSTEM_LambdaVolume', 'InitBASAL_LambdaVolume', 'DensitySTEM_HalfMaxValue', 'DensityBASAL_HalfMaxValue'],
    },
    # ---- Differentiation (Eqs 4-6; S2 Text) ----
    'eq:stem_to_basal': {
        'name': 'LESC → Basal Differentiation',
        'latex': r'P(STEM \to BASAL) = \begin{cases} 1, & \text{if } LIMB \notin N \\ 0, & \text{otherwise} \end{cases}',
        'description': 'Stem cell differentiates the instant it loses contact with the limbal BM.',
        'paper_ref': 'Eq. 4; S2 Text §S2.1',
        'vault_id': 'eq:stem_to_basal',
        'governs': ['differentiation'],
    },
    'eq:basal_to_wing': {
        'name': 'Basal → Wing Differentiation',
        'latex': r'P(BASAL \to WING) = \begin{cases} 1, & \text{if } A_{EpBM} \leq \omega_{contact,basal} \\ 0, & \text{otherwise} \end{cases}',
        'description': 'Basal cell differentiates when its EpBM contact area drops below the threshold.',
        'paper_ref': 'Eq. 5; S2 Text §S2.2',
        'vault_id': 'eq:basal_to_wing',
        'governs': ['differentiation'],
    },
    'eq:wing_to_super': {
        'name': 'Wing → Superficial Differentiation',
        'latex': r'P(WING \to SUPER) = \begin{cases} 1, & \text{if } \{TEAR, WING\} \in N \text{ and } \{BASAL, MEMB, STEM\} \cap N = \emptyset \\ 0, & \text{otherwise} \end{cases}',
        'description': 'Wing cell differentiates on reaching the tear film and losing deep-layer contact.',
        'paper_ref': 'Eq. 6; S2 Text §S2.3',
        'vault_id': 'eq:wing_to_super',
        'governs': ['differentiation'],
    },
    # ---- Mechanics: Hamiltonian and its terms (Eq 7; S3 Text) ----
    'eq:hamiltonian': {
        'name': 'Cellular Potts Model Hamiltonian',
        'latex': r'\Delta H = \Delta H_{contact} + \Delta H_{links} + \Delta H_{volume} + \Delta H_{surface} + \Delta H_{chemotaxis}',
        'description': 'Effective energy minimized by the GGH/CPM Monte-Carlo dynamics.',
        'paper_ref': 'Eq. 7; S3 Text §S3.1',
        'vault_id': 'eq:hamiltonian',
        'governs': ['mechanics', 'movement'],
    },
    'eq:contact': {
        'name': 'Contact (Adhesion) Energy',
        'latex': r"H_{contact} = \sum_{\vec{x},\vec{x}'} J(\tau_{\sigma(\vec{x})}, \tau_{\sigma(\vec{x}')}) (1 - \delta_{\sigma(\vec{x}),\sigma(\vec{x}')})",
        'description': 'Adhesion energy summed over neighboring lattice sites of differing cells.',
        'paper_ref': 'S3 Text §S3.2; S6 Table (J values)',
        'vault_id': None,
        'governs': ['contact_energy'],
    },
    'eq:volume_constraint': {
        'name': 'Volume Constraint',
        'latex': r'H_{volume} = \sum_i \lambda_{V,i}\,(v_i - V_{target,i})^2',
        'description': 'Energy penalty for deviating from target volume (area in 2D).',
        'paper_ref': 'S3 Text §S3.3 (Eq. 22)',
        'vault_id': None,
        'governs': ['InitSTEM_LambdaVolume', 'InitBASAL_LambdaVolume', 'InitWING_LambdaVolume', 'InitSUPER_LambdaVolume',
                    'InitSTEM_TargetVolume', 'InitBASAL_TargetVolume', 'InitWING_TargetVolume', 'InitSUPER_TargetVolume'],
    },
    'eq:surface_constraint': {
        'name': 'Surface Constraint',
        'latex': r'H_{surface} = \sum_i \lambda_{S,i}\,(s_i - S_{target,i})^2',
        'description': 'Energy penalty for deviating from target surface (perimeter in 2D).',
        'paper_ref': 'S3 Text §S3.3 (Eq. 23)',
        'vault_id': None,
        'governs': ['InitSTEM_LambdaSurface', 'InitBASAL_LambdaSurface', 'InitWING_LambdaSurface', 'InitSUPER_LambdaSurface',
                    'InitSTEM_TargetSurface', 'InitBASAL_TargetSurface', 'InitWING_TargetSurface', 'InitSUPER_TargetSurface'],
    },
    'eq:chemotaxis': {
        'name': 'Chemotaxis Energy',
        'latex': r"\Delta H_{chemotaxis} = -\lambda_{c}\,[\,c(\vec{x}') - c(\vec{x})\,]",
        'description': 'Energy bias favoring copy attempts that move a cell up a chemical gradient.',
        'paper_ref': 'S3 Text §S3.4 (Eq. 24)',
        'vault_id': None,
        'governs': ['InitSTEM_LambdaChemo', 'InitBASAL_LambdaChemo', 'InitWING_EGFLambdaChemo'],
    },
    'eq:links': {
        'name': 'Hookean Link (FPP) Energy',
        'latex': r'H_{link} = \lambda_{link}\,(d_{ij} - L_{ij})^2, \quad F = 2\,\lambda_{link}\,(d_{ij} - L_{ij})',
        'description': 'Spring energy and tension between linked cell centers (superficial-layer cohesion).',
        'paper_ref': 'S3 Text §S3.2 (Eq. 17)',
        'vault_id': None,
        'governs': ['LINKWALL_lambda_distance', 'LINKSUPER_lambda_distance', 'LINKSUPER_target_distance',
                    'LINKWALL_max_distance', 'LINKSUPER_max_distance'],
    },
    # ---- Death / turnover (Eq 8; S4 Text) ----
    'eq:sloughing': {
        'name': 'Superficial Cell Sloughing Probability',
        'latex': r'P_{slough}:\quad U(0,1) < \frac{1}{3 \times DaytoMCS}',
        'description': 'Per-MCS probabilistic shedding of tear-contacting superficial cells (turnover).',
        'paper_ref': 'Eq. 8; S4 Text §S4.1',
        'vault_id': 'eq:sloughing',
        'governs': ['DeathTimeScalar', 'sloughing'],
    },
    # ---- Chemical fields (Eqs 9-10; S5 Text) ----
    'eq:egf_diffusion': {
        'name': 'EGF Reaction-Diffusion Equation',
        'latex': r'\frac{\partial c_{EGF}}{\partial t} = D_{EGF}(x,y)\,\nabla^2 c_{EGF} - k_{d_{EGF}}\,c_{EGF} + \Omega_{EGF}(x,y,t)',
        'description': 'PDE for the EGF field: cell-type-dependent diffusion, global decay, tear source.',
        'paper_ref': 'Eq. 9-10; S5 Text',
        'vault_id': 'eq:egf_diffusion',
        'governs': ['EGF_SUPERDiffCoef', 'EGF_GlobalDecay', 'EGF_ScreteAmount',
                    'EGF_FieldUptakeBASAL', 'EGF_FieldUptakeSTEM', 'EGF_FieldUptakeSuper', 'EGF_FieldUptakeWing'],
    },
    'eq:sls_diffusion': {
        'name': 'Chemical Injury (SLS) Reaction-Diffusion',
        'latex': r'\frac{\partial c_{SLS}}{\partial t} = D_{SLS}(x,y)\,\nabla^2 c_{SLS} - k_{d_{SLS}}\,c_{SLS}',
        'description': 'PDE for the SLS injury field; cleared only by cell death and tear washout (k_d≈0).',
        'paper_ref': 'S4 Text §S4.4',
        'vault_id': None,
        'governs': ['SLS_STEMDiffCoef', 'SLS_BASALDiffCoef', 'SLS_WINGDiffCoef', 'SLS_SUPERDiffCoef',
                    'SLS_MEMBDiffCoef', 'SLS_LIMBDiffCoef', 'SLS_TEARDiffCoef', 'SLS_Concentration', 'SLS_Threshold'],
    },
}


def equations_for_param(param_name):
    """Return the equation entries whose `governs` list includes this parameter."""
    return {eid: e for eid, e in EQUATIONS.items() if param_name in e.get('governs', [])}


def get_equation(eid):
    return EQUATIONS.get(eid)


# Supporting paper references per equation (numbers -> references.py bibliography).
EQUATION_REFS = {
    'eq:hill_egf': [88],
    'eq:hill_density': [89],
    'eq:total_growth': [88, 89],
    'eq:effective_pressure': [89],
    'eq:sloughing': [90, 108],
    'eq:egf_diffusion': [93, 50, 94],
}


def refs_for(eid):
    return EQUATION_REFS.get(eid, [])
