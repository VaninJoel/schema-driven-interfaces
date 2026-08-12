import subprocess
import os
import ast
import pandas as pd
import tempfile
import shutil
import json
import glob
import uuid
from pathlib import Path
from vivarium.core.process import Process

# TODO Redefine the defaults based on the paper and the actual references for the parameters

class VCorneaProcess(Process):
    """
    Enhanced Vivarium wrapper for the vCornea CompuCell3D model.
    
    Features:
    - Tracks parameter changes from defaults
    - Generates meaningful run names
    - Saves comprehensive metadata
    - Maintains experiment logs
    - Redirects outputs to external directories
    """

    defaults = {
        'vcornea_project_path': None,  # Path to the CC3D project directory
        
        'conda_executable_path': os.environ.get('CONDA_EXE', 'conda'),  # Path to conda executable if not in PATH
        'cc3d_conda_env_name': 'vc',  # Name of conda environment with CC3D
        'python_executable': 'python',  # Usually just 'python' when using conda
        
        'output_base_dir': None, #Path.cwd()/ "simulation_results",  # Permanent location        
        'run_name': None,  # Custom name for this run; if None, generates descriptive name
        'max_params_in_name': 3,  # Max number of changed parameters to include in auto-generated names
        'replicates': 1,  # Number of times to run the simulation with the same parameters
        'run_id': 0,
        # Parameter-scan provenance, set by the GUI for sweep/batch runs (control-only;
        # never written to Parameters.py because sim_params is built from the CC3D
        # schema ports, not from these keys). None for ordinary single runs.
        'parameter_scan': None,       # {param: [values, ...]} full swept space
        'scan_point': None,           # {param: value} this run's point in the scan
        'combination_index': None,    # 1-based index of this point
        'total_combinations': None,   # total scan points (cartesian product size)
        # OMEX provenance: who ran the experiment (set the parameters). Attribution,
        # not authentication. dict {given, family, email, orcid} or a plain name.
        'creator': None,
        # Wall-clock ceiling per replicate. Previously hardcoded at 24h, which is
        # far too long for a short exploratory sweep to fail fast and too short for
        # the 183-day paper-replication protocol on slow hardware.
        'run_timeout_seconds': 86400,
    }

    # Sentinel for "no seed chosen yet". CC3D seeds are non-negative, so a negative
    # value is unambiguous. Each replicate's seed is resolved before launch.
    AUTO_SEED = -1

    # Named scenarios surfaced in the GUI's preset dropdown. Each preset
    # supplies overrides on top of the schema defaults; unset keys keep their
    # _default value. SimTime / InjuryTime are in DAYS at this layer.
    PRESETS = {
        'Homeostasis (no injury)': {
            'name': 'Homeostasis (no injury)',
            'description': 'Undisturbed epithelium observed for 24 days. Useful to confirm the model holds steady state before introducing perturbations.',
            'reference': 'Vanin et al., 2025 (Section 1.2.2 — Epithelial homeostasis)',
            'parameters': {
                'IsInjury': False,
                'SimTime': 24,
            },
        },
        'Chemical exposure (paper defaults)': {
            'name': 'Chemical exposure (paper defaults)',
            'description': 'SLS chemical insult with schema defaults from Table S8.4. Three days of relaxation, then chemical injury, observed through the 21-day categorization window.',
            'reference': 'Vanin et al., 2025 (Table S8.4 chemical-injury baseline)',
            'parameters': {
                'IsInjury': True,
                'InjuryType': False,  # Chemical Exposure
                'InjuryTime': 3.0,
                'SimTime': 24,
            },
        },
        'Mechanical ablation (paper defaults)': {
            'name': 'Mechanical ablation (paper defaults)',
            'description': 'Mechanical removal of epithelium with default ablation radius. Three days of relaxation, then ablation, observed through the 21-day categorization window.',
            'reference': 'Vanin et al., 2025 (Table S8.4 mechanical-ablation baseline)',
            'parameters': {
                'IsInjury': True,
                'InjuryType': True,  # Mechanical Ablation
                'InjuryTime': 3.0,
                'SimTime': 24,
            },
        },
        'Paper replication (183 days)': {
            'name': 'Paper replication (183 days)',
            'description': 'Long-horizon run matching the paper protocol: 3 days pre-injury relaxation + 180 days post-injury observation. Long runtime; intended for late-stage outcome categorization.',
            'reference': 'Vanin et al., 2025 (long-term categorization protocol)',
            'parameters': {
                'IsInjury': True,
                'InjuryType': False,  # Chemical Exposure
                'InjuryTime': 3.0,
                'SimTime': 183,
            },
        },
    }

    def get_preset_names(self):
        """Return the list of preset names for the GUI dropdown."""
        return list(self.PRESETS.keys())

    def get_preset(self, preset_name):
        """Return a preset definition (dict with 'name', 'description', 'parameters')
        or None if the preset is not recognised."""
        return self.PRESETS.get(preset_name)

    def __init__(self, parameters=None):
        super().__init__(parameters)

        project_path = self.parameters.get('vcornea_project_path')
        
        if not project_path:
            project_path = self._auto_discover_vcornea()
        
        if not project_path:
            raise ValueError(
                "vCornea project not found. Either:\n"
                "1. Set VCORNEA_PROJECT_PATH environment variable\n"
                "2. Pass 'vcornea_project_path' parameter\n"
                "3. Place vCornea repository in standard location relative to vivarium-vcornea"
            )
                
        self.project_path = Path(project_path)
        
        if not self.project_path.exists():
            raise FileNotFoundError(f"vCornea project path not found: {self.project_path}")
        
        
        # Check for required files
        required_files = [
            'vCornea_v2.cc3d',
            'Simulation/vCornea_v2.py',
            'Simulation/vCornea_v2Steppables.py', 
            'Simulation/vCornea_v2.xml',
            'Epithelium.piff'
        ]
        
        for req_file in required_files:
            file_path = self.project_path / req_file
            if not file_path.exists():
                raise FileNotFoundError(f"Required vCornea file not found: {file_path}")

    def ports_schema(self):
        """
        Define inputs and outputs for the vCornea wrapper.
        Displays parameters with real-world biological/physical units for GUI clarity.
        Includes conversion factors to translate between display units and internal model units.
        """
        # [cite_start]Define base conversion factors based on model setup [cite: 1113, 1115]
        PIXEL_TO_MICRONS = 2.0  # 1 pixel = 2 µm
        AREA_CONVERSION = PIXEL_TO_MICRONS**2 # 1 pixel^2 = 4 µm^2
        MCS_TO_MINUTES = 6.0    # 1 MCS = 6 min
        MCS_TO_HOURS = 0.1      # 1 MCS = 0.1 hr
        MCS_TO_DAYS = 1.0 / 240.0 # 1 MCS = 1/240 day
        DIFFUSION_CONVERSION_UM2_PER_MIN = AREA_CONVERSION / MCS_TO_MINUTES # (µm²/pixel²) / (min/MCS) = µm²/min per pixel²/MCS
        RATE_CONVERSION_PER_HOUR = 1.0 / MCS_TO_HOURS # (1/MCS) / (hr/MCS) = 1/hr per 1/MCS

        schema = {
            'inputs': {
                # --- STEM Cell Parameters ---
                'InitSTEM_LambdaSurface': {
                    '_default': 2.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Stem Surface Coefficient',
                    '_description': 'Penalty factor for stem cell deviation from target surface area. Higher values mean stricter shape control.',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Stem Cells',
                    '_unit': 'Arbitrary Energy Units', # Energy unit is arbitrary in GGH/CPM
                    '_dimension': 'energy',
                    '_recommended_range': (0.1, 10.0),  # arbitrary CPM energy units; exploratory, not physiological
                    '_expert_level': 'advanced',
                    '_hidden_basic': True,
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 2.0},
                    '_cbo_term': 'cbo:AreaEnergy',
                    '_model_context': 'Parameter λs (Eq. 23) for SurfaceConstraint Hamiltonian term.',
                    '_conceptual_hint': 'λs is the surface-constraint stiffness — how strongly a cell holds its target perimeter. Higher λs gives rounder, more regular, stiffer cells; set too high it suppresses the membrane fluctuations the Monte-Carlo dynamics need to move at all. Arbitrary CPM energy units.',
                    '_implementation_pattern': 'Applied as `cell.lambdaSurface = self.InitSTEM_LambdaSurface` in `ConstraintInitializerSteppable.start()`; weights the SurfaceConstraint energy for stem cells. From `Parameters.py`.',
                    '_related_parameters': ['InitSTEM_TargetSurface'], # Simplified dependencies
                },
                'InitSTEM_TargetSurface': {
                    '_default': 18.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Stem Target Surface Area',
                    '_description': 'Ideal surface area (perimeter in 2D) each stem cell tries to maintain.',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Stem Cells',
                    '_unit': 'µm', # Perimeter length
                    '_dimension': 'length',
                    '_physiological_range': (10, 30),  # SIM units (voxel); displays in µm
                    '_expert_level': 'intermediate',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 18.0},
                    '_cbo_term': 'cbo:SurfaceArea',
                    '_model_context': 'Parameter S_target (Eq. 23) for SurfaceConstraint Hamiltonian term.',
                    '_conceptual_hint': "Target surface is the cell's preferred perimeter (a length in 2D); with the surface coefficient λs it regularizes cell shape. Higher targets permit more elongated or ruffled membranes; the constraint keeps cells compact. It shapes cells rather than sizing them — that is target volume's job.",
                    '_implementation_pattern': "Applied as `cell.targetSurface = self.InitSTEM_TargetSurface` in `ConstraintInitializerSteppable.start()`; the SurfaceConstraint plugin regularizes each stem cell's perimeter toward this value. From `Parameters.py`.",
                    '_literature': [85],  # paper ref numbers -> references.py
                    '_related_parameters': ['InitSTEM_LambdaSurface'],
                },
                'InitSTEM_LambdaVolume': {
                    '_default': 2.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Stem Volume Coefficient',
                    '_description': 'Penalty factor for stem cell deviation from target volume. Higher values mean stricter volume control.',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Stem Cells',
                    '_unit': 'Arbitrary Energy Units',
                    '_dimension': 'energy',
                    '_recommended_range': (0.1, 10.0),  # arbitrary CPM energy units; exploratory, not physiological
                    '_expert_level': 'advanced',
                    '_hidden_basic': True,
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 2.0},
                    '_cbo_term': 'cbo:VolumeEnergy',
                    '_model_context': 'Parameter λv (Eq. 22) for VolumeConstraint Hamiltonian term and Pressure calculation (Eq. 6).',
                    '_conceptual_hint': 'λv is the volume-constraint stiffness — how hard a cell resists deviating from its target area. High λv gives rigid, size-locked cells; low λv gives squishy, deformable ones. λv also feeds the effective pressure that drives density-dependent growth inhibition, so it indirectly couples mechanics to proliferation. Arbitrary CPM energy units — tune by behavior, not by measurement.',
                    '_implementation_pattern': 'Applied as `cell.lambdaVolume = self.InitSTEM_LambdaVolume` in `ConstraintInitializerSteppable.start()`; weights the VolumeConstraint energy for stem cells. From `Parameters.py`.',
                    '_related_parameters': ['InitSTEM_TargetVolume'],
                },
                'InitSTEM_TargetVolume': {
                    '_default': 25.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Stem Target Volume',
                    '_description': 'Ideal volume (area in 2D) each stem cell tries to maintain.',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Stem Cells',
                    '_unit': 'µm²', # Area in 2D
                    '_dimension': 'area',
                    '_physiological_range': (15, 40),  # SIM units (voxel^2); displays in µm²
                    '_expert_level': 'intermediate',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 25.0},
                    '_cbo_term': 'cbo:Volume',
                    '_model_context': 'Parameter V_target (Eq. 22, 8) for VolumeConstraint and Growth. Represents TargetVolume state variable.',
                    '_conceptual_hint': 'Target volume and the volume coefficient λv together set how strongly a cell holds its size. Raising it makes cells larger (fewer per layer → thicker, fewer-celled epithelium); lowering it packs more, smaller cells. Because mitosis triggers at 2× the initial volume, target volume also paces division. Keep it within the 10–30 µm cell-diameter envelope or emergent thickness and turnover drift from the calibrated targets.',
                    '_implementation_pattern': 'Applied per cell in `ConstraintInitializerSteppable.start()` as `cell.targetVolume = self.InitSTEM_TargetVolume` for each stem cell; the CPM VolumeConstraint plugin then relaxes the cell toward this area each MCS. Stored in `Parameters.py` (pixels) and imported via `from Parameters import *`.',
                    '_literature': [85],  # paper ref numbers -> references.py
                    '_related_parameters': ['InitSTEM_LambdaVolume', 'GrowthControl'],
                },
                'DensitySTEM_HalfMaxValue': {
                    '_default': 125,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Stem Density Growth Inhibition (Km)',
                    '_description': 'Cell pressure (related to density) at which stem cell growth rate is halved.',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Stem Cells',
                    '_unit': 'Arbitrary Pressure Units', # Derived from LambdaVolume * Volume difference
                    '_dimension': 'pressure',
                    '_recommended_range': (50, 300),  # arbitrary CPM pressure units; exploratory, not physiological
                    '_expert_level': 'intermediate',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 125},
                    '_cbo_term': 'cbo:CellGrowth',
                    '_model_context': 'Parameter Km_density (Eq. 4) affecting Growth behavior sensitivity to crowding.',
                    '_related_parameters': ['InitSTEM_LambdaVolume', 'InitSTEM_TargetVolume', 'GrowthControl'],
                    '_conceptual_hint': 'Half-max effective pressure for contact inhibition (inverse n=4 Hill): the crowding level that halves growth. Higher tolerates more crowding before stopping; lower inhibits earlier. 125 (arbitrary pressure units) was fitted so steady-state density gives 5–7 layers.',
                    '_implementation_pattern': 'Consumed by `GrowthSteppable` in the density-inhibition Hill term (Eq. 2) for stem cells. From `Parameters.py`.',
                    '_literature': [89],  # paper ref numbers -> references.py
                },
                'EGF_STEM_HalfMaxValue': {
                    '_default': 3.5,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Stem EGF Growth Sensitivity (Km)',
                    '_description': 'EGF concentration at which stem cell growth rate is halved.',
                    '_category': 'Growth Factors',
                    '_subcategory': 'EGF Response',
                    '_unit': 'Normalized Concentration',
                    '_dimension': 'concentration',
                    '_recommended_range': (1.0, 10.0),  # normalized/arbitrary concentration; exploratory, not physiological
                    '_expert_level': 'basic',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 3.5},
                    '_cbo_term': 'cbo:CellGrowth',
                    '_model_context': 'Parameter Km_EGF (Eq. 1) affecting Growth behavior sensitivity to EGF.',
                    '_related_parameters': ['EGF_ScreteAmount', 'EGF_GlobalDecay', 'GrowthControl'],
                    '_conceptual_hint': 'The EGF level at which stem-cell growth runs at half maximum (midpoint of the n=4 Hill switch). Lower km = more EGF-sensitive. Stem km (3.5) sits below basal (7.0), so stem cells switch on at lower EGF, keeping the limbus proliferative. Fitted to hit physiological thickness and turnover (S1 Text §S1.5).',
                    '_implementation_pattern': 'Consumed by `GrowthSteppable` in the EGF-dependent Hill growth term (Eq. 1) for stem cells; declared class-level in ConstraintInitializerSteppable and copied into GrowthSteppable. From `Parameters.py`.',
                    '_literature': [88],  # paper ref numbers -> references.py
                },
                'STEM_beta_EGF': {
                    '_default': 1,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Stem EGF Dependence Factor',
                    '_description': 'Factor β scaling the influence of EGF on stem cell growth rate (0=none, 1=full). Source steppable line 582-584 computes G_EGF = β·Hill(EGF) + (1-β).',
                    '_category': 'Growth Factors',
                    '_subcategory': 'EGF Response',
                    '_unit': 'dimensionless',
                    '_dimension': 'dimensionless',
                    '_recommended_range': (0.0, 1.0),  # exploratory range (dimensionless)
                    '_expert_level': 'intermediate',
                    '_reference_paper': {'source': 'Vanin et al., 2025 (S1 Text Eq. S7)', 'value': 1.0, 'detail': 'Implicit β parameter for Hill function combining EGF dependence with baseline (paper sets β=1 → fully EGF-dependent).'},
                    '_cbo_term': 'cbo:CellGrowth',
                    '_model_context': 'Modulates the impact of G_EGF term in Growth behavior (Eq. 1, S1 Text S1.1).',
                    '_related_parameters': ['EGF_STEM_HalfMaxValue', 'GrowthControl'],
                    '_conceptual_hint': 'Dimensionless blend (β) between EGF-gated and baseline growth: G_EGF = β·Hill(EGF) + (1−β). β=1 (paper) makes stem growth fully EGF-dependent; β=0 makes it EGF-independent. Usually left at 1; lower it to probe EGF-independent proliferation.',
                    '_implementation_pattern': 'Read by `GrowthSteppable`; the beta factor blends EGF-dependence with a baseline in the stem growth term. From `Parameters.py`.',
                    '_literature': [88],  # paper ref numbers -> references.py
                },
                'InitSTEM_LambdaChemo': {
                    '_default': 100.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Stem Movement Bias Chemotaxis Strength',
                    '_description': 'Strength of stem cell directed movement towards the Movement Bias chemical gradient.',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Stem Cells',
                    '_unit': 'Arbitrary Energy Units', # Lambda_c * concentration difference is energy
                    '_dimension': 'energy',
                    '_recommended_range': (10.0, 1000.0),  # arbitrary CPM energy units; exploratory, not physiological
                    '_expert_level': 'advanced',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 100.0},
                    '_cbo_term': 'cbo:Chemotaxis',
                    '_model_context': 'Parameter λc (Eq. 24) for Chemotaxis_MBias Hamiltonian term influencing Movement.',
                    '_conceptual_hint': 'λc sets how strongly the cell biases its movement up the Movement-Bias chemoattractant gradient (limbus → periphery). Basal λc (1000) is an order of magnitude above stem (100), which drives centripetal migration of progeny away from the limbal niche while stem cells stay put. Arbitrary CPM energy units.',
                    '_implementation_pattern': 'Sets the chemotaxis weight (lambda_c) for stem cells toward the Movement-Bias field via the CC3DML Chemotaxis plugin (configured in ConstraintInitializerSteppable). From `Parameters.py`.',
                    '_related_parameters': ['MovementBiasScreteAmount', 'MovementBiasUptake'],
                },

                # --- BASAL Cell Parameters ---
                'InitBASAL_LambdaSurface': {
                    '_default': 2.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Basal Surface Coefficient',
                    '_description': 'Penalty factor for basal cell deviation from target surface area.',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Basal Cells',
                    '_unit': 'Arbitrary Energy Units',
                    '_dimension': 'energy',
                    '_recommended_range': (0.1, 10.0),  # arbitrary CPM energy units; exploratory, not physiological
                    '_expert_level': 'advanced',
                    '_hidden_basic': True,
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 2.0},
                    '_cbo_term': 'cbo:AreaEnergy',
                    '_model_context': 'Parameter λs (Eq. 23) for SurfaceConstraint Hamiltonian term.',
                    '_conceptual_hint': 'λs is the surface-constraint stiffness — how strongly a cell holds its target perimeter. Higher λs gives rounder, more regular, stiffer cells; set too high it suppresses the membrane fluctuations the Monte-Carlo dynamics need to move at all. Arbitrary CPM energy units.',
                    '_implementation_pattern': 'Applied as `cell.lambdaSurface = self.InitBASAL_LambdaSurface` in `ConstraintInitializerSteppable.start()`; weights the SurfaceConstraint energy for basal cells. From `Parameters.py`.',
                     '_related_parameters': ['InitBASAL_TargetSurface'],
               },
                'InitBASAL_TargetSurface': {
                    '_default': 20.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Basal Target Surface Area',
                    '_description': 'Ideal surface area (perimeter in 2D) each basal cell tries to maintain.',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Basal Cells',
                    '_unit': 'µm',
                    '_dimension': 'length',
                    '_physiological_range': (10, 35),  # SIM units (voxel); displays in µm
                    '_expert_level': 'intermediate',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 20.0},
                    '_cbo_term': 'cbo:SurfaceArea',
                    '_model_context': 'Parameter S_target (Eq. 23) for SurfaceConstraint Hamiltonian term.',
                    '_conceptual_hint': "Target surface is the cell's preferred perimeter (a length in 2D); with the surface coefficient λs it regularizes cell shape. Higher targets permit more elongated or ruffled membranes; the constraint keeps cells compact. It shapes cells rather than sizing them — that is target volume's job.",
                    '_implementation_pattern': "Applied as `cell.targetSurface = self.InitBASAL_TargetSurface` in `ConstraintInitializerSteppable.start()`; the SurfaceConstraint plugin regularizes each basal cell's perimeter toward this value. From `Parameters.py`.",
                    '_literature': [85],  # paper ref numbers -> references.py
                    '_related_parameters': ['InitBASAL_LambdaSurface'],
                },
                'InitBASAL_LambdaVolume': {
                    '_default': 2.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Basal Volume Coefficient',
                    '_description': 'Penalty factor for basal cell deviation from target volume.',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Basal Cells',
                    '_unit': 'Arbitrary Energy Units',
                    '_dimension': 'energy',
                    '_recommended_range': (0.1, 10.0),  # arbitrary CPM energy units; exploratory, not physiological
                    '_expert_level': 'advanced',
                    '_hidden_basic': True,
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 2.0},
                    '_cbo_term': 'cbo:VolumeEnergy',
                    '_model_context': 'Parameter λv (Eq. 22) for VolumeConstraint Hamiltonian term and Pressure calculation (Eq. 6).',
                    '_conceptual_hint': 'λv is the volume-constraint stiffness — how hard a cell resists deviating from its target area. High λv gives rigid, size-locked cells; low λv gives squishy, deformable ones. λv also feeds the effective pressure that drives density-dependent growth inhibition, so it indirectly couples mechanics to proliferation. Arbitrary CPM energy units — tune by behavior, not by measurement.',
                    '_implementation_pattern': 'Applied as `cell.lambdaVolume = self.InitBASAL_LambdaVolume` in `ConstraintInitializerSteppable.start()`; weights the VolumeConstraint energy for basal cells. From `Parameters.py`.',
                    '_related_parameters': ['InitBASAL_TargetVolume'],
                },
                'InitBASAL_TargetVolume': {
                    '_default': 25.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Basal Target Volume',
                    '_description': 'Ideal volume (area in 2D) each basal cell tries to maintain.',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Basal Cells',
                    '_unit': 'µm²',
                    '_dimension': 'area',
                    '_physiological_range': (15, 40),  # SIM units (voxel^2); displays in µm²
                    '_expert_level': 'intermediate',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 25.0},
                    '_cbo_term': 'cbo:Volume',
                    '_model_context': 'Parameter V_target (Eq. 22, 8) for VolumeConstraint and Growth. Represents TargetVolume state variable.',
                    '_conceptual_hint': 'Target volume and the volume coefficient λv together set how strongly a cell holds its size. Raising it makes cells larger (fewer per layer → thicker, fewer-celled epithelium); lowering it packs more, smaller cells. Because mitosis triggers at 2× the initial volume, target volume also paces division. Keep it within the 10–30 µm cell-diameter envelope or emergent thickness and turnover drift from the calibrated targets.',
                    '_implementation_pattern': 'Applied per cell in `ConstraintInitializerSteppable.start()` as `cell.targetVolume = self.InitBASAL_TargetVolume` for each basal cell; the CPM VolumeConstraint plugin then relaxes the cell toward this area each MCS. Stored in `Parameters.py` (pixels) and imported via `from Parameters import *`.',
                    '_literature': [85],  # paper ref numbers -> references.py
                    '_related_parameters': ['InitBASAL_LambdaVolume', 'GrowthControl'],
                },
                'InitBASAL_LambdaChemo': {
                    '_default': 1000.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Basal Movement Bias Chemotaxis Strength',
                    '_description': 'Strength of basal cell directed movement towards the Movement Bias chemical gradient.',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Basal Cells',
                    '_unit': 'Arbitrary Energy Units',
                    '_dimension': 'energy',
                    '_recommended_range': (100.0, 5000.0),  # arbitrary CPM energy units; exploratory, not physiological
                    '_expert_level': 'advanced',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 1000.0},
                    '_cbo_term': 'cbo:Chemotaxis',
                    '_model_context': 'Parameter λc (Eq. 24) for Chemotaxis_MBias Hamiltonian term influencing Movement.',
                    '_conceptual_hint': 'λc sets how strongly the cell biases its movement up the Movement-Bias chemoattractant gradient (limbus → periphery). Basal λc (1000) is an order of magnitude above stem (100), which drives centripetal migration of progeny away from the limbal niche while stem cells stay put. Arbitrary CPM energy units.',
                    '_implementation_pattern': 'Sets the chemotaxis weight (lambda_c) for basal cells toward the Movement-Bias field (Chemotaxis plugin). From `Parameters.py`.',
                    '_related_parameters': ['MovementBiasScreteAmount', 'MovementBiasUptake'],
                },
                'DensityBASAL_HalfMaxValue': {
                    '_default': 125,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Basal Density Growth Inhibition (Km)',
                    '_description': 'Cell pressure (related to density) at which basal cell growth rate is halved.',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Basal Cells',
                    '_unit': 'Arbitrary Pressure Units',
                    '_dimension': 'pressure',
                    '_recommended_range': (50, 300),  # arbitrary CPM pressure units; exploratory, not physiological
                    '_expert_level': 'intermediate',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 125},
                    '_cbo_term': 'cbo:CellGrowth',
                    '_model_context': 'Parameter Km_density (Eq. 4) affecting Growth behavior sensitivity to crowding.',
                    '_related_parameters': ['InitBASAL_LambdaVolume', 'InitBASAL_TargetVolume', 'GrowthControl'],
                    '_conceptual_hint': 'Half-max pressure for basal contact inhibition (inverse n=4 Hill); same fitted value (125) as stem. Sets how crowded basal cells get before proliferation shuts off, capping peripheral epithelial density.',
                    '_implementation_pattern': 'Consumed by `GrowthSteppable` in the density-inhibition Hill term (Eq. 2) for basal cells. From `Parameters.py`.',
                    '_literature': [89],  # paper ref numbers -> references.py
                },
                'EGF_BASAL_HalfMaxValue': {
                    '_default': 7.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Basal EGF Growth Sensitivity (Km)',
                    '_description': 'EGF concentration at which basal cell growth rate is halved.',
                    '_category': 'Growth Factors',
                    '_subcategory': 'EGF Response',
                    '_unit': 'Normalized Concentration',
                    '_dimension': 'concentration',
                    '_recommended_range': (3.0, 15.0),  # normalized/arbitrary concentration; exploratory, not physiological
                    '_expert_level': 'basic',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 7.0},
                    '_cbo_term': 'cbo:CellGrowth',
                    '_model_context': 'Parameter Km_EGF (Eq. 1) affecting Growth behavior sensitivity to EGF.',
                    '_related_parameters': [
                        'EGF_ScreteAmount', 'EGF_GlobalDecay', 'GrowthControl' # Simplified
                    ],
                    '_conceptual_hint': 'Half-max EGF for basal-cell growth (n=4 Hill). At 7.0 it is above the stem value (3.5), so peripheral basal cells need more EGF to proliferate — they ramp up mainly during wound healing, when a breached superficial barrier lets EGF flood in. Fitted (S1 Text §S1.5).',
                    '_implementation_pattern': 'Consumed by `GrowthSteppable` in the EGF-dependent Hill growth term (Eq. 1) for basal cells. From `Parameters.py`.',
                    '_literature': [88],  # paper ref numbers -> references.py
                },
                'BASAL_beta_EGF': {
                    '_default': 1,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Basal EGF Dependence Factor',
                    '_description': 'Factor β scaling the influence of EGF on basal cell growth rate (0=none, 1=full). Source steppable line 570-572 computes G_EGF = β·Hill(EGF) + (1-β).',
                    '_category': 'Growth Factors',
                    '_subcategory': 'EGF Response',
                    '_unit': 'dimensionless',
                    '_dimension': 'dimensionless',
                    '_recommended_range': (0.0, 1.0),  # exploratory range (dimensionless)
                    '_expert_level': 'intermediate',
                    '_reference_paper': {'source': 'Vanin et al., 2025 (S1 Text Eq. S7)', 'value': 1.0, 'detail': 'Implicit β parameter for Hill function combining EGF dependence with baseline (paper sets β=1 → fully EGF-dependent).'},
                    '_cbo_term': 'cbo:CellGrowth',
                    '_model_context': 'Modulates the impact of G_EGF term in Growth behavior (Eq. 1, S1 Text S1.1).',
                    '_related_parameters': ['EGF_BASAL_HalfMaxValue', 'GrowthControl'],
                    '_conceptual_hint': 'Same β blend for basal cells: at 1 (paper) basal growth is fully EGF-gated. Lowering it lets basal cells grow without EGF, useful for testing the barrier hypothesis.',
                    '_implementation_pattern': 'Read by `GrowthSteppable`; the beta factor blends EGF-dependence with a baseline in the basal growth term. From `Parameters.py`.',
                    '_literature': [88],  # paper ref numbers -> references.py
                },

                # --- WING Cell Parameters ---
                'InitWING_LambdaSurface': {
                    '_default': 5.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Wing Surface Coefficient',
                    '_description': 'Penalty factor for wing cell deviation from target surface area.',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Wing Cells',
                    '_unit': 'Arbitrary Energy Units',
                    '_dimension': 'energy',
                    '_recommended_range': (1.0, 20.0),  # arbitrary CPM energy units; exploratory, not physiological
                    '_expert_level': 'advanced',
                    '_hidden_basic': True,
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 5.0},
                    '_cbo_term': 'cbo:AreaEnergy',
                    '_model_context': 'Parameter λs (Eq. 23) for SurfaceConstraint Hamiltonian term.',
                    '_conceptual_hint': 'λs is the surface-constraint stiffness — how strongly a cell holds its target perimeter. Higher λs gives rounder, more regular, stiffer cells; set too high it suppresses the membrane fluctuations the Monte-Carlo dynamics need to move at all. Arbitrary CPM energy units.',
                    '_implementation_pattern': 'Applied as `cell.lambdaSurface = self.InitWING_LambdaSurface` in `ConstraintInitializerSteppable.start()`; weights the SurfaceConstraint energy for wing cells. From `Parameters.py`.',
                    '_related_parameters': ['InitWING_TargetSurface'],
                },
                'InitWING_TargetSurface': {
                    '_default': 25,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Wing Target Surface Area',
                    '_description': 'Ideal surface area (perimeter in 2D) each wing cell tries to maintain.',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Wing Cells',
                    '_unit': 'µm',
                    '_dimension': 'length',
                    '_physiological_range': (15, 40),  # SIM units (voxel); displays in µm
                    '_expert_level': 'intermediate',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 25},
                    '_cbo_term': 'cbo:SurfaceArea',
                    '_model_context': 'Parameter S_target (Eq. 23) for SurfaceConstraint Hamiltonian term.',
                    '_conceptual_hint': "Target surface is the cell's preferred perimeter (a length in 2D); with the surface coefficient λs it regularizes cell shape. Higher targets permit more elongated or ruffled membranes; the constraint keeps cells compact. It shapes cells rather than sizing them — that is target volume's job.",
                    '_implementation_pattern': "Applied as `cell.targetSurface = self.InitWING_TargetSurface` in `ConstraintInitializerSteppable.start()`; the SurfaceConstraint plugin regularizes each wing cell's perimeter toward this value. From `Parameters.py`.",
                    '_literature': [85],  # paper ref numbers -> references.py
                    '_related_parameters': ['InitWING_LambdaSurface'],
                },
                'InitWING_LambdaVolume': {
                    '_default': 2.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Wing Volume Coefficient',
                    '_description': 'Penalty factor for wing cell deviation from target volume.',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Wing Cells',
                    '_unit': 'Arbitrary Energy Units',
                    '_dimension': 'energy',
                    '_recommended_range': (0.1, 10.0),  # arbitrary CPM energy units; exploratory, not physiological
                    '_expert_level': 'advanced',
                    '_hidden_basic': True,
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 2.0},
                    '_cbo_term': 'cbo:VolumeEnergy',
                    '_model_context': 'Parameter λv (Eq. 22) for VolumeConstraint Hamiltonian term.',
                    '_conceptual_hint': 'λv is the volume-constraint stiffness — how hard a cell resists deviating from its target area. High λv gives rigid, size-locked cells; low λv gives squishy, deformable ones. λv also feeds the effective pressure that drives density-dependent growth inhibition, so it indirectly couples mechanics to proliferation. Arbitrary CPM energy units — tune by behavior, not by measurement.',
                    '_implementation_pattern': 'Applied as `cell.lambdaVolume = self.InitWING_LambdaVolume` in `ConstraintInitializerSteppable.start()`; weights the VolumeConstraint energy for wing cells. From `Parameters.py`.',
                    '_related_parameters': ['InitWING_TargetVolume'],
                },
                'InitWING_TargetVolume': {
                    '_default': 25.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Wing Target Volume',
                    '_description': 'Ideal volume (area in 2D) each wing cell tries to maintain (fixed).',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Wing Cells',
                    '_unit': 'µm²',
                    '_dimension': 'area',
                    '_physiological_range': (15, 40),  # SIM units (voxel^2); displays in µm²
                    '_expert_level': 'intermediate',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 25.0},
                    '_cbo_term': 'cbo:Volume',
                    '_model_context': 'Parameter V_target (Eq. 22) for VolumeConstraint. Represents fixed TargetVolume state variable.',
                    '_conceptual_hint': 'Target volume and the volume coefficient λv together set how strongly a cell holds its size. Raising it makes cells larger (fewer per layer → thicker, fewer-celled epithelium); lowering it packs more, smaller cells. These cells do not divide, so target volume mainly sets packing density and layer thickness. Keep it within the 10–30 µm cell-diameter envelope or emergent thickness and turnover drift from the calibrated targets.',
                    '_implementation_pattern': 'Applied per cell in `ConstraintInitializerSteppable.start()` as `cell.targetVolume = self.InitWING_TargetVolume` for each wing cell; the CPM VolumeConstraint plugin then relaxes the cell toward this area each MCS. Stored in `Parameters.py` (pixels) and imported via `from Parameters import *`.',
                    '_literature': [85],  # paper ref numbers -> references.py
                    '_related_parameters': ['InitWING_LambdaVolume'],
                },
                'InitWING_EGFLambdaChemo': {
                    '_default': 20.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Wing EGF Chemotaxis Strength',
                    '_description': 'Strength of wing cell directed movement towards the EGF chemical gradient.',
                    '_category': 'Growth Factors',
                    '_subcategory': 'EGF Response',
                    '_unit': 'Arbitrary Energy Units',
                    '_dimension': 'energy',
                    '_recommended_range': (5.0, 100.0),  # arbitrary CPM energy units; exploratory, not physiological
                    '_expert_level': 'intermediate',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 20.0},
                    '_cbo_term': 'cbo:Chemotaxis',
                    '_model_context': 'Parameter λc (Eq. 24) for Chemotaxis_EGF_Wing Hamiltonian term influencing Movement.',
                    '_conceptual_hint': 'λc for wing cells biases movement up the EGF gradient (rather than the Movement-Bias field), contributing to the upward drift of maturing cells toward the surface and, after injury, toward EGF-rich wound regions. Arbitrary CPM energy units.',
                    '_implementation_pattern': 'Sets the chemotaxis weight (lambda_c) for wing cells toward the EGF field (Chemotaxis plugin). From `Parameters.py`.',
                    '_literature': [93],  # paper ref numbers -> references.py
                    '_related_parameters': ['EGF_ScreteAmount', 'EGF_GlobalDecay', 'EGF_SUPERDiffCoef'],
                },

                # --- SUPERFICIAL Cell Parameters ---
                'InitSUPER_LambdaSurface': {
                    '_default': 5.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Superficial Surface Coefficient',
                    '_description': 'Penalty factor for superficial cell deviation from target surface area.',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Superficial Cells',
                    '_unit': 'Arbitrary Energy Units',
                    '_dimension': 'energy',
                    '_recommended_range': (1.0, 20.0),  # arbitrary CPM energy units; exploratory, not physiological
                    '_expert_level': 'advanced',
                    '_hidden_basic': True,
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 5.0},
                    '_cbo_term': 'cbo:AreaEnergy',
                    '_model_context': 'Parameter λs (Eq. 23) for SurfaceConstraint Hamiltonian term.',
                    '_conceptual_hint': 'λs is the surface-constraint stiffness — how strongly a cell holds its target perimeter. Higher λs gives rounder, more regular, stiffer cells; set too high it suppresses the membrane fluctuations the Monte-Carlo dynamics need to move at all. Arbitrary CPM energy units.',
                    '_implementation_pattern': 'Applied as `cell.lambdaSurface = self.InitSUPER_LambdaSurface` in `ConstraintInitializerSteppable.start()`; weights the SurfaceConstraint energy for superficial cells. From `Parameters.py`.',
                    '_related_parameters': ['InitSUPER_TargetSurface'],
                },
                'InitSUPER_TargetSurface': {
                    '_default': 25.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Superficial Target Surface Area',
                    '_description': 'Ideal surface area (perimeter in 2D) each superficial cell tries to maintain.',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Superficial Cells',
                    '_unit': 'µm',
                    '_dimension': 'length',
                    '_physiological_range': (15, 40),  # SIM units (voxel); displays in µm
                    '_expert_level': 'intermediate',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 25.0},
                    '_cbo_term': 'cbo:SurfaceArea',
                    '_model_context': 'Parameter S_target (Eq. 23) for SurfaceConstraint Hamiltonian term.',
                    '_conceptual_hint': "Target surface is the cell's preferred perimeter (a length in 2D); with the surface coefficient λs it regularizes cell shape. Higher targets permit more elongated or ruffled membranes; the constraint keeps cells compact. It shapes cells rather than sizing them — that is target volume's job.",
                    '_implementation_pattern': "Applied as `cell.targetSurface = self.InitSUPER_TargetSurface` in `ConstraintInitializerSteppable.start()`; the SurfaceConstraint plugin regularizes each superficial cell's perimeter toward this value. From `Parameters.py`.",
                    '_literature': [85],  # paper ref numbers -> references.py
                    '_related_parameters': ['InitSUPER_LambdaSurface'],
                },
                'InitSUPER_LambdaVolume': {
                    '_default': 5.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Superficial Volume Coefficient',
                    '_description': 'Penalty factor for superficial cell deviation from target volume.',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Superficial Cells',
                    '_unit': 'Arbitrary Energy Units',
                    '_dimension': 'energy',
                    '_recommended_range': (1.0, 20.0),  # arbitrary CPM energy units; exploratory, not physiological
                    '_expert_level': 'advanced',
                    '_hidden_basic': True,
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 5.0},
                    '_cbo_term': 'cbo:VolumeEnergy',
                    '_model_context': 'Parameter λv (Eq. 22) for VolumeConstraint Hamiltonian term.',
                    '_conceptual_hint': 'λv is the volume-constraint stiffness — how hard a cell resists deviating from its target area. High λv gives rigid, size-locked cells; low λv gives squishy, deformable ones. λv also feeds the effective pressure that drives density-dependent growth inhibition, so it indirectly couples mechanics to proliferation. Arbitrary CPM energy units — tune by behavior, not by measurement.',
                    '_implementation_pattern': 'Applied as `cell.lambdaVolume = self.InitSUPER_LambdaVolume` in `ConstraintInitializerSteppable.start()`; weights the VolumeConstraint energy for superficial cells. From `Parameters.py`.',
                    '_related_parameters': ['InitSUPER_TargetVolume'],
                },
                'InitSUPER_TargetVolume': {
                    '_default': 25.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Superficial Target Volume',
                    '_description': 'Ideal volume (area in 2D) each superficial cell tries to maintain (fixed).',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Superficial Cells',
                    '_unit': 'µm²',
                    '_dimension': 'area',
                    '_physiological_range': (15, 40),  # SIM units (voxel^2); displays in µm²
                    '_expert_level': 'intermediate',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 25.0},
                    '_cbo_term': 'cbo:Volume',
                    '_model_context': 'Parameter V_target (Eq. 22) for VolumeConstraint. Represents fixed TargetVolume state variable.',
                    '_conceptual_hint': 'Target volume and the volume coefficient λv together set how strongly a cell holds its size. Raising it makes cells larger (fewer per layer → thicker, fewer-celled epithelium); lowering it packs more, smaller cells. These cells do not divide, so target volume mainly sets packing density and layer thickness. Keep it within the 10–30 µm cell-diameter envelope or emergent thickness and turnover drift from the calibrated targets.',
                    '_implementation_pattern': 'Applied per cell in `ConstraintInitializerSteppable.start()` as `cell.targetVolume = self.InitSUPER_TargetVolume` for each superficial cell; the CPM VolumeConstraint plugin then relaxes the cell toward this area each MCS. Stored in `Parameters.py` (pixels) and imported via `from Parameters import *`.',
                    '_literature': [85],  # paper ref numbers -> references.py
                    '_related_parameters': ['InitSUPER_LambdaVolume'],
                },

                # --- Movement Bias Field Parameters ---
                'MovementBiasScreteAmount': {
                    '_default': 1.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Movement Bias Secretion Rate',
                    '_description': 'Rate of Movement Bias chemoattractant secretion by the basement membrane.',
                    '_category': 'Tissue Mechanics',
                    '_subcategory': 'Movement Signals',
                    '_unit': 'Normalized Conc. / hour', # Rate
                    '_dimension': 'rate',
                    '_recommended_range': (0.1, 10.0),  # model-usable range in sim 1/MCS; proxy term, not strictly physiological
                    '_expert_level': 'intermediate',
                    '_reference_paper': {'source': 'Vanin et al., 2025 (S9 Table)', 'value': 1.0},
                    '_cbo_term': 'cbo:MoleculeCreation',
                    '_model_context': 'Source term (φ) for BASALMVBIAS field in ReactionDiffusion_MBias process.',
                    '_related_parameters': ['MovementBiasUptake', 'InitSTEM_LambdaChemo', 'InitBASAL_LambdaChemo'],
                    '_conceptual_hint': 'Constant secretion of the Movement-Bias chemoattractant by the basement membrane, setting the strength of the limbus→periphery guidance gradient (paper value 1.0, normalized). Stronger gradient = more directed centripetal/vertical migration.',
                    '_implementation_pattern': 'Constant secretion into the Movement-Bias (BASALMVBIAS) field by the basement membrane, establishing the guidance gradient. From `Parameters.py`.',
                },
                'MovementBiasUptake': {
                    '_default': 1.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Movement Bias Uptake Rate',
                    '_description': 'Rate at which basal and stem cells absorb the Movement Bias chemoattractant.',
                    '_category': 'Tissue Mechanics',
                    '_subcategory': 'Movement Signals',
                    '_unit': '1 / hour', # Rate
                    '_dimension': 'rate',
                    '_recommended_range': (0.1, 10.0),  # model-usable range in sim 1/MCS; proxy term, not strictly physiological
                    '_expert_level': 'advanced',
                    '_reference_paper': {'source': 'Vanin et al., 2025 (S9 Table)', 'value': 1.0},
                    '_cbo_term': 'cbo:MoleculeDeletion',
                    '_model_context': 'Sink term (μ) for BASALMVBIAS field in ReactionDiffusion_MBias process.',
                    '_related_parameters': ['MovementBiasScreteAmount', 'InitSTEM_LambdaChemo', 'InitBASAL_LambdaChemo'],
                    '_conceptual_hint': "Rate at which basal cells absorb the Movement-Bias chemoattractant, shaping how sharply the guidance gradient decays away from the membrane. Paired with the secretion term to set the gradient's reach.",
                    '_implementation_pattern': 'Basal-cell uptake from the Movement-Bias field, shaping how the guidance gradient decays. From `Parameters.py`.',
                },

                # --- EGF Field Parameters ---
                'EGF_ScreteAmount': {
                    '_default': 1.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'EGF Secretion Rate (Tear)',
                    '_description': 'Rate of EGF introduction from the tear film.',
                    '_category': 'Growth Factors',
                    '_subcategory': 'EGF Production',
                    '_unit': 'Normalized Conc. / hour',
                    '_dimension': 'rate',
                    '_recommended_range': (0.1, 10.0),  # model-usable range in sim 1/MCS; proxy term, not strictly physiological
                    '_expert_level': 'intermediate',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 1.0},
                    '_cbo_term': 'cbo:MoleculeCreation',
                    '_model_context': 'Source term (φ, Eq. 40) for EGF field in ReactionDiffusion_EGF process.',
                    '_related_parameters': ['EGF_GlobalDecay', 'EGF_SUPERDiffCoef'], # Simplified
                    '_conceptual_hint': "Constant EGF the tear film injects at the surface, normalized so the field peaks at 1.0. The tear is the model's sole EGF source; raising this lifts the whole gradient and the proliferative drive. A normalized/abstract source term.",
                    '_implementation_pattern': 'Constant EGF secreted into the EGF field by tear cells (Secretion plugin / field steppable). From `Parameters.py`.',
                    '_literature': [34, 35, 54, 66],  # paper ref numbers -> references.py
                },
                'EGF_FieldUptakeBASAL': { # Currently unused in model (set to 0)
                    '_default': 0.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Basal EGF Uptake Rate',
                    '_description': 'Rate at which basal cells consume EGF.',
                    '_category': 'Growth Factors',
                    '_subcategory': 'EGF Consumption',
                    '_unit': '1 / hour',
                    '_dimension': 'rate',
                    '_recommended_range': (0.0, 5.0),  # model-usable range in sim 1/MCS; proxy term, not strictly physiological
                    '_expert_level': 'advanced',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 0.0},
                    '_cbo_term': 'cbo:MoleculeDeletion',
                    '_model_context': 'Sink term (μ, Eq. 40) for EGF field (specific to BASAL cells).',
                    '_related_parameters': ['EGF_GlobalDecay'],
                    '_conceptual_hint': 'Per-cell EGF consumption rate for basal cells — set to 0 in the paper. Cellular uptake is folded into the inflated global decay instead. Raise it only to model an explicit per-cell-type EGF sink (and lower the global decay to compensate).',
                    '_implementation_pattern': 'Per-cell EGF uptake from the EGF field for basal cells; 0 in the paper (uptake is folded into the inflated global decay). From `Parameters.py`.',
                },
                # ... Similar updates for EGF_FieldUptakeSTEM, EGF_FieldUptakeSuper, EGF_FieldUptakeWing ...
                'EGF_FieldUptakeSTEM': {
                    '_default': 0.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Stem EGF Uptake Rate',
                    '_description': 'Rate at which stem cells consume EGF.',
                    '_category': 'Growth Factors',
                    '_subcategory': 'EGF Consumption',
                    '_unit': '1 / hour',
                    '_dimension': 'rate',
                    '_recommended_range': (0.0, 5.0),  # model-usable range in sim 1/MCS; proxy term, not strictly physiological
                    '_expert_level': 'advanced',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 0.0},
                    '_cbo_term': 'cbo:MoleculeDeletion',
                    '_model_context': 'Sink term (μ, Eq. 40) for EGF field (specific to STEM cells).',
                    '_related_parameters': ['EGF_GlobalDecay'],
                    '_conceptual_hint': 'Per-cell EGF consumption rate for stem cells — set to 0 in the paper. Cellular uptake is folded into the inflated global decay instead. Raise it only to model an explicit per-cell-type EGF sink (and lower the global decay to compensate).',
                    '_implementation_pattern': 'Per-cell EGF uptake from the EGF field for stem cells; 0 in the paper (uptake is folded into the inflated global decay). From `Parameters.py`.',
                },
                'EGF_FieldUptakeSuper': {
                    '_default': 0.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Superficial EGF Uptake Rate',
                    '_description': 'Rate at which superficial cells consume EGF.',
                    '_category': 'Growth Factors',
                    '_subcategory': 'EGF Consumption',
                    '_unit': '1 / hour',
                    '_dimension': 'rate',
                    '_recommended_range': (0.0, 5.0),  # model-usable range in sim 1/MCS; proxy term, not strictly physiological
                    '_expert_level': 'advanced',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 0.0},
                    '_cbo_term': 'cbo:MoleculeDeletion',
                    '_model_context': 'Sink term (μ, Eq. 40) for EGF field (specific to SUPER cells).',
                    '_related_parameters': ['EGF_GlobalDecay'],
                    '_conceptual_hint': 'Per-cell EGF consumption rate for super cells — set to 0 in the paper. Cellular uptake is folded into the inflated global decay instead. Raise it only to model an explicit per-cell-type EGF sink (and lower the global decay to compensate).',
                    '_implementation_pattern': 'Per-cell EGF uptake from the EGF field for super cells; 0 in the paper (uptake is folded into the inflated global decay). From `Parameters.py`.',
                },
                'EGF_FieldUptakeWing': {
                    '_default': 0.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Wing EGF Uptake Rate',
                    '_description': 'Rate at which wing cells consume EGF.',
                    '_category': 'Growth Factors',
                    '_subcategory': 'EGF Consumption',
                    '_unit': '1 / hour',
                    '_dimension': 'rate',
                    '_recommended_range': (0.0, 5.0),  # model-usable range in sim 1/MCS; proxy term, not strictly physiological
                    '_expert_level': 'advanced',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 0.0},
                    '_cbo_term': 'cbo:MoleculeDeletion',
                    '_model_context': 'Sink term (μ, Eq. 40) for EGF field (specific to WING cells).',
                    '_related_parameters': ['EGF_GlobalDecay'],
                    '_conceptual_hint': 'Per-cell EGF consumption rate for wing cells — set to 0 in the paper. Cellular uptake is folded into the inflated global decay instead. Raise it only to model an explicit per-cell-type EGF sink (and lower the global decay to compensate).',
                    '_implementation_pattern': 'Per-cell EGF uptake from the EGF field for wing cells; 0 in the paper (uptake is folded into the inflated global decay). From `Parameters.py`.',
                },
                'EGF_GlobalDecay': {
                    '_default': 0.5,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'EGF Global Decay Rate',
                    '_description': 'Overall rate at which EGF naturally breaks down or is removed.',
                    '_category': 'Growth Factors',
                    '_subcategory': 'EGF Dynamics',
                    '_unit': '1 / hour',
                    '_dimension': 'rate',
                    '_recommended_range': (0.1, 2.0),  # model-usable range in sim 1/MCS; proxy term, not strictly physiological
                    '_expert_level': 'intermediate',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 0.5},
                    '_cbo_term': 'cbo:MoleculeDeletion',
                    '_model_context': 'Decay term (k_dEGF, Eq. 38) for EGF field in ReactionDiffusion_EGF process.',
                    '_related_parameters': ['EGF_ScreteAmount', 'EGF_SUPERDiffCoef'], # Simplified
                    '_conceptual_hint': 'Rate at which EGF disappears everywhere (0.5/MCS ≈ 5/hour) — deliberately ~5–10× the physiological clearance (half-life 42–114 min). The inflation lumps in unmodeled uptake, receptor endocytosis and ECM sequestration, and sets the EGF gradient length scale. A proxy rate, not a measured one.',
                    '_implementation_pattern': "`ConstraintInitializerSteppable.start()` runs `get_xml_element('EGF_GlobalDecay').cdata = self.EGF_GlobalDecay`, overriding the EGF field's XML GlobalDecayConstant. From `Parameters.py`.",
                    '_literature': [94],  # paper ref numbers -> references.py
                },
                'EGF_SUPERDiffCoef': {
                    '_default': 20.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'EGF Diffusion Rate (Superficial)',
                    '_description': 'Diffusion coefficient for the EGF field in the superficial layer.',
                    '_category': 'Growth Factors',
                    '_subcategory': 'EGF Dynamics',
                    '_unit': 'µm²/min',  # display label; conversion via utils/units.py keyed on _dimension
                    '_dimension': 'diffusion',
                    '_physiological_range': (0, 186),  # SIM units voxel^2/MCS: [0, EGF field global diffusion = 186]; displays as [0, 124] µm²/min
                    '_expert_level': 'intermediate',
                    '_reference_paper': {'source': 'Vanin et al., 2025 (S9 Table; refs Savage & Cohen 1973, Van Itallie 2008)', 'value': 20.0, 'detail': 'Higher than baseline EGF diffusion to reflect superficial tight-junction permeability for EGF in healthy cornea (Savage & Cohen 1973 + Van Itallie 2008).'},
                    '_cbo_term': 'cbo:MoleculeDiffusion',
                    '_model_context': 'Diffusion coefficient D_EGF,super for superficial layer in ReactionDiffusion_EGF (Eq. 10). Steppable line 261 overwrites XML default with this value at start().',
                    '_conceptual_hint': 'How fast EGF diffuses through superficial cells (20 voxel²/MCS ≈ 13 µm²/min) — about 9× slower than the global rate (186). This contrast IS the barrier: intact superficial cells throttle EGF reaching basal/stem layers, so proliferation stays low until injury breaches them. From tight-junction permeability data.',
                    '_implementation_pattern': "The EGF field's per-region diffusion is defined in CC3DML and overwritten at runtime: `ConstraintInitializerSteppable.start()` runs `get_xml_element('EGF_Coef_SUPER').cdata = self.EGF_SUPERDiffCoef`, so the `Parameters.py` value (voxel^2/MCS) wins over the XML default.",
                    '_literature': [93, 50],  # paper ref numbers -> references.py
                },

                # --- Link Parameters (SUPER-WALL) ---
                'LINKWALL_lambda_distance': {
                    '_default': 50,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Superficial-Wall Link Stiffness',
                    '_description': 'Stiffness of the connection between superficial cells and the boundary.',
                    '_category': 'Tissue Mechanics',
                    '_subcategory': 'Boundary Interactions',
                    '_unit': 'Arbitrary Energy Units', # Energy/Length^2 -> related to N/m or pN/um
                    '_dimension': 'energy',
                    '_recommended_range': (10, 200),  # arbitrary CPM energy units; exploratory, not physiological
                    '_expert_level': 'advanced',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 50},
                    '_cbo_term': 'cbo:StiffnessMechanical', # Represents stiffness
                    '_model_context': 'Stiffness parameter (λ, Eq. 17) for FPP links between SUPER and WALL cells.',
                    '_related_parameters': ['LINKWALL_max_distance'],
                    '_conceptual_hint': 'Spring stiffness (λ) of the focal-point link between superficial cells and the simulation boundary. Higher λ holds the target spacing more rigidly, enforcing the constant-tension apical sheet. Arbitrary CPM energy units.',
                    '_implementation_pattern': 'Passed to `new_fpp_link(cell, wall_neighbor, self.LINKWALL_lambda_distance, ...)` in the link steppable — spring constant for superficial<->boundary FPP links. From `Parameters.py`.',
                },
                'LINKWALL_max_distance': {
                    '_default': 1000,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Superficial-Wall Link Max Interaction Range',
                    '_description': 'Maximum distance over which the Superficial-Wall link force applies.',
                    '_category': 'Tissue Mechanics',
                    '_subcategory': 'Boundary Interactions',
                    '_unit': 'µm',
                    '_dimension': 'length',
                    '_physiological_range': (100, 2000),  # SIM units (voxel); displays in µm
                    '_expert_level': 'advanced',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 1000},
                    '_cbo_term': 'cbo:AdhesionEnergy',
                    '_model_context': 'Maximum interaction distance for FPP links between SUPER and WALL cells.',
                    '_related_parameters': ['LINKWALL_lambda_distance'],
                    '_conceptual_hint': 'Maximum stretch before the superficial–boundary link breaks (voxels; shown in µm). At 1000 it effectively never snaps; lowering it lets the sheet detach from the boundary under strain.',
                    '_implementation_pattern': 'Break-length (max distance) argument to `new_fpp_link(...)` for superficial<->boundary links. From `Parameters.py`.',
                },

                # --- Link Parameters (SUPER-SUPER) ---
                'LINKSUPER_lambda_distance': {
                    '_default': 50,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Superficial-Superficial Link Stiffness',
                    '_description': 'Stiffness of the connection between adjacent superficial cells.',
                    '_category': 'Tissue Mechanics',
                    '_subcategory': 'Cell Adhesion',
                    '_unit': 'Arbitrary Energy Units',
                    '_dimension': 'energy',
                    '_recommended_range': (10, 200),  # arbitrary CPM energy units; exploratory, not physiological
                    '_expert_level': 'intermediate',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 50},
                    '_cbo_term': 'cbo:StiffnessMechanical',
                    '_model_context': 'Stiffness parameter (λ, Eq. 17) for FPP links between SUPER cells.',
                    '_related_parameters': ['LINKSUPER_target_distance', 'LINKSUPER_max_distance', 'AutoAdjustLinks', 'Tension_link_SS'],
                    '_conceptual_hint': 'Spring stiffness (λ) of the link between two superficial cells. Higher λ knits the apical layer into a stiffer, more cohesive sheet. Arbitrary CPM energy units.',
                    '_implementation_pattern': 'Passed to `new_fpp_link(cell, neighbor, self.LINKSUPER_lambda_distance, ...)` — spring constant for superficial<->superficial FPP links. From `Parameters.py`.',
                },
                'LINKSUPER_target_distance': {
                    '_default': 3,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Superficial-Superficial Link Target Length',
                    '_description': 'Ideal resting length of the connection between superficial cells.',
                    '_category': 'Tissue Mechanics',
                    '_subcategory': 'Cell Adhesion',
                    '_unit': 'µm',
                    '_dimension': 'length',
                    '_physiological_range': (1, 10),  # SIM units (voxel); displays in µm
                    '_expert_level': 'intermediate',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 3},
                    '_cbo_term': 'cbo:AdhesionEnergy',
                    '_model_context': 'Target length parameter (d_target, Eq. 17) for FPP links between SUPER cells.',
                    '_related_parameters': ['LINKSUPER_lambda_distance', 'LINKSUPER_max_distance', 'AutoAdjustLinks', 'Tension_link_SS'],
                    '_conceptual_hint': 'Resting length of the spring between two superficial cells (voxels; shown in µm). The link pulls neighbors toward this spacing, forming a continuous apical sheet.',
                    '_implementation_pattern': 'Rest-length argument to `new_fpp_link(...)` for superficial<->superficial links. From `Parameters.py`.',
                },
                'LINKSUPER_max_distance': {
                    '_default': 1000,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Superficial-Superficial Link Max Interaction Range',
                    '_description': 'Maximum distance over which the Superficial-Superficial link force applies.',
                    '_category': 'Tissue Mechanics',
                    '_subcategory': 'Cell Adhesion',
                    '_unit': 'µm',
                    '_dimension': 'length',
                    '_physiological_range': (100, 2000),  # SIM units (voxel); displays in µm
                    '_expert_level': 'advanced',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 1000},
                    '_cbo_term': 'cbo:AdhesionEnergy',
                    '_model_context': 'Maximum interaction distance for FPP links between SUPER cells.',
                    '_related_parameters': ['LINKSUPER_lambda_distance', 'LINKSUPER_target_distance', 'AutoAdjustLinks'],
                    '_conceptual_hint': 'Maximum stretch before a superficial–superficial link breaks (voxels; shown in µm). At 1000 it effectively never snaps; lowering it lets the apical sheet tear apart under strain.',
                    '_implementation_pattern': 'Break-length (max distance) argument to `new_fpp_link(...)` for superficial<->superficial links. From `Parameters.py`.',
                },
                'AutoAdjustLinks': {
                    '_default': True,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Enable Dynamic Link Tension',
                    '_description': 'Automatically adjust link properties (stiffness or target length) to maintain constant tension between superficial cells.',
                    '_category': 'Tissue Mechanics',
                    '_subcategory': 'Adaptive Behavior',
                    '_unit': 'boolean',
                    '_expert_level': 'intermediate',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': True},
                    '_cbo_term': 'cbo:CellCellAdhesion',
                    '_model_context': 'Enables dynamic adjustment mechanism (Eq. 19-21) for SUPER-SUPER links.',
                    '_related_parameters': ['LINKSUPER_lambda_distance', 'LINKSUPER_target_distance'],
                    '_conceptual_hint': "When on, link properties auto-tune to hold constant tension on the superficial layer (the paper's mode). Off uses fixed link parameters.",
                    '_implementation_pattern': 'Boolean flag read class-level and checked by the relevant steppable to enable/disable auto-tuning of superficial-layer link tension. From `Parameters.py`.',
                },

                # --- Injury Parameters ---
                'IsInjury': {
                    '_default': True,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Enable Injury Simulation',
                    '_description': 'Whether to simulate an injury event during the run.',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Basic Setup',
                    '_unit': 'boolean',
                    '_expert_level': 'basic',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': True},
                    '_cbo_term': 'cbo:SystemQualities',
                    '_model_context': 'Globally enables/disables the injury event.',
                    '_affects_output': ['healing_time', 'cell_recovery_pattern'],
                    '_conceptual_hint': 'Master switch for the injury event. Off = pure homeostasis; on applies the chosen InjuryType at InjuryTime.',
                    '_implementation_pattern': 'Boolean flag read class-level and checked by the relevant steppable to enable/disable the injury event. From `Parameters.py`.',
                },
                'InjuryType': {
                    '_default': False,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Injury Type',
                    '_description': 'Selects the type of injury: Chemical Exposure or Mechanical Ablation.',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Basic Setup',
                    '_unit': 'categorical',
                    '_expert_level': 'basic',
                    '_value_mapping': {True: 'Mechanical Ablation', False: 'Chemical Exposure'},
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': False}, # Table S8.4 is True, param_defaults is False. Assuming Chemical=False is default intent. NEEDS VERIFICATION.
                    '_cbo_term': 'cbo:SystemQualities',
                    '_model_context': 'Selects injury mode.',
                    '_depends_on': ['IsInjury'],
                    '_conditional_display': lambda params: params.get('IsInjury', False),
                    '_conceptual_hint': 'Selects the injury mode: chemical exposure vs mechanical ablation (the two implemented pathways). Gates which injury parameters apply.',
                    '_implementation_pattern': 'Categorical flag read by the injury steppable selecting chemical exposure vs mechanical ablation. From `Parameters.py`.',
                },
                'InjuryTime': {
                    '_default': 3.0,  # 3 days pre-injury relaxation before applying the insult
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Injury Time (in Days)',
                    '_description': 'Time point during simulation when injury occurs. CC3D engine receives this value converted to MCS (1 day = 240 MCS).',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Timing',
                    '_unit': 'days',
                    '_conversion_factor': MCS_TO_DAYS, # days / MCS
                    '_physiological_range': (0.5, 30),
                    '_expert_level': 'intermediate',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 3.0},
                    '_cbo_term': 'cbo:TemporalInstant',
                    '_model_context': 'Specifies t_injury (used in Eq. 29, 32, 33 triggers). A 3-day relaxation period is recommended to let the tissue reach homeostasis before perturbation.',
                    '_depends_on': ['IsInjury'],
                    '_conceptual_hint': 'Simulation time at which the injury is applied (days, converted to MCS). Allow ≥3 days so the epithelium first relaxes to homeostasis; injuring earlier hits unequilibrated tissue and confounds the recovery readout.',
                    '_implementation_pattern': 'Read by the injury steppable; the injury (ablation or SLS seeding) is applied at this MCS. Stored in `Parameters.py` (converted from days).',
                },

                # --- Ablation Injury Parameters ---
                'InjuryX_Center': {
                    '_default': 150,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Ablation Center X',
                    '_description': 'X-coordinate of the ablation injury center.',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Mechanical Injury',
                    '_unit': 'µm',
                    '_dimension': 'length',
                    '_physiological_range': (0, 200),  # SIM units (voxel); displays in µm
                    '_expert_level': 'intermediate',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 150},
                    '_cbo_term': 'cbo:Location',
                    '_model_context': 'Sets x_center_abla (Eq. 29).',
                    '_depends_on': ['IsInjury'],
                    '_conditional_display': lambda params: params.get('IsInjury', False) and params.get('InjuryType', False), # True = Ablation
                    '_conceptual_hint': "X lattice position of the ablation center (voxels; shown in µm). Fixed to the paper's location — vary the radius for different scenarios rather than moving the site. Domain is 200×90 voxels (400×180 µm).",
                    '_implementation_pattern': 'Read by the injury steppable; the x-coordinate of the ablation center used at InjuryTime. From `Parameters.py`.',
                },
                'InjuryY_Center': {
                    '_default': 60,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Ablation Center Y',
                    '_description': 'Y-coordinate of the ablation injury center.',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Mechanical Injury',
                    '_unit': 'µm',
                    '_dimension': 'length',
                    '_physiological_range': (0, 90),  # SIM units (voxel); displays in µm
                    '_expert_level': 'intermediate',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 60},
                    '_cbo_term': 'cbo:Location',
                    '_model_context': 'Sets y_center_abla (Eq. 29).',
                    '_depends_on': ['IsInjury'],
                    '_conditional_display': lambda params: params.get('IsInjury', False) and params.get('InjuryType', False), # True = Ablation
                    '_conceptual_hint': "Y lattice position of the ablation center (voxels; shown in µm). Fixed to the paper's location across severities.",
                    '_implementation_pattern': 'Read by the injury steppable; the y-coordinate of the ablation center used at InjuryTime. From `Parameters.py`.',
                },
                'InjuryRadius': {
                    '_default': 25,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Ablation Radius',
                    '_description': 'Radius of the circular ablation injury area.',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Mechanical Injury',
                    '_unit': 'µm',
                    '_dimension': 'length',
                    '_physiological_range': (1, 90),  # SIM units (voxel); displays in µm
                    '_expert_level': 'basic',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 25},
                    '_cbo_term': 'cbo:ExtentGeometrical',
                    '_model_context': 'Sets r_abla (Eq. 29).',
                    '_depends_on': ['IsInjury'],
                    '_conditional_display': lambda params: params.get('IsInjury', False) and params.get('InjuryType', False), # True = Ablation
                    '_conceptual_hint': 'Radius of the circular ablation (voxels; shown in µm) — every cell touching the circle is removed and replaced by tear. The main severity knob for mechanical injury; wide range because injury extent is scenario-dependent.',
                    '_implementation_pattern': 'Read by the injury steppable; at InjuryTime, cells within this radius of (InjuryX_Center, InjuryY_Center) are converted to tear (ablation). From `Parameters.py`.',
                },

                # --- Chemical Injury Parameters ---
                'SLS_Injury': {
                    '_default': True,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Enable SLS Injury Field',
                    '_description': 'Master toggle for SLS-based chemical injury. Also gates the conditional display of SLS_Threshold, SLS_Concentration, SLS_X/Y_Center, SLS_Gaussian_pulse, and per-cell-type SLS diffusion coefficients in the GUI.',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Chemical Injury',
                    '_unit': 'boolean',
                    '_expert_level': 'intermediate',
                    '_reference_paper': {'source': 'Vanin et al., 2025 (S11 Table)', 'value': False, 'detail': 'Paper supp default is False (baseline homeostasis runs); schema default True since the GUI surface assumes injury workflows.'},
                    '_model_context': 'Controls activation of the SLS injury field (ReactionDiffusion_Chemical). When False, the steppable skips the chemical-injury branch (vCornea_v2Steppables.py:742).',
                    '_depends_on': ['IsInjury', 'InjuryType'],
                    '_conditional_display': lambda params: params.get('IsInjury', False) and not params.get('InjuryType', False),
                    '_conceptual_hint': 'Enables the SLS chemical-injury pathway specifically (vs ablation) — a testing/diagnostic flag for chemical spread and death.',
                    '_implementation_pattern': 'Boolean flag read class-level and checked by the relevant steppable to enable/disable the SLS chemical-injury pathway. From `Parameters.py`.',
                },
                'SLS_X_Center': {
                    '_default': 100,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Chemical Exposure Center X',
                    '_description': 'X-coordinate for the center of initial chemical application.',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Chemical Injury',
                    '_unit': 'µm',
                    '_dimension': 'length',
                    '_physiological_range': (0, 200),  # SIM units (voxel); displays in µm
                    '_expert_level': 'intermediate',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 100},
                    '_cbo_term': 'cbo:Location',
                    '_model_context': 'Sets x_center_chem (Eq. 32/33).',
                    '_depends_on': ['IsInjury', 'InjuryType'],
                    '_conditional_display': lambda params: params.get('IsInjury', False) and not params.get('InjuryType', False), # False = Chemical
                    '_conceptual_hint': "X position of the chemical-injury source (voxels; shown in µm); the Gaussian pulse or uniform coating is centered here. Fixed to the paper's location across severity scenarios.",
                    '_implementation_pattern': 'Read by the injury steppable; x-coordinate of the SLS chemical source seeded into the SLS field. From `Parameters.py`.',
                },
                'SLS_Y_Center': {
                    '_default': 75,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Chemical Exposure Center Y',
                    '_description': 'Y-coordinate for the center of initial chemical application.',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Chemical Injury',
                    '_unit': 'µm',
                    '_dimension': 'length',
                    '_physiological_range': (0, 90),  # SIM units (voxel); displays in µm
                    '_expert_level': 'intermediate',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 75},
                    '_cbo_term': 'cbo:Location',
                    '_model_context': 'Sets y_center_chem (Eq. 32/33).',
                    '_depends_on': ['IsInjury', 'InjuryType'],
                    '_conditional_display': lambda params: params.get('IsInjury', False) and not params.get('InjuryType', False), # False = Chemical
                    '_conceptual_hint': "Y position of the chemical-injury source (voxels; shown in µm). Fixed to the paper's location.",
                    '_implementation_pattern': 'Read by the injury steppable; y-coordinate of the SLS chemical source. From `Parameters.py`.',
                },
                'SLS_Concentration': {
                    '_default': 750.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Initial Chemical Concentration',
                    '_description': 'Initial concentration of the applied SLS chemical insult. Paper S10 defines three depth-of-injury presets (Scott et al. 2010): slight=750, mild=1500, moderate=2500.',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Chemical Injury',
                    '_unit': 'Arbitrary Units', # a.u.
                    '_dimension': 'concentration',
                    '_recommended_range': (100.0, 5000.0),  # normalized/arbitrary concentration; exploratory, not physiological
                    '_preset_values': {'slight': 750.0, 'mild': 1500.0, 'moderate': 2500.0},
                    '_expert_level': 'basic',
                    '_reference_paper': {'source': 'Vanin et al., 2025 (S10 Table; Scott et al. 2010 depth-of-injury classification)', 'value': 750.0},
                    '_cbo_term': 'cbo:ChemicalDensity',
                    '_model_context': 'Sets c0_chem (Eq. 32/33).',
                    '_depends_on': ['IsInjury', 'InjuryType'],
                    '_conditional_display': lambda params: params.get('IsInjury', False) and not params.get('InjuryType', False), # False = Chemical
                    '_conceptual_hint': 'Initial strength of the chemical insult, in arbitrary units mapped to injury DEPTH: 750 = slight (superficial only), 1500 = mild (full epithelium, BM intact), 2500 = moderate (destroys the BM → RCE-like instability). A depth-of-injury proxy, not a molar concentration.',
                    '_implementation_pattern': 'Initial value seeded into the SLS field at injury time by the injury steppable (Gaussian pulse or uniform coating). From `Parameters.py`.',
                    '_literature': [3],  # paper ref numbers -> references.py
                },
                'SLS_Gaussian_pulse': {
                    '_default': True, # Default set based on Table S8.4 (NEEDS VERIFICATION vs parameter_defaults.json)
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Chemical Distribution Pattern',
                    '_description': 'Pattern of initial chemical application: Gaussian Droplet or Uniform Coating.',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Chemical Injury',
                    '_unit': 'categorical',
                    '_expert_level': 'intermediate',
                    '_value_mapping': {True: 'Gaussian Droplet', False: 'Uniform Coating'},
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': True}, # Value from Table S8.4
                    '_cbo_term': 'cbo:ChemicalPattern',
                    '_model_context': 'Selects initial condition Eq. 32 (True) or Eq. 33 (False) for ReactionDiffusion_Chemical.',
                    '_depends_on': ['IsInjury', 'InjuryType'],
                    '_conditional_display': lambda params: params.get('IsInjury', False) and not params.get('InjuryType', False), # False = Chemical
                    '_conceptual_hint': 'Chooses the chemical initial condition: on = a localized Gaussian droplet at the source; off = a uniform coating across the surface.',
                    '_implementation_pattern': 'Boolean flag read class-level and checked by the relevant steppable to enable/disable the Gaussian-pulse vs uniform SLS initial condition. From `Parameters.py`.',
                },
                # ... Diffusion Coefficients SLS_*DiffCoef ...
                 'SLS_STEMDiffCoef': {
                    '_default': 5.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Chemical Diffusion Rate (Stem)',
                    '_description': 'Rate of chemical diffusion within stem cells.',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Chemical Diffusion',
                    '_unit': 'µm²/min',  # display label; conversion via utils/units.py keyed on _dimension
                    '_dimension': 'diffusion',
                    '_physiological_range': (0, 5.0),  # SIM units voxel^2/MCS: [0, SLS field global diffusion = 5.0]; displays as [0, 3.33] µm²/min
                    '_expert_level': 'advanced',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 5.0},
                    '_cbo_term': 'cbo:MoleculeDiffusion',
                    '_model_context': 'Diffusion coefficient D_chem (Eq. 31) in STEM cells.',
                    '_conceptual_hint': "How fast the injury chemical spreads within stem cells (5 voxel²/MCS, the field's global rate). All compartments share one value, so SLS diffuses uniformly; injury depth/severity is governed by concentration and exposure, not compartment-specific diffusion. A proxy field, not a specific molecule.",
                     '_implementation_pattern': "Imported from `Parameters.py` for the SLS field. (The per-region SLS diffusion overwritten at runtime in ConstraintInitializerSteppable covers SUPER/WING/BASAL/MEMB/LIMB/TEAR via `get_xml_element('SLS_Coef_*')`.)",
                    '_depends_on': ['IsInjury', 'InjuryType'],
                    '_conditional_display': lambda params: params.get('IsInjury', False) and not params.get('InjuryType', False),
                    '_related_parameters': ['SLS_BASALDiffCoef', 'SLS_WINGDiffCoef', 'SLS_SUPERDiffCoef', 'SLS_MEMBDiffCoef', 'SLS_LIMBDiffCoef', 'SLS_TEARDiffCoef'],
                },
                'SLS_BASALDiffCoef': {
                    '_default': 5.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Chemical Diffusion Rate (Basal)',
                    '_description': 'Rate of chemical diffusion within basal cells.',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Chemical Diffusion',
                    '_unit': 'µm²/min',  # display label; conversion via utils/units.py keyed on _dimension
                    '_dimension': 'diffusion',
                    '_physiological_range': (0, 5.0),  # SIM units voxel^2/MCS: [0, SLS field global diffusion = 5.0]; displays as [0, 3.33] µm²/min
                    '_expert_level': 'advanced',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 5.0},
                    '_cbo_term': 'cbo:MoleculeDiffusion',
                    '_model_context': 'Diffusion coefficient D_chem (Eq. 31) in BASAL cells.',
                    '_depends_on': ['IsInjury', 'InjuryType'],
                    '_conditional_display': lambda params: params.get('IsInjury', False) and not params.get('InjuryType', False),
                    '_related_parameters': ['SLS_STEMDiffCoef', 'SLS_WINGDiffCoef', 'SLS_SUPERDiffCoef', 'SLS_MEMBDiffCoef', 'SLS_LIMBDiffCoef', 'SLS_TEARDiffCoef'],
                    '_conceptual_hint': "How fast the injury chemical spreads within basal cells (5 voxel²/MCS, the field's global rate). All compartments share one value, so SLS diffuses uniformly; injury depth/severity is governed by concentration and exposure, not compartment-specific diffusion. A proxy field, not a specific molecule.",
                    '_implementation_pattern': "`ConstraintInitializerSteppable.start()` runs `get_xml_element('SLS_Coef_BASAL').cdata = self.SLS_BASALDiffCoef`, overriding the SLS field's XML diffusion constant for the BASAL region. From `Parameters.py`.",
                },
                'SLS_WINGDiffCoef': {
                    '_default': 5.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Chemical Diffusion Rate (Wing)',
                    '_description': 'Rate of chemical diffusion within wing cells.',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Chemical Diffusion',
                    '_unit': 'µm²/min',  # display label; conversion via utils/units.py keyed on _dimension
                    '_dimension': 'diffusion',
                    '_physiological_range': (0, 5.0),  # SIM units voxel^2/MCS: [0, SLS field global diffusion = 5.0]; displays as [0, 3.33] µm²/min
                    '_expert_level': 'advanced',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 5.0},
                    '_cbo_term': 'cbo:MoleculeDiffusion',
                    '_model_context': 'Diffusion coefficient D_chem (Eq. 31) in WING cells.',
                    '_depends_on': ['IsInjury', 'InjuryType'],
                    '_conditional_display': lambda params: params.get('IsInjury', False) and not params.get('InjuryType', False),
                    '_related_parameters': ['SLS_STEMDiffCoef', 'SLS_BASALDiffCoef', 'SLS_SUPERDiffCoef', 'SLS_MEMBDiffCoef', 'SLS_LIMBDiffCoef', 'SLS_TEARDiffCoef'],
                    '_conceptual_hint': "How fast the injury chemical spreads within wing cells (5 voxel²/MCS, the field's global rate). All compartments share one value, so SLS diffuses uniformly; injury depth/severity is governed by concentration and exposure, not compartment-specific diffusion. A proxy field, not a specific molecule.",
                    '_implementation_pattern': "`ConstraintInitializerSteppable.start()` runs `get_xml_element('SLS_Coef_WING').cdata = self.SLS_WINGDiffCoef`, overriding the SLS field's XML diffusion constant for the WING region. From `Parameters.py`.",
                },
                'SLS_SUPERDiffCoef': {
                    '_default': 5.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Chemical Diffusion Rate (Superficial)',
                    '_description': 'Rate of chemical diffusion within superficial cells.',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Chemical Diffusion',
                    '_unit': 'µm²/min',  # display label; conversion via utils/units.py keyed on _dimension
                    '_dimension': 'diffusion',
                    '_physiological_range': (0, 5.0),  # SIM units voxel^2/MCS: [0, SLS field global diffusion = 5.0]; displays as [0, 3.33] µm²/min
                    '_expert_level': 'advanced',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 5.0},
                    '_cbo_term': 'cbo:MoleculeDiffusion',
                    '_model_context': 'Diffusion coefficient D_chem (Eq. 31) in SUPER cells.',
                    '_depends_on': ['IsInjury', 'InjuryType'],
                    '_conditional_display': lambda params: params.get('IsInjury', False) and not params.get('InjuryType', False),
                    '_related_parameters': ['SLS_STEMDiffCoef', 'SLS_BASALDiffCoef', 'SLS_WINGDiffCoef', 'SLS_MEMBDiffCoef', 'SLS_LIMBDiffCoef', 'SLS_TEARDiffCoef'],
                    '_conceptual_hint': "How fast the injury chemical spreads within superficial cells (5 voxel²/MCS, the field's global rate). All compartments share one value, so SLS diffuses uniformly; injury depth/severity is governed by concentration and exposure, not compartment-specific diffusion. A proxy field, not a specific molecule.",
                    '_implementation_pattern': "`ConstraintInitializerSteppable.start()` runs `get_xml_element('SLS_Coef_SUPER').cdata = self.SLS_SUPERDiffCoef`, overriding the SLS field's XML diffusion constant for the SUPER region. From `Parameters.py`.",
                },
                'SLS_MEMBDiffCoef': {
                    '_default': 5.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Chemical Diffusion Rate (Peripheral BM)',
                    '_description': 'Rate of chemical diffusion within the peripheral basement membrane region.',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Chemical Diffusion',
                    '_unit': 'µm²/min',  # display label; conversion via utils/units.py keyed on _dimension
                    '_dimension': 'diffusion',
                    '_physiological_range': (0, 5.0),  # SIM units voxel^2/MCS: [0, SLS field global diffusion = 5.0]; displays as [0, 3.33] µm²/min
                    '_expert_level': 'advanced',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 5.0},
                    '_cbo_term': 'cbo:MoleculeDiffusion',
                    '_model_context': 'Diffusion coefficient D_chem (Eq. 31) in MEMB cells.',
                    '_depends_on': ['IsInjury', 'InjuryType'],
                    '_conditional_display': lambda params: params.get('IsInjury', False) and not params.get('InjuryType', False),
                    '_related_parameters': ['SLS_STEMDiffCoef', 'SLS_BASALDiffCoef', 'SLS_WINGDiffCoef', 'SLS_SUPERDiffCoef', 'SLS_LIMBDiffCoef', 'SLS_TEARDiffCoef'],
                    '_conceptual_hint': "How fast the injury chemical spreads within the peripheral EpBM (5 voxel²/MCS, the field's global rate). All compartments share one value, so SLS diffuses uniformly; injury depth/severity is governed by concentration and exposure, not compartment-specific diffusion. A proxy field, not a specific molecule.",
                    '_implementation_pattern': "`ConstraintInitializerSteppable.start()` runs `get_xml_element('SLS_Coef_MEMB').cdata = self.SLS_MEMBDiffCoef`, overriding the SLS field's XML diffusion constant for the MEMB region. From `Parameters.py`.",
                },
                'SLS_LIMBDiffCoef': {
                    '_default': 5.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Chemical Diffusion Rate (Limbal BM)',
                    '_description': 'Rate of chemical diffusion within the limbal basement membrane region.',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Chemical Diffusion',
                    '_unit': 'µm²/min',  # display label; conversion via utils/units.py keyed on _dimension
                    '_dimension': 'diffusion',
                    '_physiological_range': (0, 5.0),  # SIM units voxel^2/MCS: [0, SLS field global diffusion = 5.0]; displays as [0, 3.33] µm²/min
                    '_expert_level': 'advanced',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 5.0},
                    '_cbo_term': 'cbo:MoleculeDiffusion',
                    '_model_context': 'Diffusion coefficient D_chem (Eq. 31) in LIMB cells.',
                    '_depends_on': ['IsInjury', 'InjuryType'],
                    '_conditional_display': lambda params: params.get('IsInjury', False) and not params.get('InjuryType', False),
                    '_related_parameters': ['SLS_STEMDiffCoef', 'SLS_BASALDiffCoef', 'SLS_WINGDiffCoef', 'SLS_SUPERDiffCoef', 'SLS_MEMBDiffCoef', 'SLS_TEARDiffCoef'],
                    '_conceptual_hint': "How fast the injury chemical spreads within the limbal EpBM (5 voxel²/MCS, the field's global rate). All compartments share one value, so SLS diffuses uniformly; injury depth/severity is governed by concentration and exposure, not compartment-specific diffusion. A proxy field, not a specific molecule.",
                    '_implementation_pattern': "`ConstraintInitializerSteppable.start()` runs `get_xml_element('SLS_Coef_LIMB').cdata = self.SLS_LIMBDiffCoef`, overriding the SLS field's XML diffusion constant for the LIMB region. From `Parameters.py`.",
                },
                'SLS_TEARDiffCoef': {
                    '_default': 5.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Chemical Diffusion Rate (Tear)',
                    '_description': 'Rate of chemical diffusion within the tear film.',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Chemical Diffusion',
                    '_unit': 'µm²/min',  # display label; conversion via utils/units.py keyed on _dimension
                    '_dimension': 'diffusion',
                    '_physiological_range': (0, 5.0),  # SIM units voxel^2/MCS: [0, SLS field global diffusion = 5.0]; displays as [0, 3.33] µm²/min
                    '_expert_level': 'advanced',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 5.0},
                    '_cbo_term': 'cbo:MoleculeDiffusion',
                    '_model_context': 'Diffusion coefficient D_chem (Eq. 31) in TEAR cells.',
                    '_depends_on': ['IsInjury', 'InjuryType'],
                    '_conditional_display': lambda params: params.get('IsInjury', False) and not params.get('InjuryType', False),
                    '_related_parameters': ['SLS_STEMDiffCoef', 'SLS_BASALDiffCoef', 'SLS_WINGDiffCoef', 'SLS_SUPERDiffCoef', 'SLS_MEMBDiffCoef', 'SLS_LIMBDiffCoef'],
                    '_conceptual_hint': "How fast the injury chemical spreads within the tear film (5 voxel²/MCS, the field's global rate). All compartments share one value, so SLS diffuses uniformly; injury depth/severity is governed by concentration and exposure, not compartment-specific diffusion. A proxy field, not a specific molecule.",
                    '_implementation_pattern': "`ConstraintInitializerSteppable.start()` runs `get_xml_element('SLS_Coef_TEAR').cdata = self.SLS_TEARDiffCoef`, overriding the SLS field's XML diffusion constant for the TEAR region. From `Parameters.py`.",
                },
                'SLS_Threshold_Method': {
                    '_default': True,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Enable Chemical Death Threshold',
                    '_description': 'Use a concentration threshold to trigger chemical-induced cell death.',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Chemical Injury',
                    '_unit': 'boolean',
                    '_expert_level': 'intermediate',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': True},
                    '_cbo_term': 'cbo:Necrosis',
                    '_model_context': 'Enables the Death_Chemical behavior based on threshold (Eq. 36).',
                    '_depends_on': ['IsInjury', 'InjuryType'],
                    '_conditional_display': lambda params: params.get('IsInjury', False) and not params.get('InjuryType', False),
                    '_related_parameters': ['SLS_Threshold', 'DeathControl'],
                    '_conceptual_hint': 'When on, cells die by the concentration-threshold rule (mean SLS > SLS_Threshold) — the standard chemical-death mechanism.',
                    '_implementation_pattern': 'Boolean flag read class-level and checked by the relevant steppable to enable/disable concentration-threshold cell death. From `Parameters.py`.',
                },
                'SLS_Threshold': {
                    '_default': 2.0, # Assuming 2.0 based on previous schema and CBO.owl value
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Chemical Death Concentration Threshold',
                    '_description': 'Average intracellular chemical concentration above which cell death is triggered.',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Chemical Injury',
                    '_unit': 'Arbitrary Units', # a.u.
                    '_dimension': 'concentration',
                    '_recommended_range': (0.5, 10.0),  # normalized/arbitrary concentration; exploratory, not physiological
                    '_expert_level': 'intermediate',
                     # Table S8.4 has True, param_defaults has 2.0. Using 2.0. NEEDS VERIFICATION.
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 2.0},
                    '_cbo_term': 'cbo:Necrosis',
                    '_model_context': 'Sets threshold ω_chem (Eq. 36) for Death_Chemical behavior.',
                    '_depends_on': ['IsInjury', 'InjuryType', 'SLS_Threshold_Method'],
                    '_conditional_display': lambda params: params.get('IsInjury', False) and not params.get('InjuryType', False) and params.get('SLS_Threshold_Method', False),
                    '_related_parameters': ['SLS_Threshold_Method', 'DeathControl'],
                    '_conceptual_hint': "Mean internal chemical concentration above which a cell is marked for death (arbitrary units, on SLS_Concentration's scale). Lower = cells die at milder exposure (deeper apparent injury); higher = more tolerant. Sets where the dose–response cliff sits.",
                    '_implementation_pattern': 'Read by the chemical-death logic: a cell dies when its mean internal SLS exceeds this. From `Parameters.py`.',
                },

                # --- Simulation Duration ---
                # Defined before the Function Control / Biological Processes
                # block so the 'Duration' subcategory renders ABOVE
                # 'Biological Processes' in the Simulation Control tab
                # (subcategory ordering follows schema['inputs'] iteration order).
                # Value is in DAYS at this layer; the CC3D-bridge converts to MCS
                # (1 day = 240 MCS) via _to_cc3d_units() in _write_parameters_file
                # and _collect_output_files. Do not pre-multiply here.
                'SimTime': {
                    '_default': 30,  # 3 days relaxation + 27 days observation; generous default to let the system reach steady state rather than cutting off at the 24-day categorization minimum (paper replication = 183-day preset below)
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Simulation Duration (in Days)',
                    '_description': 'Total duration of the simulation run in days. The CC3D engine receives this value converted to Monte Carlo Steps (1 day = 240 MCS).',
                    '_category': 'Simulation Control',
                    '_subcategory': 'Duration',
                    '_unit': 'days',
                    '_conversion_factor': MCS_TO_DAYS, # days / MCS
                    '_physiological_range': (1, 200),  # 200 day ceiling allows the 183-day paper-replication run with headroom
                    '_expert_level': 'basic',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 183},
                    '_cbo_term': 'cbo:TemporalInterval',
                    '_model_context': 'Sets the total simulation time (t_final). Internally converted to MCS for the CC3D engine.',
                    '_presets': { # Presets in days
                        'Quick Test (1 week)': 7,
                        'Categorization (3 pre + 21 post)': 24,
                        'Paper Replication (3 pre + 180 post)': 183,
                    },
                    '_biological_meaning': 'Determines observation window. Paper used 180 days post-injury for late-stage outcome categorization; 24 days is the minimum to assess the standard categorization paradigm.',
                    '_conceptual_hint': "Total run length (days, converted to MCS). Default 30 days (3-day relaxation + ~4 weeks observation) covers the standard 3-pre + 21-post categorization window; use the 183-day preset to replicate the paper's long-horizon protocol. Longer is safer — let the system reach steady state rather than truncating.",
                    '_implementation_pattern': 'Total number of MCS the simulation runs. Stored in `Parameters.py` (converted from days at the GUI->Parameters.py boundary).',
                },

                'random_seed': {
                    '_default': -1,
                    '_updater': 'set',
                    '_emit': True,
                    '_scope': 'wrapper',
                    '_display_name': 'Random Seed',
                    '_description': 'Seed for the Monte Carlo random number generator. '
                                    'Leave at -1 to draw a seed automatically; the drawn '
                                    'value is recorded with the run either way.',
                    '_category': 'Simulation Control',
                    '_subcategory': 'Reproducibility',
                    '_unit': 'dimensionless',
                    '_dimension': 'dimensionless',
                    '_recommended_range': (-1, 2147483646),
                    '_expert_level': 'intermediate',
                    '_reference_paper': {'source': 'Not a model parameter; execution control.',
                                         'value': -1},
                    '_cbo_term': 'cbo:SystemQualities',
                    '_model_context': 'Written into the CC3DML <Potts><RandomSeed> element of '
                                      'the per-run project copy; the source project is unchanged.',
                    '_conceptual_hint': (
                        'The model is stochastic, so two runs with identical parameters '
                        'diverge unless they share a seed. Leave at -1 for normal use: a '
                        'fresh seed is drawn for every replicate and reported in the run '
                        'metadata, archive and PDF report, so a reader can always tell '
                        'whether a difference between two runs is stochastic or configured. '
                        'Set a specific value only to reproduce one particular realization.'),
                    '_implementation_pattern': (
                        'Resolved per replicate by `_resolve_run_seed` and injected into the '
                        'copied project by `_inject_random_seed_in_copy`; also written to the '
                        'archived `Parameters.py` for the record (CC3D reads it from the XML).'),
                    '_affects_output': ['trajectory_realization'],
                },

                # --- Function Control Parameters ---
                'GrowthControl': {
                    '_default': True,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Enable Cell Growth',
                    '_description': 'Allow stem and basal cells to increase target volume based on EGF and density.',
                    '_category': 'Simulation Control',
                    '_subcategory': 'Biological Processes',
                    '_unit': 'boolean',
                    '_expert_level': 'intermediate',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': True},
                    '_cbo_term': 'cbo:CellGrowth',
                    '_model_context': 'Master switch for the Growth behavior.',
                    '_debug_parameter': True,
                    '_conceptual_hint': 'Master switch for cell growth. Off freezes all volume growth — isolates mechanics/differentiation from proliferation. Normally on.',
                    '_implementation_pattern': 'Boolean flag read class-level and checked by the relevant steppable to enable/disable the growth method (`if self.GrowthControl:` in GrowthSteppable). From `Parameters.py`.',
                },
                'MitosisControl': {
                    '_default': True,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Enable Cell Division',
                    '_description': 'Allow stem and basal cells to divide when reaching volume threshold.',
                    '_category': 'Simulation Control',
                    '_subcategory': 'Biological Processes',
                    '_unit': 'boolean',
                    '_expert_level': 'intermediate',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': True},
                    '_cbo_term': 'cbo:Mitosis',
                    '_model_context': 'Master switch for Mitosis_Asymmetric_STEM and Mitosis_Symmetric_BASAL behaviors.',
                    '_debug_parameter': True,
                    '_conceptual_hint': 'Master switch for cell division. Off lets cells grow but never divide — isolates growth from population increase. Normally on.',
                    '_implementation_pattern': 'Boolean flag read class-level and checked by the relevant steppable to enable/disable the mitosis method (`if self.MitosisControl:`). From `Parameters.py`.',
                },
                'DeathControl': {
                    '_default': True,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Enable Cell Death',
                    '_description': 'Allow cell removal via sloughing, volume collapse, or chemical toxicity.',
                    '_category': 'Simulation Control',
                    '_subcategory': 'Biological Processes',
                    '_unit': 'boolean',
                    '_expert_level': 'intermediate',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': True},
                    '_cbo_term': 'cbo:CellDeath',
                    '_model_context': 'Master switch for Death_Sloughing, Death_Volume_Collapse, Death_Chemical, and Death_Execution_Shrink behaviors.',
                    '_debug_parameter': True,
                    '_conceptual_hint': 'Master switch for cell death and sloughing. Off disables turnover and injury death so the epithelium only accumulates. Normally on.',
                    '_implementation_pattern': 'Boolean flag read class-level and checked by the relevant steppable to enable/disable the death/sloughing method (`if self.DeathControl:`). From `Parameters.py`.',
                },
                'DifferentiationControl': {
                    '_default': True,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Enable Cell Differentiation',
                    '_description': 'Allow cells to change type based on environmental contact rules.',
                    '_category': 'Simulation Control',
                    '_subcategory': 'Biological Processes',
                    '_unit': 'boolean',
                    '_expert_level': 'intermediate',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': True},
                    '_cbo_term': 'cbo:CellDifferentiation',
                    '_model_context': 'Master switch for Differentiation_STEM_to_BASAL, Differentiation_BASAL_to_WING, and Differentiation_WING_to_SUPER behaviors.',
                    '_debug_parameter': True,
                    '_conceptual_hint': 'Master switch for state transitions (stem→basal→wing→super). Off freezes cell identities — useful to test mechanics alone. Normally on.',
                    '_implementation_pattern': 'Boolean flag read class-level and checked by the relevant steppable to enable/disable the differentiation method (`if self.DifferentiationControl:`). From `Parameters.py`.',
                },
                'DeathTimeScalar': {
                     '_default': 1.0,
                     '_updater': 'set',
                     '_emit': True,
                     '_display_name': 'Cell Shrink Rate Multiplier',
                     '_description': 'Multiplier for how quickly cells shrink when dying (higher values = faster removal).',
                     '_category': 'Simulation Control',
                     '_subcategory': 'Biological Processes',
                     '_unit': 'dimensionless',
                     '_dimension': 'dimensionless',
                     '_recommended_range': (0.1, 10.0),  # exploratory range (dimensionless)
                     '_expert_level': 'advanced',
                     '_reference_paper': {'source': 'Vanin et al., 2025 (S4 Text Cell Death and Injury Implementation)', 'value': 1.0, 'detail': 'Multiplicative scalar on the natural sloughing rate (Eq. 8). Source steppable line 207 imports from Parameters.py; default 1.0 keeps paper baseline rate of (1/3)/DAYtoMCS per MCS.'},
                     '_cbo_term': 'cbo:CellDeath',
                     '_model_context': 'Scales the speed (effective λ_v) of the Death_Execution_Shrink process (Eq. 28, 37).',
                     '_depends_on': ['DeathControl'],
                    '_conceptual_hint': 'Multiplies the natural sloughing probability (Eq. 8). 1.0 = paper baseline (≈1.75-day layer transit, 7–14-day turnover); >1 sheds superficial cells faster (thinner epithelium), <1 slower. Retunes turnover without touching the calibrated 1/3 factor.',
                    '_implementation_pattern': 'Read by the death/sloughing steppable; multiplies the per-MCS superficial sloughing probability (Eq. 8). From `Parameters.py`.',
                    '_literature': [90, 108],  # paper ref numbers -> references.py
                },

                # --- Data Collection Parameters ---
                # Note: the CC3D Player live-visualization toggle was removed.
                # The Vivarium wrapper runs CC3D as a headless subprocess; the
                # Player UI is not reachable from this code path, so a toggle
                # would be misleading.
                'CellCount': {
                    '_default': True,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Log Cell Counts',
                    '_description': 'Record the number of cells of each type over time.',
                    '_category': 'Data Collection',
                    '_subcategory': 'Population Tracking',
                    '_unit': 'boolean',
                    '_expert_level': 'basic',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': True},
                    '_cbo_term': 'cbo:SystemQualities',
                    '_model_context': 'Enables logging cell counts.',
                    '_output_files': ['cell_count_*.csv'],
                    '_conceptual_hint': 'Logs per-type cell counts over time — the primary homeostasis/recovery readout. Leave on for any quantitative run.',
                    '_implementation_pattern': 'Boolean logging flag: when on, the data-collection steppable records per-type cell counts. From `Parameters.py`.',
                },
                 # PressureTracker - Removed default real-time plotting, kept logging
                'PressureTracker': {
                    '_default': True,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Log Cell Pressure',
                    '_description': 'Record calculated pressure for each cell over time (based on volume deviation).',
                    '_category': 'Data Collection',
                    '_subcategory': 'Mechanical Properties',
                    '_unit': 'boolean',
                    '_expert_level': 'intermediate',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': False},
                    '_cbo_term': 'cbo:PressureMechanical',
                    '_model_context': 'Enables logging of cell pressure (Eq. 6).',
                    '_output_files': ['pressure_*.csv'], # Assumed output file
                    '_conceptual_hint': 'Logs/plots intracellular effective pressure, a diagnostic for the density-inhibition term. Off by default (verbose).',
                    '_implementation_pattern': 'Boolean logging flag: when on, the data-collection steppable records intracellular pressure. From `Parameters.py`.',
                },
                'EGF_SeenByCell': { # Renamed from Cell EGF Tracking
                    '_default': True, # Logging default
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Log Average Cell EGF',
                    '_description': 'Record the average EGF concentration within each cell over time.',
                    '_category': 'Data Collection',
                    '_subcategory': 'Growth Factor Tracking',
                    '_unit': 'boolean',
                    '_expert_level': 'intermediate',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': True},
                    '_cbo_term': 'cbo:MolecularField',
                    '_model_context': 'Enables logging AvgEGFConcentration state variable (Eq. 2).',
                    '_output_files': ['egf_by_cell_*.csv'], # Assumed output file
                    '_conceptual_hint': 'Records the mean EGF each cell experiences — shows how the superficial barrier shapes the growth signal.',
                    '_implementation_pattern': 'Boolean logging flag: when on, the data-collection steppable records per-cell EGF. From `Parameters.py`.',
                },
                'SLS_SeenByCell': { # Renamed from Cell Chemical Tracking
                    '_default': True,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Log Average Cell Chemical',
                    '_description': 'Record the average chemical concentration within each cell over time.',
                    '_category': 'Data Collection',
                    '_subcategory': 'Chemical Tracking',
                    '_unit': 'boolean',
                    '_expert_level': 'intermediate',
                    '_reference_paper': {'source': 'Vanin et al., 2025 (S11 Table)', 'value': False, 'detail': 'Paper supp default is False; schema default True for richer GUI debugging output.'},
                    '_cbo_term': 'cbo:MolecularField',
                    '_model_context': 'Enables logging AvgChemicalConcentration state variable (Eq. 35).',
                    '_depends_on': ['IsInjury', 'InjuryType'],
                    '_conditional_display': lambda params: params.get('IsInjury', False) and not params.get('InjuryType', False),
                    '_output_files': ['sls_by_cell_*.csv'], # Assumed output file
                    '_conceptual_hint': 'Records the mean injury-chemical each cell experiences — the basis for the death decision. Enable for chemical-injury analysis.',
                    '_implementation_pattern': 'Boolean logging flag: when on, the data-collection steppable records per-cell SLS. From `Parameters.py`.',
                },
                'CenterBias': { # Renamed from Movement Bias Tracking
                    '_default': False,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Log Movement Bias Field',
                    '_description': 'Record the concentration of the Movement Bias field over time.',
                    '_category': 'Data Collection',
                    '_subcategory': 'Movement Tracking',
                    '_unit': 'boolean',
                    '_expert_level': 'advanced',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': False},
                    '_cbo_term': 'cbo:MolecularField',
                    '_model_context': 'Enables logging of the BASALMVBIAS field.',
                    '_conceptual_hint': 'Diagnostic flag biasing initial placement/analysis toward the domain center. Off in standard runs.',
                    '_implementation_pattern': 'Boolean logging flag: when on, the data-collection steppable records the Movement-Bias field. From `Parameters.py`.',
                     '_output_files': ['center_bias_*.csv'], # Assumed output file
               },
                'ThicknessPlot': { # Renamed from Tissue Thickness Plot
                    '_default': True,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Log Tissue Thickness',
                    '_description': 'Record measurements of tissue thickness over time.',
                    '_category': 'Data Collection',
                    '_subcategory': 'Tissue Metrics',
                    '_unit': 'boolean',
                    '_expert_level': 'basic',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': True},
                    '_cbo_term': 'cbo:SystemQualities',
                    '_model_context': 'Enables logging thickness measurements.',
                    '_output_files': ['thickness_*.parquet'],
                    '_conceptual_hint': 'Collects epithelial thickness over time and space — the key structural validation against the 50–54 µm target. Leave on.',
                    '_implementation_pattern': 'Boolean logging flag: when on, the data-collection steppable records epithelial thickness. From `Parameters.py`.',
                },
                'SurfactantTracking': { # Renamed from Chemical Tracking
                    '_default': True,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Log Chemical Field Distribution',
                    '_description': 'Record the overall distribution of the chemical field over time.',
                    '_category': 'Data Collection',
                    '_subcategory': 'Chemical Tracking',
                    '_unit': 'boolean',
                    '_expert_level': 'intermediate',
                    '_reference_paper': {'source': 'Vanin et al., 2025 (S11 Table)', 'value': False, 'detail': 'Paper supp default is False; schema default True for richer GUI output during injury runs.'},
                    '_cbo_term': 'cbo:MolecularField',
                    '_model_context': 'Enables logging of the Chemical_Toxicant field.',
                    '_depends_on': ['IsInjury', 'InjuryType'],
                    '_conditional_display': lambda params: params.get('IsInjury', False) and not params.get('InjuryType', False),
                    '_output_files': ['surfactant_*.csv'], # Assumed output file based on filename pattern
                    '_conceptual_hint': 'Logs the SLS field distribution over time. Enable to study chemical spread during injury runs.',
                    '_implementation_pattern': 'Boolean logging flag: when on, the data-collection steppable records the SLS field over time. From `Parameters.py`.',
                },
                'DivisionTracker': {
                    '_default': True,
                    '_updater': 'set',
                    '_emit': True,
                    '_scope': 'wrapper',
                    '_display_name': 'Log Mitosis Events',
                    '_description': 'Record cell division events over time (per-MCS counter for STEM and BASAL divisions).',
                    '_category': 'Data Collection',
                    '_subcategory': 'Cell Events',
                    '_unit': 'boolean',
                    '_expert_level': 'intermediate',
                    '_reference_paper': {'source': 'Parameters.py (paper_version line 88)', 'value': True, 'detail': 'Not in paper supp tables; tunable in paper_version source.'},
                    '_output_files': ['division_count_*.csv'],
                    '_conceptual_hint': 'Logs division events (where and when cells divide) — useful for mapping proliferative zones.',
                    '_implementation_pattern': 'Boolean logging flag: when on, the data-collection steppable records division events. From `Parameters.py`.',
                },
                'SloughTracker': {
                    '_default': False,
                    '_updater': 'set',
                    '_emit': True,
                    '_scope': 'wrapper',
                    '_display_name': 'Log Slough Events',
                    '_description': 'Record superficial-cell sloughing events over time.',
                    '_category': 'Data Collection',
                    '_subcategory': 'Cell Events',
                    '_unit': 'boolean',
                    '_expert_level': 'intermediate',
                    '_reference_paper': {'source': 'Parameters.py (paper_version line 83)', 'value': False, 'detail': 'Not in paper supp tables; tunable in paper_version source.'},
                    '_output_files': ['slough_count_*.csv'],
                    '_conceptual_hint': 'Logs sloughing events at the surface — useful to quantify turnover.',
                    '_implementation_pattern': 'Boolean logging flag: when on, the data-collection steppable records sloughing events. From `Parameters.py`.',
                },
                'VolumeSurfaceDetail': {
                    '_default': False,
                    '_updater': 'set',
                    '_emit': True,
                    '_scope': 'wrapper',
                    '_display_name': 'Log Per-Cell Volume & Surface',
                    '_description': 'Record per-cell time series of volume and surface area (large output; off by default).',
                    '_category': 'Data Collection',
                    '_subcategory': 'Cell Metrics',
                    '_unit': 'boolean',
                    '_expert_level': 'advanced',
                    '_reference_paper': {'source': 'Parameters.py (paper_version line 90)', 'value': False, 'detail': 'Not in paper supp tables; tunable in paper_version source.'},
                    '_output_files': ['volume_surface_*.csv'],
                    '_storage_impact': 'high',
                    '_conceptual_hint': 'Logs per-cell volume/surface detail — a verbose diagnostic for mechanics tuning.',
                    '_implementation_pattern': 'Boolean logging flag: when on, the data-collection steppable records per-cell volume/surface detail. From `Parameters.py`.',
                },
                'SnapShot': {
                    '_default': False,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Enable Image Snapshots',
                    '_description': 'Save images of the simulation grid at regular intervals. Off by default for safety and to avoid large output directories; paper supp default is True but we keep False here.',
                    '_category': 'Data Collection',
                    '_subcategory': 'Visual Documentation',
                    '_unit': 'boolean',
                    '_expert_level': 'basic',
                    '_reference_paper': {'source': 'Vanin et al., 2025 (S11 Table)', 'value': True, 'detail': 'Paper supp default is True; schema default kept False for safety and data-storage cost.'},
                    '_cbo_term': 'cbo:SystemQualities',
                    '_model_context': 'Enables saving image snapshots.',
                    '_storage_impact': 'high',
                    '_conceptual_hint': 'Saves periodic image/state snapshots of the simulation (useful for movies); adds I/O overhead.',
                    '_implementation_pattern': 'Boolean logging flag: when on, the data-collection steppable records periodic image snapshots. From `Parameters.py`.',
                },
                'SnapShot_time': {
                    '_default': 10,
                    '_updater': 'set',
                    '_emit': True,
                    '_scope': 'wrapper',
                    '_display_name': 'Snapshot Interval',
                    '_description': 'Time interval between saving image snapshots.',
                    '_category': 'Data Collection',
                    '_subcategory': 'Visual Documentation',
                    '_unit': 'hours',
                    '_conversion_factor': MCS_TO_HOURS, # hours / MCS
                    '_physiological_range': (1, 48),
                    '_expert_level': 'basic',
                    '_reference_paper': {'source': 'Vanin et al., 2025', 'value': 10}, # Assuming the 10 is in hours based on display name
                    '_cbo_term': 'cbo:TemporalInterval',
                    '_model_context': 'Sets the time interval between snapshots.',
                    '_depends_on': ['SnapShot'],
                    '_conceptual_hint': 'Interval between snapshots (hours; stored as MCS, 10 MCS = 1 hour). Floats allowed down to 0.1 h (= 1 MCS). Smaller = more frequent snapshots and more I/O.',
                    '_implementation_pattern': 'Interval (in MCS, converted from hours) at which the snapshot steppable writes images. From `Parameters.py`.',
                },

                # OMEX/SED-ML archive generation is always-on: every run emits a
                # standards-compliant COMBINE archive. The toggle was removed
                # because reproducible provenance is non-negotiable. See
                # `create_omex_archive` invocation below.
            },

            'outputs': {
                 'replicate_results': {
                    '_default': [],
                    '_updater': 'set',
                    '_emit': True,
                    '_scope': 'wrapper',
                    '_description': 'List containing results dictionary for each replicate run.',
                },
                'simulation_success': {
                    '_default': False,
                    '_updater': 'set',
                    '_emit': True,
                    '_scope': 'wrapper',
                    '_description': 'Overall boolean flag indicating if ALL replicates completed without errors.',
                },
                'output_directory': {
                    '_default': '',
                    '_updater': 'set',
                    '_emit': True,
                    '_scope': 'wrapper',
                    '_description': 'Path to the main output directory for this batch run.',
                },
                'parameter_changes': {
                    '_default': {},
                    '_updater': 'set',
                    '_emit': True,
                    '_scope': 'wrapper',
                    '_description': 'Dictionary detailing parameters changed from their default values.',
                },
                'run_metadata': {
                    '_default': {},
                    '_updater': 'set',
                    '_emit': True,
                    '_scope': 'wrapper',
                    '_description': 'Comprehensive metadata dictionary for the batch run.',
                }
            }
        }

        return schema

    def next_update(self, timestep, states):
        """Executes a batch of vCornea simulations in parallel and returns results.

        Vivarium's Engine may invoke this more than once for a single
        engine.update() call depending on the process's time_step boundary
        evaluation. Each invocation would re-run the entire batch (creating
        a new vcornea_sim_<hex> under every replicate dir), which doubled
        outputs and confused the GUI when chasing the parallel-sweep
        contamination bug. Guard with a one-shot flag so a second
        invocation in the same process lifetime is a no-op.
        """
        if getattr(self, '_batch_already_run', False):
            print("VCorneaProcess: next_update called again — batch already ran, returning empty.")
            return {'outputs': {}}
        self._batch_already_run = True

        # Vivarium's `states['inputs']` only carries the schema defaults
        # because no upstream process writes to the inputs store. Any value
        # the user set in the GUI was passed to VCorneaProcess(parameters=...)
        # and lives in `self.parameters`. Overlay it onto sim_params so that
        # SimTime, sweep values, IsInjury, etc. actually reach the CC3D
        # Parameters.py and the run metadata. Without this overlay every
        # run silently used schema defaults (24 days, default sweep value,
        # parameters_changed=0).
        sim_params = dict(states['inputs'])
        for key in list(sim_params.keys()):
            if key in self.parameters:
                sim_params[key] = self.parameters[key]

        num_replicates = self.parameters.get('replicates', 1)
        print(f"VCorneaProcess: Starting batch of {num_replicates} parallel replicate(s).")
        # Surface the overlaid time-critical values so the run log explains
        # which numbers actually reached CC3D after the overlay.
        print(f"  Effective SimTime (days): {sim_params.get('SimTime')}  "
              f"InjuryTime (days): {sim_params.get('InjuryTime')}  "
              f"IsInjury: {sim_params.get('IsInjury')}")

        parameter_changes = self._identify_parameter_changes(sim_params)
        run_name = self._generate_run_name(parameter_changes)

        if self.parameters.get('output_base_dir'):
            output_base = Path(self.parameters['output_base_dir'])
        else:
            output_base = Path.cwd() / "simulation_results"
        
        batch_output_dir = output_base / run_name
        batch_output_dir.mkdir(parents=True, exist_ok=True)
        
        running_processes = []
        replicate_outputs = []

        # ======================================================
        # PHASE 1: SETUP AND LAUNCH ALL REPLICATES
        # ======================================================
        print("\n--- Phase 1: Launching all replicate processes ---")
        for i in range(num_replicates):
            replicate_id = i + 1
            run_output_dir = batch_output_dir / f"replicate_{replicate_id}"
            run_output_dir.mkdir(parents=True, exist_ok=True)
            
            # Prepare metadata and files for this replicate
            run_metadata = self._create_run_metadata(sim_params, parameter_changes, run_name)
            run_metadata['replicate_id'] = replicate_id
            run_metadata['total_replicates'] = num_replicates
            # Task B: per-run back-reference so a sweep/replicate run's archive is not
            # an orphan (parent experiment, swept-parameter point, replicate index).
            run_metadata['run_reference'] = self._build_run_reference(
                sim_params, run_name, replicate_id, num_replicates)

            # Each replicate gets its OWN independently drawn seed (see
            # _resolve_run_seed). Resolved before launch so no replicate can run
            # under a seed nobody recorded, and stamped onto both the metadata and
            # the Parameters.py archived beside the data.
            run_seed, seed_origin = self._resolve_run_seed(sim_params, replicate_id)
            run_metadata['random_seed'] = run_seed
            run_metadata['random_seed_origin'] = seed_origin
            replicate_params = dict(sim_params)
            replicate_params['random_seed'] = run_seed

            # Keep the working directory inside the user's chosen output
            # directory — it's where they can inspect Parameters.py and the
            # in-progress CC3D state. cmd.exe handles mapped drive letters
            # (X:\...) and local Windows paths (C:\...) fine; the prior UNC
            # cwd issue only triggers when the user picks a \\wsl.localhost\
            # path directly. With Fix E (Path.absolute() instead of resolve())
            # the GUI preserves the X:\ drive letter the user selected.
            #
            # We append a short uuid so a leftover vcornea_sim from a prior
            # (failed/incompletely-cleaned) run cannot race with a fresh
            # copytree: Windows file locks intermittently make rmtree silently
            # fail, after which copytree raises WinError 183 ("file already
            # exists") and kills the replicate at launch.
            temp_dir = run_output_dir / f"vcornea_sim_{uuid.uuid4().hex[:6]}"

            try:
                # Setup the simulation environment in a temporary directory
                temp_project = Path(temp_dir)

                # Copy project with ignore function to skip problematic files
                def ignore_files(directory, files):
                    # Skip Windows Zone.Identifier files (alternate data streams)
                    # These files have ':' in the name which causes issues on Windows
                    ignored = []
                    for f in files:
                        if ':Zone.Identifier' in f or f.endswith(':Zone.Identifier'):
                            ignored.append(f)
                        elif ':' in f:  # Any file with ':' is problematic on Windows
                            ignored.append(f)
                    return ignored

                shutil.copytree(self.project_path, temp_project,
                               ignore=ignore_files,
                               copy_function=shutil.copyfile)
                self._redirect_outputs_in_copy(temp_project, run_output_dir)
                self._inject_random_seed_in_copy(temp_project, run_seed)
                sim_params_file = temp_project / "Simulation" / "Parameters.py"
                self._write_parameters_file(sim_params_file, replicate_params)

                # Baseline for the generated-vs-collected audit (see
                # _get_generated_files_list). BOTH locations are snapshotted: the
                # steppable redirect sends outputs straight to run_output_dir, while
                # anything written through a hardcoded path lands in the temp
                # project. Snapshotting only the temp dir made "files generated"
                # permanently empty and the audit meaningless.
                temp_sim_dir = temp_project / "Simulation"
                before_snapshot = (self._take_directory_snapshot(temp_sim_dir)
                                   | self._take_directory_snapshot(run_output_dir))

                # Launch the simulation and get the process handle
                process, stdout_log, stderr_log = self._run_cc3d_simulation(temp_project, run_output_dir)

                if process:
                    # Store the handle and related info
                    running_processes.append({
                        'process': process,
                        'replicate_id': replicate_id,
                        'output_dir': run_output_dir,
                        'temp_dir': temp_dir,
                        'temp_project': temp_project,
                        'metadata': run_metadata,
                        'stdout_log': stdout_log,
                        'stderr_log': stderr_log,
                        # Carried forward to Phase 3; previously computed and
                        # dropped, which silently disabled the audit.
                        'before_snapshot': before_snapshot,
                    })
                    print(f"  > Replicate {replicate_id} launched (PID: {process.pid}).")
                else:
                    raise RuntimeError("Process launch failed.")

            except Exception as e:
                print(f"  > FAILED to launch replicate {replicate_id}: {e}")
                shutil.rmtree(temp_dir, ignore_errors=True)
                run_metadata['simulation_success'] = False
                run_metadata['error_message'] = f"Failed during setup/launch phase: {e}"
                # Immediately add a failure report for this replicate
                replicate_outputs.append({
                    'replicate_id': replicate_id, 'success': False,
                    'output_directory': str(run_output_dir),
                    'error_message': run_metadata['error_message'], 'results': None
                })

        # ======================================================
        # PHASE 2: CONCURRENT PROCESS MONITORING WITH FUTURES
        # ======================================================
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import time

        def monitor_process(job):
            """Monitor a single process until completion and return job with results."""
            process = job['process']
            
            timeout_s = int(self.parameters.get('run_timeout_seconds', 86400) or 86400)
            try:
                # Wait for this specific process to complete
                exit_code = process.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                print(f"  > TIMEOUT ERROR: Replicate {job['replicate_id']} exceeded the "
                      f"{timeout_s}s ({timeout_s / 3600:.1f}h) limit.")
                process.kill()  # Terminate the runaway process
                exit_code = -9  # specific exit code for timeouts
                job['timed_out'] = True

            # Mirror of the Phase-1 baseline: both the temp project and the
            # redirect destination, taken the moment the process exits.
            temp_sim_dir = job['temp_project'] / "Simulation"
            job['after_snapshot'] = (self._take_directory_snapshot(temp_sim_dir)
                                     | self._take_directory_snapshot(job['output_dir']))

            job['exit_code'] = exit_code
            job['completed_at'] = time.time()
            
            # Close log files
            job['stdout_log'].close()
            job['stderr_log'].close()
            
            return job

        print("\n--- Phase 2: Monitoring all processes concurrently ---")

        # Check if any processes were successfully launched
        if not running_processes:
            print("  > ERROR: No replicates were successfully launched. Returning empty results.")
            return {
                'outputs': {
                    'run_name': run_name,
                    'batch_output_dir': str(batch_output_dir),
                    'replicates': replicate_outputs,
                    'success': False,
                    'error_message': 'All replicates failed to launch'
                }
            }

        # Use ThreadPoolExecutor to monitor all processes concurrently
        with ThreadPoolExecutor(max_workers=len(running_processes)) as executor:
            # Submit monitoring tasks for all processes
            future_to_job = {
                executor.submit(monitor_process, job): job 
                for job in running_processes
            }
            
            completed_jobs = []
            
            # Collect results as they complete
            for future in as_completed(future_to_job):
                job = future_to_job[future]
                try:
                    completed_job = future.result()
                    completed_jobs.append(completed_job)
                    print(f"  > Replicate {completed_job['replicate_id']} (PID: {completed_job['process'].pid}) finished with exit code {completed_job['exit_code']}")
                except Exception as e:
                    print(f"  > Error monitoring replicate {job['replicate_id']}: {e}")
                    job['exit_code'] = -1  # Mark as failed
                    job['error'] = str(e)
                    completed_jobs.append(job)

        print(f"  > All {len(completed_jobs)} processes completed")

        # ======================================================
        # PHASE 3: COLLECT RESULTS FROM ALL COMPLETED PROCESSES
        # ======================================================
        print("\n--- Phase 3: Collecting results from completed processes ---")

        for job in completed_jobs:
            replicate_id = job['replicate_id']
            run_output_dir = job['output_dir']
            temp_project = job['temp_project']
            run_metadata = job['metadata']
            exit_code = job['exit_code']
            
            print(f"  > Processing results for replicate {replicate_id}...")

            # Close log files
            job['stdout_log'].close()
            job['stderr_log'].close()

            # Before/after snapshots taken in Phases 1 and 2. These were previously
            # read from the job dict (where they had never been stored) and then
            # immediately overwritten with an empty baseline, so every file present
            # at the end counted as "generated" and the audit could not actually
            # distinguish a simulator that produced nothing from a wrapper that
            # collected nothing.
            before_files = job.get('before_snapshot', set())
            after_files = job.get('after_snapshot')
            if after_files is None:
                temp_sim_dir = temp_project / "Simulation"
                after_files = (self._take_directory_snapshot(temp_sim_dir)
                               | self._take_directory_snapshot(run_output_dir))

            # Process based on exit code AND whether real output files were
            # produced. CC3D can exit 0 even when it crashed before writing
            # any data (e.g. UNC-cwd failures on Windows) — relying on the
            # exit code alone caused silent "successes" with empty results.
            if exit_code == 0:
                print(f"    - Collecting output files...")
                files_moved = self._collect_output_files(temp_project, run_output_dir, sim_params)
                print(f"    - Copying Parameters.py for reference...")
                self._copy_parameters_file(temp_project, run_output_dir)
                generated_files = self._get_generated_files_list(temp_project, before_files, after_files)

                # Real-output gate: a successful run must have produced at least
                # one cell_count CSV. If none reached run_output_dir, treat the
                # replicate as failed even though the subprocess returned 0.
                has_real_outputs = any(
                    'cell_count' in str(f).lower() for f in files_moved
                ) or any(p.name.startswith('cell_count_') for p in run_output_dir.glob('cell_count_*'))

                if has_real_outputs:
                    print(f"    - Parsing simulation results...")
                    results = self._parse_simulation_results(run_output_dir, sim_params)
                    run_metadata.update({
                        'simulation_success': True,
                        'simulation_completed_at': pd.Timestamp.now().isoformat(),
                        'healing_time': results.get('healing_time'),
                        'files_collected': files_moved,
                        'files_generated': generated_files,
                    })
                    replicate_outputs.append({
                        'replicate_id': replicate_id,
                        'success': True,
                        'output_directory': str(run_output_dir),
                        'error_message': None,
                        'results': results,
                        'files_generated': generated_files,
                        'files_collected': files_moved,
                    })
                    print(f"    - Replicate {replicate_id} completed successfully")
                else:
                    error_message = (
                        f"Simulation process exited cleanly (code {exit_code}) but produced no "
                        f"cell_count_*.csv output. The CC3D simulation likely failed silently "
                        f"during startup (check stderr.log for UNC path / missing .cc3d / conda "
                        f"environment errors)."
                    )
                    run_metadata.update({
                        'simulation_success': False,
                        'simulation_completed_at': pd.Timestamp.now().isoformat(),
                        'error_message': error_message,
                        'files_collected': files_moved,
                        'files_generated': generated_files,
                    })
                    replicate_outputs.append({
                        'replicate_id': replicate_id,
                        'success': False,
                        'output_directory': str(run_output_dir),
                        'error_message': error_message,
                        'results': None,
                        'files_generated': generated_files,
                        'files_collected': files_moved,
                    })
                    print(f"    - Replicate {replicate_id} FAILED: no output files produced (despite exit 0)")

            else:
                # Non-zero exit
                error_message = f"Simulation process failed with exit code {exit_code}. Check stderr.log in the output directory."
                run_metadata.update({
                    'simulation_success': False,
                    'error_message': error_message,
                })
                replicate_outputs.append({
                    'replicate_id': replicate_id,
                    'success': False,
                    'output_directory': str(run_output_dir),
                    'error_message': error_message,
                    'results': None,
                    'files_generated': [],
                    'files_collected': [],
                })
                print(f"    - Replicate {replicate_id} failed with exit code {exit_code}")

            # Save metadata and clean up
            with open(run_output_dir / "run_metadata.json", 'w') as f:
                json.dump(run_metadata, f, indent=2)

            # Always produce a typed COMBINE/OMEX archive — successful AND failed.
            # A failed run gets an archive marked failed (no executable SED-ML, a
            # machine-readable status), carrying params/provenance, logs and any
            # partial outputs. This keeps the run's provenance honest about failure
            # rather than leaving it as a loose directory: the original concern (an
            # .omex for a failed run is misleading provenance) is addressed by making
            # the archive explicitly NOT a reproducible success, not by skipping it.
            run_succeeded = bool(run_metadata.get('simulation_success'))
            try:
                from ..utils.omex_generator import create_omex_archive
                omex_path = create_omex_archive(
                    run_output_dir=run_output_dir,
                    run_metadata=run_metadata,
                    sim_params=sim_params,
                    include_model=True,   # bundle the CC3D project so model/@source resolves
                    creator=self.parameters.get('creator'),  # experimenter (provenance); None -> omitted
                    failed=not run_succeeded,
                )
                run_metadata['omex_archive'] = str(omex_path.name)
                # Re-save metadata with OMEX info
                with open(run_output_dir / "run_metadata.json", 'w') as f:
                    json.dump(run_metadata, f, indent=2)
                print(f"    - Generated {'FAILED ' if not run_succeeded else ''}OMEX archive: {omex_path.name}")
            except Exception as e:
                print(f"    - Warning: Could not generate OMEX archive: {e}")
                run_metadata['omex_archive'] = None

            self._update_experiment_log(output_base, run_metadata)
            # Keep the working directory inside the run output dir for
            # inspection. The user requested this layout; we no longer wipe
            # it after collection because the CC3D project copy, the
            # generated Parameters.py, and any intermediate snapshots are
            # useful for post-mortem when a run fails.
            # shutil.rmtree(job['temp_dir'], ignore_errors=True)

        print(f"--- Result collection completed ---")
        overall_success = all(rep['success'] for rep in replicate_outputs if 'success' in rep)

        return {
            'outputs': {
                'replicate_results': sorted(replicate_outputs, key=lambda r: r['replicate_id']), 
                'simulation_success': overall_success,
                'output_directory': str(batch_output_dir),
                'parameter_changes': parameter_changes,
                'run_metadata': self._create_run_metadata(sim_params, parameter_changes, run_name)
            }
        }

    def _auto_discover_vcornea(self):
        """Auto-discover vCornea installation using common patterns."""
        
        search_locations = [
            # (highest priority)
            self._get_json_config_path(),

            # Local repo-relative locations (cell-fate project)
            Path.cwd() / "vcornea_cellfate_updated",
            Path.cwd().parent / "vcornea_cellfate_updated",

            # Sibling directory (common development setup)
            Path(__file__).parent.parent.parent / "vCornea/HPC/Project/paper_version",
            Path(__file__).parent.parent.parent / "vCornea/Local/Project/paper_version",
            
            # User's home directory
            Path.home() / "vCornea/HPC/Project/paper_version",
            Path.home() / "vCornea/Local/Project/paper_version",
            
            # Current working directory relatives
            Path.cwd() / "../vCornea/HPC/Project/paper_version",
            Path.cwd() / "../vCornea/Local/Project/paper_version",
        ]
        
        for location in search_locations:
            if location and Path(location).exists():
                cc3d_file = Path(location) / "vCornea_v2.cc3d"
                if cc3d_file.exists():
                    return str(location)
        
        return None 

    def _get_json_config_path(self):
        """Get path from JSON config if it exists, checking multiple locations."""
        
        # Possible config file locations (in order of preference)
        config_locations = [
            # 1. Current working directory (highest priority)
            Path.cwd() / "vcornea_config.json",
            
            # 2. Project root (relative to package)
            Path(__file__).parent.parent.parent / "vcornea_config.json",
            
            # 3. User's home directory
            Path.home() / ".vcornea_config.json",
            
            # 4. Package directory (fallback)
            Path(__file__).parent.parent / "vcornea_config.json",
        ]
        
        for config_file in config_locations:
            if config_file.exists():
                try:
                    with open(config_file, 'r') as f:
                        config = json.load(f)
                    print(f"Using config from: {config_file}")
                    return config.get('vcornea_project_path')
                except Exception as e:
                    print(f"Warning: Could not read {config_file}: {e}")
                    continue
        
        return None

    def _identify_parameter_changes(self, sim_params):
        """Identify which parameters have been changed from their defaults."""
        parameter_changes = {}
        
        # Get default values from the ports schema
        defaults = {}
        for param, schema in self.ports_schema()['inputs'].items():
            defaults[param] = schema['_default']
        
        # Compare current values with defaults
        for param, value in sim_params.items():
            if param in defaults:
                default_value = defaults[param]
                if value != default_value:
                    parameter_changes[param] = {
                        'current_value': value,
                        'default_value': default_value,
                        'change_type': self._classify_change(value, default_value)
                    }
        
        return parameter_changes

    def _classify_change(self, current, default):
        """Classify the type of parameter change."""
        if isinstance(current, bool) and isinstance(default, bool):
            return 'toggled'  # Fix: Handle booleans first
        elif isinstance(current, (int, float)) and isinstance(default, (int, float)):
            if current > default:
                return 'increased'
            else:
                return 'decreased'
        else:
            return 'modified'

    def _generate_run_name(self, parameter_changes):
        """Generate a descriptive run name based on parameter changes.

        Precedence: explicit run_name > GUI exp_name > generated descriptive
        name from parameter changes > default_run_<timestamp>. The GUI passes
        'exp_name' (not 'run_name') so we honor it here to keep inner
        replicate directories named consistently with the batch directory.
        """

        # If user provided a custom name, use it
        if self.parameters.get('run_name'):
            return self.parameters['run_name']
        if self.parameters.get('exp_name'):
            return self.parameters['exp_name']

        # *** NEW LOGIC: Use the unique run_id from the GUI if available ***
        run_id = self.parameters.get('run_id')

        # If no parameters changed, use a simple name
        if not parameter_changes:
            base_name = "default_run"
            return f"{base_name}_{run_id}" if run_id else f"{base_name}_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}"

        # Generate descriptive name based on key parameter changes
        name_parts = []
        max_params = self.parameters.get('max_params_in_name', 3)
        
        priority_params = [
            'SLS_Concentration', 'SLS_Y_Center', 'SLS_X_Center',
            'InjuryTime', 'SimTime', 'IsInjury', 'InjuryType',
            'EGF_STEM_HalfMaxValue', 'EGF_BASAL_HalfMaxValue',  # Add other swept params here
        ]
        
        # First, add high-priority parameters
        for param in priority_params:
            if param in parameter_changes and len(name_parts) < max_params:
                change = parameter_changes[param]
                name_parts.append(self._format_param_for_name(param, change))
        
        # Then add other parameters if we have space
        for param, change in parameter_changes.items():
            if param not in priority_params and len(name_parts) < max_params:
                name_parts.append(self._format_param_for_name(param, change))
        
        if len(parameter_changes) > max_params:
            name_parts.append(f"plus{len(parameter_changes) - max_params}more")
        
        base_name = "_".join(name_parts) if name_parts else "modified_params"
        
        # Append the unique run_id instead of the timestamp
        return f"{base_name}_{run_id}" if run_id else f"{base_name}_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}"
        
        # """Generate a descriptive run name based on parameter changes."""
        
        # # If user provided a custom name, use it
        # if self.parameters.get('run_name'):
        #     return self.parameters['run_name']
        
        # # If no parameters changed, use default name
        # if not parameter_changes:
        #     timestamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
        #     return f"default_run_{timestamp}"
        
        # # Generate descriptive name based on key parameter changes
        # name_parts = []
        # max_params = self.parameters.get('max_params_in_name', 3)
        
        # # Prioritize certain parameters for naming
        # priority_params = [
        #     'SLS_Concentration', 'InjuryTime', 'SimTime', 'IsInjury', 'InjuryType',
        #     'EGF_STEM_HalfMaxValue', 'EGF_BASAL_HalfMaxValue'
        # ]
        
        # # First, add high-priority parameters
        # for param in priority_params:
        #     if param in parameter_changes and len(name_parts) < max_params:
        #         change = parameter_changes[param]
        #         name_parts.append(self._format_param_for_name(param, change))
        
        # # Then add other parameters if we have space
        # for param, change in parameter_changes.items():
        #     if param not in priority_params and len(name_parts) < max_params:
        #         name_parts.append(self._format_param_for_name(param, change))
        
        # # If we have many changes, add a count
        # if len(parameter_changes) > max_params:
        #     name_parts.append(f"plus{len(parameter_changes) - max_params}more")
        
        # # Combine parts
        # if name_parts:
        #     base_name = "_".join(name_parts)
        # else:
        #     base_name = "modified_params"
        
        # # Add timestamp for uniqueness
        # timestamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
        # return f"{base_name}_{timestamp}"

    def _format_param_for_name(self, param, change):
        """Format a parameter change for inclusion in the run name."""
        value = change['current_value']
        
        # Special formatting for certain parameters
        if param == 'SLS_Concentration':
            return f"SLS{int(value)}"
        elif param == 'InjuryTime':
            return f"InjT{int(value)}"
        elif param == 'SimTime':
            return f"SimT{int(value)}"
        elif param == 'IsInjury':
            return "WithInjury" if value else "NoInjury"
        elif param == 'InjuryType':
            return "Ablation" if value else "Chemical"
        elif isinstance(value, bool):
            return f"{param}_{str(value)}"
        elif isinstance(value, (int, float)):
            if isinstance(value, float) and value.is_integer():
                return f"{param}{int(value)}"
            else:
                return f"{param}{value}"
        else:
            return f"{param}_{str(value)}"

    def _build_run_reference(self, sim_params, run_name, replicate_id, num_replicates):
        """Task B back-reference: stop a sweep/replicate run's archive from being an
        orphan. Returns {parent_experiment_id, parameter_combination, replicate_index,
        ...} or None for a single (non-sweep, single-replicate) run."""
        scan_spec = self.parameters.get('parameter_scan')
        scan_point = self.parameters.get('scan_point')
        if scan_spec and scan_point is None:
            scan_point = {p: sim_params.get(p) for p in scan_spec if p in sim_params}
        is_sweep = bool(scan_spec)
        is_replicated = bool(num_replicates and num_replicates > 1)
        if not (is_sweep or is_replicated):
            return None
        parent = (self.parameters.get('parent_experiment_id')
                  or self.parameters.get('parent_experiment') or run_name)
        return {
            'parent_experiment_id': parent,
            'parameter_combination': scan_point or None,
            'replicate_index': replicate_id,
            'combination_index': self.parameters.get('combination_index'),
            'total_combinations': self.parameters.get('total_combinations'),
            'total_replicates': num_replicates,
            'parameter_scan': scan_spec or None,
        }

    def _create_run_metadata(self, sim_params, parameter_changes, run_name):
        """Create comprehensive metadata for this run."""
        metadata = {
            'run_name': run_name,
            'created_at': pd.Timestamp.now().isoformat(),
            'vivarium_wrapper_version': '1.0.0',  # You can version your wrapper
            'total_parameters': len(sim_params),
            'parameters_changed': len(parameter_changes),
            'parameter_changes': parameter_changes,
            'simulation_config': {
                'vcornea_project_path': str(self.parameters['vcornea_project_path']),
                'cc3d_conda_env_name': self.parameters['cc3d_conda_env_name'],
                'sim_time': sim_params.get('SimTime', 7700),
                'has_injury': sim_params.get('IsInjury', False),
                'injury_type': 'ablation' if sim_params.get('InjuryType', False) else 'chemical'
            },
            'key_parameters': {
                param: sim_params.get(param, 'not_set') 
                for param in ['SLS_Concentration', 'InjuryTime', 'SimTime', 'IsInjury']
            },
            'simulation_success': None,  # Will be updated after simulation
            'simulation_completed_at': None,
            'files_generated': [],
            'healing_time': None
        }

        # Run identity (requirement 2.5.1): a content hash of the parameter
        # definitions in force plus the identity of the code that ran. Recorded
        # separately from vivarium_wrapper_version above, which is hand-maintained
        # and cannot detect drift on its own. Best-effort — provenance capture must
        # never be able to fail a run.
        try:
            from ..utils.provenance import run_provenance
            metadata['provenance'] = run_provenance(self.ports_schema())
            metadata['schema_fingerprint'] = metadata['provenance']['schema_fingerprint']
        except Exception as e:
            metadata['provenance'] = {'error': f'provenance capture failed: {e}'}

        # Parameter-scan provenance (present only for sweep/batch runs). The GUI passes
        # the full scan space plus this run's point so the OMEX generator can (a) annotate
        # this per-run archive with its scan point and (b) build the experiment-level scan
        # archive. These are control keys, not CC3D parameters — they live only in metadata.
        scan_spec = self.parameters.get('parameter_scan')
        if scan_spec:
            metadata['parameter_scan'] = scan_spec
            scan_point = self.parameters.get('scan_point')
            if scan_point is None:
                # Derive this run's swept values from sim_params if not supplied.
                scan_point = {p: sim_params.get(p) for p in scan_spec if p in sim_params}
            metadata['scan_point'] = scan_point
            if self.parameters.get('combination_index') is not None:
                metadata['combination_index'] = self.parameters['combination_index']
            if self.parameters.get('total_combinations') is not None:
                metadata['total_combinations'] = self.parameters['total_combinations']

        return metadata

    def _update_experiment_log(self, output_base, run_metadata):
        """Update the master experiment log with this run's information."""
        log_file = output_base / "experiment_log.csv"
        
        # Create log entry
        log_entry = {
            'run_name': run_metadata['run_name'],
            'created_at': run_metadata['created_at'],
            'simulation_success': run_metadata['simulation_success'],
            'parameters_changed': run_metadata['parameters_changed'],
            'sim_time': run_metadata['simulation_config']['sim_time'],
            'has_injury': run_metadata['simulation_config']['has_injury'],
            'injury_type': run_metadata['simulation_config']['injury_type'],
            'healing_time': run_metadata.get('healing_time', ''),
            'output_directory': run_metadata['run_name']
        }
        #TODO: Add all the parameters used in the run to the log
        # Add key parameter changes to the log
        for param, change in run_metadata.get('parameter_changes', {}).items():
            # if param in ['SLS_Concentration', 'InjuryTime', 'EGF_STEM_HalfMaxValue']:
            log_entry[f'{param}_value'] = change['current_value']
            log_entry[f'{param}_default'] = change['default_value']
        
        # Read existing log or create new DataFrame
        if log_file.exists():
            try:
                df = pd.read_csv(log_file)
                # Append new entry
                new_df = pd.concat([df, pd.DataFrame([log_entry])], ignore_index=True)
            except Exception as e:
                print(f"Warning: Could not read existing log file: {e}")
                new_df = pd.DataFrame([log_entry])
        else:
            new_df = pd.DataFrame([log_entry])
        
        # Save updated log
        try:
            new_df.to_csv(log_file, index=False)
            print(f"Updated experiment log: {log_file}")
        except Exception as e:
            print(f"Warning: Could not update experiment log: {e}")

    def _resolve_run_seed(self, sim_params, replicate_id):
        """Return (seed, origin) for one replicate. Never returns the sentinel.

        Seeds are drawn INDEPENDENTLY per replicate from the operating system's
        entropy source, not derived by offsetting a shared base: deriving them
        arithmetically would make replicate independence an assumption about how
        the generator expands adjacent seeds rather than a property of the design.
        The batch stays reproducible because every seed is recorded with its run.

        Nothing prescribes a value. An operator who pins a seed is asking to
        reproduce one specific realization, so the pinned value applies to the
        first replicate; any further replicates must be distinct realizations or
        they are not replicates, and draw their own.
        """
        import random as _random
        try:
            pinned = int(sim_params.get('random_seed', self.AUTO_SEED))
        except (TypeError, ValueError):
            pinned = self.AUTO_SEED
        if pinned >= 0 and replicate_id == 1:
            return pinned, 'explicit'
        # 2**31-1 keeps the value inside the range CC3D's C++ RNG accepts.
        return _random.SystemRandom().randrange(1, 2 ** 31 - 1), 'drawn'

    def _inject_random_seed_in_copy(self, temp_project, seed):
        """Set <RandomSeed> in the copied project's CC3DML so the run is replayable.

        The decoupled pattern has no live spec object to configure, so the seed is
        written into the <Potts> block of the COPY — the same targeted edit strategy
        already used to redirect outputs, and applied only to the per-replicate
        workspace so the validated source project is never touched. Without this
        CC3D self-seeds and the realization cannot be identified afterwards.

        Best-effort: a project whose XML cannot be located still runs, it just runs
        unseeded, and the caller's recorded seed would then be wrong — so a failure
        here is reported loudly rather than swallowed.
        """
        import re
        xml_files = sorted((temp_project / "Simulation").glob("*.xml"))
        if not xml_files:
            print("  > [WARNING] no CC3DML file found; run will be UNSEEDED "
                  "and the recorded seed will not describe it")
            return False
        for xml_path in xml_files:
            try:
                content = xml_path.read_text()
            except Exception as e:
                print(f"  > [WARNING] could not read {xml_path.name}: {e}")
                continue
            if '<Potts>' not in content:
                continue
            if re.search(r'<RandomSeed>.*?</RandomSeed>', content, flags=re.S):
                content = re.sub(r'<RandomSeed>.*?</RandomSeed>',
                                 f'<RandomSeed>{int(seed)}</RandomSeed>',
                                 content, flags=re.S)
            else:
                content = content.replace(
                    '<Potts>', f'<Potts>\n       <RandomSeed>{int(seed)}</RandomSeed>', 1)
            try:
                xml_path.write_text(content)
                print(f"  > [OK] seeded {xml_path.name} with RandomSeed={int(seed)}")
                return True
            except Exception as e:
                print(f"  > [WARNING] could not write seed into {xml_path.name}: {e}")
        print("  > [WARNING] no <Potts> block found; run will be UNSEEDED")
        return False

    def _redirect_outputs_in_copy(self, temp_project, external_output_dir):
        """Modify the copied vCornea steppables to redirect outputs to external directory."""
        steppables_file = temp_project / "Simulation" / "vCornea_v2Steppables.py"

        if not steppables_file.exists():
            raise FileNotFoundError(f"Steppables file not found: {steppables_file}")

        # Read the original steppables file
        with open(steppables_file, 'r') as f:
            content = f.read()

        safe_path = str(external_output_dir).replace('\\', '/')

        # Strategy: Replace the pg.set_output_dir() call directly to use the replicate folder
        # This is more robust than trying to match the output_directory calculation
        import re

        # PRIMARY FIX: Find and replace the pg.set_output_dir() call
        # This is the most critical change - it forces CC3D to write outputs to the replicate folder
        # Original pattern: pg.set_output_dir(str(output_directory))
        # New: directly set to external output directory
        pg_pattern = r'pg\.set_output_dir\(str\(output_directory\)\)'
        pg_replacement = f'pg.set_output_dir(r"{safe_path}")'

        if re.search(pg_pattern, content):
            content = re.sub(pg_pattern, pg_replacement, content)
            print(f"  > [OK] Redirected pg.set_output_dir() to: {safe_path}")
        else:
            # Fallback: try to find any pg.set_output_dir call
            pg_pattern_flexible = r'pg\.set_output_dir\([^)]+\)'
            if re.search(pg_pattern_flexible, content):
                content = re.sub(pg_pattern_flexible, pg_replacement, content)
                print(f"  > [OK] Redirected pg.set_output_dir() (flexible match) to: {safe_path}")
            else:
                print(f"  > [WARNING] Could not find pg.set_output_dir() to redirect!")

        # Also redirect current_script_directory to external output directory
        # This ensures any other output paths are also redirected
        content = re.sub(
            r'current_script_directory = Path\(__file__\)\.parent',
            f'current_script_directory = Path(r"{safe_path}")',
            content,
        )
        content = re.sub(
            r'self\.current_script_directory = Path\(__file__\)\.parent',
            f'self.current_script_directory = Path(r"{safe_path}")',
            content,
        )
        
        # Also ensure Path is imported
        if 'from pathlib import Path' not in content:
            content = 'from pathlib import Path\n' + content

        import re
        content = re.sub(
            r'^\s*current_script_directory\s*=\s*Path\(__file__\)\.parent',
            (
                f'current_script_directory = Path(r"{safe_path}")\n'
                f'current_script_directory.mkdir(parents=True, exist_ok=True)'
            ),
            content,
            flags=re.MULTILINE,
        )
        content = re.sub(
            r'^\s*output_directory\s*=.*$',
            (
                f'output_directory = Path(r"{safe_path}")\n'
                f'output_directory.mkdir(parents=True, exist_ok=True)'
            ),
            content,
            flags=re.MULTILINE,
        )
        content = re.sub(
            r'pg\.set_output_dir\(.*\)',
            f'pg.set_output_dir(r"{safe_path}")',
            content,
        )
        content = re.sub(
            r'self\.current_script_directory\s*=\s*Path\(__file__\)\.parent',
            (
                f'self.current_script_directory = Path(r"{safe_path}")\n'
                f'self.current_script_directory.mkdir(parents=True, exist_ok=True)'
            ),
            content,
        )
        
        # Write the modified content back
        with open(steppables_file, 'w') as f:
            f.write(content)

    # Conversion factors from schema time units to MCS (CC3D's native time unit).
    # Mirrors the constants in ports_schema(): 1 MCS = 6 min => 240 MCS / day, 10 MCS / hour.
    _UNIT_TO_MCS_MULTIPLIER = {
        'days': 240,
        'hours': 10,
        'minutes': 1.0 / 6.0,
    }

    def _to_cc3d_units(self, param_name, value, schema=None):
        """Convert a schema-layer parameter value into CC3D-native units (MCS for time).

        The schema exposes user-friendly units (days, hours) so the GUI can present
        physiological numbers; CC3D itself only speaks Monte Carlo Steps. This
        helper looks up the parameter's `_unit` in the schema and applies the
        appropriate multiplier. Non-time parameters pass through unchanged.
        """
        if schema is None:
            schema = self.ports_schema()
        info = schema.get('inputs', {}).get(param_name)
        if not info:
            return value
        unit = info.get('_unit', '')
        multiplier = self._UNIT_TO_MCS_MULTIPLIER.get(unit)
        if multiplier is None or not isinstance(value, (int, float)) or isinstance(value, bool):
            return value
        converted = value * multiplier
        return int(round(converted)) if isinstance(info.get('_default'), int) else converted

    def _read_existing_parameters(self, params_file):
        """Parse an existing Parameters.py into a {name: value} dict.

        Used as the base layer when (re)writing Parameters.py. The steppable does
        `from Parameters import *`, so every name it reads must remain defined —
        including variables the GUI/schema deliberately does NOT expose (e.g.
        InitBASAL_Division, read at vCornea_v2Steppables.py:147). Without this base
        layer the writer would emit only schema params and drop those names,
        raising NameError on CC3D startup.

        Values in the canonical file are already in CC3D-native units, so they are
        parsed verbatim (and later passed through _to_cc3d_units unchanged, since
        names absent from the schema are not converted).
        """
        base = {}
        if not params_file.exists():
            return base
        with open(params_file, 'r') as f:
            for line in f:
                stripped = line.split('#', 1)[0].strip()
                if not stripped or '=' not in stripped:
                    continue
                name, _, value_str = stripped.partition('=')
                name, value_str = name.strip(), value_str.strip()
                if not name.isidentifier() or not value_str:
                    continue
                try:
                    base[name] = ast.literal_eval(value_str)
                except (ValueError, SyntaxError):
                    base[name] = value_str  # preserve verbatim if not a literal
        return base

    def _write_parameters_file(self, params_file, sim_params):
        """Write a COMPLETE Parameters.py for the vCornea model.

        The file must define every variable the steppable imports via
        `from Parameters import *`, including ones the GUI/schema deliberately does
        not expose. We therefore layer three sources (low -> high precedence):

            canonical base (existing file)  <  schema defaults  <  user values

        so GUI-hidden-but-required variables (e.g. InitBASAL_Division) keep their
        canonical value and can never be silently dropped.

        Time-valued schema parameters (SimTime in days, SnapShot_time in hours) are
        converted to MCS here so CC3D consumes native units; base-only variables are
        already in native units and pass through _to_cc3d_units unchanged.
        """
        params_file.parent.mkdir(parents=True, exist_ok=True)

        schema = self.ports_schema()

        # Layer 1: the full variable set already present in the canonical
        # Parameters.py copied into the temp project (the steppable's namespace).
        base_params = self._read_existing_parameters(params_file)

        # Layers 2 + 3: schema defaults, overridden by any user-supplied values.
        schema_defaults = {param: info['_default'] for param, info in schema['inputs'].items()}
        final_params = {**base_params, **schema_defaults, **sim_params}

        with open(params_file, 'w') as f:
            f.write("# Parameters for vCornea simulation\n")
            f.write("# Generated by Vivarium wrapper (canonical base + schema/user\n")
            f.write("# overrides; time parameters converted to MCS).\n\n")
            for param_name, param_value in final_params.items():
                cc3d_value = self._to_cc3d_units(param_name, param_value, schema)
                f.write(f"{param_name}={repr(cc3d_value)}\n")

    def _run_cc3d_simulation(self, project_path, output_dir):
        """
        Launches the CC3D simulation as a separate process using Popen.
        Redirects stdout and stderr to log files in the replicate's output directory.
        """
        cc3d_file = project_path / "vCornea_v2.cc3d"

        import os
        import sys
        import importlib.util

        # Pass cc3d_file by NAME ONLY (not full path), with cwd set to its
        # parent directory (see Popen below). Any space in the path (e.g.
        # "Test Runs/...") could otherwise be split into separate args,
        # leaving cc3d.run_script with a truncated -i value that resolves to
        # nothing — CC3D then exits in ~2 seconds with no output and no error.

        # Preferred path: the wrapper already runs inside a Python env that
        # has CompuCell3D — this is the documented single-env "vc" install,
        # and it is also how the angiogenesis model runs. In that case launch
        # CC3D with the SAME interpreter (sys.executable). This removes two
        # fragile couplings that previously caused silent "exit 0, no output"
        # failures:
        #   1. `conda` no longer has to be resolvable on PATH in the subprocess.
        #   2. The env no longer has to be *named* exactly 'vc' (or match
        #      cc3d_conda_env_name) — we use whatever interpreter is running.
        #
        # Fallback (advanced two-env setups, where the GUI env and the CC3D
        # env are separate): if cc3d isn't importable in the current
        # interpreter, shell out via `conda run -n <env>` into the env that
        # does have it. --no-capture-output forwards CC3D's stdout/stderr to
        # our log files in real time; without it, `conda run` buffers
        # everything and discards subprocess output on failure, leaving only
        # the uninformative "ERROR conda.cli.main_run: ... failed" line.
        cc3d_available_here = importlib.util.find_spec('cc3d') is not None

        # Pass the output directory explicitly with -o. CompuCell3D 4.7.0
        # copies the simulation files into its output directory during startup
        # (sim_runner.run_cc3d_project), BEFORE any steppable runs — and it
        # refuses if that directory is the simulation folder or inside it.
        # Without -o, CC3D defaults the output dir from the .cc3d location and
        # the copy aborts with "Output directory cannot be the simulation
        # folder or inside it", so the run dies on startup with exit code 1
        # and no cell_count_*.csv. The in-steppable pg.set_output_dir() we
        # inject runs too late to prevent this. Giving -o up front (an
        # absolute path OUTSIDE the temp project) makes the startup copy land
        # in the replicate dir and matches where the steppable redirect points.
        cc3d_run_args = [
            '-m', 'cc3d.run_script',
            '-i', cc3d_file.name,
            '-o', str(Path(output_dir).resolve()),
        ]

        if cc3d_available_here:
            command = [sys.executable, *cc3d_run_args]
        else:
            conda_env = self.parameters['cc3d_conda_env_name']
            conda_exe = self.parameters.get('conda_executable_path', 'conda')  # Use .get for safety
            command = [
                conda_exe, 'run', '--no-capture-output', '-n', conda_env,
                'python', *cc3d_run_args,
            ]

        print(f"VCorneaProcess: Launching command: {' '.join(command)}")

        # ---- Create log files for stdout and stderr for this specific replicate ----
        stdout_log_path = output_dir / "stdout.log"
        stderr_log_path = output_dir / "stderr.log"

        try:
            # Open the log files
            stdout_log = open(stdout_log_path, 'w')
            stderr_log = open(stderr_log_path, 'w')

            # ---- Use Popen to run the command in the background ----
            process = subprocess.Popen(
                command,
                cwd=os.fspath(project_path),
                stdout=stdout_log,
                stderr=stderr_log,
                text=True
            )
            
            # Return the process handle and the log file objects
            return process, stdout_log, stderr_log
            
        except Exception as e:
            print(f"VCorneaProcess: Error trying to launch CC3D: {e}")
            # Ensure files are closed if Popen fails
            if 'stdout_log' in locals() and not stdout_log.closed:
                stdout_log.close()
            if 'stderr_log' in locals() and not stderr_log.closed:
                stderr_log.close()
            return None, None, None  
    
    def _collect_output_files(self, temp_project, output_dir, sim_params):
        """
        Collect any output files left in the temp CC3D project copy and move
        them to the run output directory.

        Most outputs are written DIRECTLY to `output_dir` already, because
        `_redirect_outputs_in_copy` rewrites `pg.set_output_dir()` and
        `current_script_directory` in the steppables before CC3D launches.
        We only need to scan the temp Simulation/ folder for any stragglers
        that the redirect missed (e.g. files written via hardcoded paths).
        Previously this method ALSO searched `output_dir` itself, which
        meant every already-redirected file produced a misleading
        "Skipping ... - destination already exists" log line — they were
        being detected and "moved" to their own location, not lost.
        """
        import glob
        from collections import defaultdict

        # Only search the temp project's Simulation/ dir. The output_dir is
        # the destination; scanning it would just re-find files we already
        # have and produce confusing "Skipping" noise.
        temp_simulation_dir = temp_project / "Simulation"

        processed_files = set()
        files_moved = []
        files_already_in_place = []
        collection_stats = defaultdict(int)

        # CC3D writes filenames stamped with the final MCS, so we must convert
        # SimTime (days) to MCS before constructing the glob patterns.
        sim_time = self._to_cc3d_units('SimTime', sim_params.get('SimTime', 24))
        file_patterns = [
            f"cell_count_{sim_time}.csv",
            f"cell_count_{sim_time + 1}.csv",
            f"thickness_rep*_{sim_time}.parquet",
            f"thickness_rep*_{sim_time + 1}.parquet",
            "surfactant_*.csv",
            "center_bias_*.csv",
            "pressure_*.csv",
            "maboss_states_*.csv",
            "cell_states_*.csv",
            "injury_tracking_*.csv",
            "injury_edge_*.csv",
            "memb_disruption_*.csv",
            "*.png",
            "*.jpg",
        ]

        print(f"Scanning for stragglers in: {temp_simulation_dir}")

        # First pass: pattern-based search of the temp Simulation/ dir only
        for pattern in file_patterns:
            collection_stats[f'pattern_{pattern}'] = 0
            for search_path in (temp_simulation_dir / pattern,
                                temp_simulation_dir / "**" / pattern):
                for file_path in glob.glob(str(search_path), recursive=True):
                    source_file = Path(file_path)
                    if source_file.resolve() in processed_files:
                        continue
                    if not (source_file.exists() and source_file.is_file()):
                        continue
                    dest_file = output_dir / source_file.name
                    if dest_file.exists():
                        # Already written directly to output_dir via redirect.
                        # Nothing to do — informational only.
                        processed_files.add(source_file.resolve())
                        files_already_in_place.append(source_file.name)
                        continue
                    try:
                        shutil.copy2(source_file, dest_file)
                        processed_files.add(source_file.resolve())
                        files_moved.append(source_file.name)
                        collection_stats[f'pattern_{pattern}'] += 1
                        print(f"  Collected straggler: {source_file.name}")
                    except Exception as e:
                        print(f"  Warning: Could not copy {source_file}: {e}")

        # Also enumerate what's already in output_dir for the metadata audit
        # (we did NOT scan it, we just list what's there so the per-run
        # report shows the redirected files alongside any stragglers).
        for f in output_dir.iterdir() if output_dir.exists() else []:
            if f.is_file() and f.suffix.lower() in {'.csv', '.parquet', '.png', '.jpg'}:
                if f.name not in files_moved:
                    files_already_in_place.append(f.name)
        
        # Second pass: Catch any remaining output files we might have missed
        # (but only if they weren't already processed)
        for ext in ['*.csv', '*.parquet', '*.png', '*.jpg']:
            collection_stats[f'catchall_{ext}'] = 0
            found_files = glob.glob(str(temp_simulation_dir / ext))
            
            for file_path in found_files:
                source_file = Path(file_path)
                
                # Skip if already processed
                if source_file.resolve() in processed_files:
                    continue
                    
                # Only collect files that look like simulation outputs
                # (avoid collecting input files or other non-output files)
                if source_file.name.startswith((
                                            'cell_count_', 'thickness_', 'surfactant_',
                                            'pressure_', 'center_bias_', 'maboss_states_',
                                            'cell_states_', 'injury_tracking_', 'injury_edge_',
                                            'memb_disruption_'
                                        )) or \
                source_file.suffix in ['.png', '.jpg']:
                    
                    if source_file.exists() and source_file.is_file():
                        dest_file = output_dir / source_file.name
                        
                        if not dest_file.exists():
                            try:
                                shutil.copy2(source_file, dest_file)
                                processed_files.add(source_file.resolve())
                                files_moved.append(source_file.name)
                                collection_stats[f'catchall_{ext}'] += 1
                                print(f"Collected additional output file: {source_file.name}")
                            except Exception as e:
                                print(f"Warning: Could not move additional file {source_file}: {e}")
        
        # Honest collection summary. With the redirect working, the normal
        # case is len(files_moved) == 0 and len(files_already_in_place) > 0:
        # CC3D wrote outputs directly to the destination, nothing needed
        # moving. The only genuine warning is when BOTH lists are empty —
        # that means CC3D produced no recognized output files at all.
        in_place_unique = sorted(set(files_already_in_place))
        moved_unique = sorted(set(files_moved))
        if in_place_unique or moved_unique:
            print(
                f"Output collection: {len(in_place_unique)} file(s) already in place via redirect, "
                f"{len(moved_unique)} straggler(s) copied from temp"
            )
            if moved_unique:
                for cat, count in collection_stats.items():
                    if count > 0:
                        print(f"  {cat}: {count} file(s)")
        else:
            print("Warning: No recognized output files in either the redirect destination or the temp Simulation/ dir")

        # files_moved is the legacy return value (used by callers for the
        # 'has_real_outputs' gate). Combine with files-already-in-place so
        # downstream checks see the full truth.
        return sorted(set(files_moved + files_already_in_place))

    def _copy_parameters_file(self, temp_project, output_dir):
        """
        Copy the Parameters.py file from the temp simulation directory to the output directory.
        This preserves the exact parameter values used for this run alongside the data.

        Args:
            temp_project: Path to the temporary project directory
            output_dir: Path to the replicate output directory
        """
        params_source = temp_project / "Simulation" / "Parameters.py"
        params_dest = output_dir / "Parameters.py"

        try:
            if params_source.exists():
                shutil.copy2(params_source, params_dest)
                print(f"      -> Copied Parameters.py to {output_dir.name}/")
            else:
                print(f"      -> Warning: Parameters.py not found at {params_source}")
        except Exception as e:
            print(f"      -> Warning: Could not copy Parameters.py: {e}")

    def _get_generated_files_list(self, temp_project, before_files, after_files):
        """
        Determine which files were actually generated by comparing before/after snapshots.
        This provides a more accurate list than just glob searching.
        """
        # Convert to sets for easier comparison
        before_set = set(before_files)
        after_set = set(after_files)
        
        # Files that were created during simulation
        generated_files = after_set - before_set
        
        # Filter to only include likely output files (not temp or log files)
        output_extensions = {'.csv', '.parquet', '.png', '.jpg', '.json'}
        output_prefixes = {
            'cell_count_', 'thickness_', 'surfactant_', 'pressure_', 'center_bias_',
            'maboss_states_', 'cell_states_', 'injury_tracking_', 'injury_edge_',
            'memb_disruption_'
        }
        
        actual_outputs = []
        for file_path in generated_files:
            file_obj = Path(file_path)
            if (file_obj.suffix.lower() in output_extensions and 
                (any(file_obj.name.startswith(prefix) for prefix in output_prefixes) or
                file_obj.suffix in {'.png', '.jpg'})):
                actual_outputs.append(file_obj.name)
        
        return sorted(actual_outputs)

    def _take_directory_snapshot(self, directory):
        """Take a snapshot of all files in a directory for before/after comparison."""
        snapshot = set()
        if directory.exists():
            for file_path in directory.rglob('*'):
                if file_path.is_file():
                    snapshot.add(str(file_path))
        return snapshot
    
    def _parse_simulation_results(self, output_dir, sim_params):
        """Parse the simulation output files from external output directory."""
        # CC3D filenames are stamped with the final MCS, not the schema-layer day value.
        sim_time = self._to_cc3d_units('SimTime', sim_params.get('SimTime', 24))

        # Look for output files in the external directory
        cell_count_files = sorted(output_dir.glob(f"cell_count_{sim_time}.csv"))
        if not cell_count_files:
            cell_count_files = sorted(output_dir.glob(f"cell_count_{sim_time + 1}.csv"))

        thickness_files = sorted(output_dir.glob(f"thickness_rep*_{sim_time}.parquet"))
        if not thickness_files:
            thickness_files = sorted(output_dir.glob(f"thickness_rep*_{sim_time + 1}.parquet"))
        surfactant_files = sorted(output_dir.glob("surfactant_*.csv"))
        center_bias_files = sorted(output_dir.glob("center_bias_*.csv"))
        pressure_files = sorted(output_dir.glob("pressure_*.csv"))
        maboss_states_files = sorted(output_dir.glob("maboss_states_*.csv"))
        cell_states_files = sorted(output_dir.glob("cell_states_*.csv"))
        injury_tracking_files = sorted(output_dir.glob("injury_tracking_*.csv"))
        injury_edge_files = sorted(output_dir.glob("injury_edge_*.csv"))
        memb_disruption_files = sorted(output_dir.glob("memb_disruption_*.csv"))
        image_files = sorted(list(output_dir.glob("*.png")) + list(output_dir.glob("*.jpg")))

        cell_count_file = cell_count_files[0] if cell_count_files else None
        thickness_file = thickness_files[0] if thickness_files else None
        
        results = {
            'simulation_success': True,
            'healing_time': 0.0,
            'cell_counts': {},
            'tissue_thickness': {},
            'output_files': {
                'cell_count': [path.name for path in cell_count_files],
                'thickness': [path.name for path in thickness_files],
                'surfactant': [path.name for path in surfactant_files],
                'center_bias': [path.name for path in center_bias_files],
                'pressure': [path.name for path in pressure_files],
                'maboss_states': [path.name for path in maboss_states_files],
                'cell_states': [path.name for path in cell_states_files],
                'injury_tracking': [path.name for path in injury_tracking_files],
                'injury_edge': [path.name for path in injury_edge_files],
                'memb_disruption': [path.name for path in memb_disruption_files],
                'images': [path.name for path in image_files]
            }
        }

        # Parse cell counts
        if cell_count_file and cell_count_file.exists():
            try:
                cell_counts_df = pd.read_csv(cell_count_file)
                results['cell_counts'] = cell_counts_df.to_dict('records')
                
                # Calculate healing time if injury occurred
                if sim_params.get('IsInjury', False):
                    results['healing_time'] = self._calculate_healing_time(
                        cell_counts_df, sim_params
                    )
                    
            except Exception as e:
                print(f"Warning: Could not parse cell counts: {e}")
        else:
            print("Warning: Cell count file not found")
        
        # Parse thickness data
        if thickness_file and thickness_file.exists():
            try:
                thickness_df = pd.read_parquet(thickness_file)
                results['tissue_thickness'] = thickness_df.to_dict('records')
            except Exception as e:
                print(f"Warning: Could not parse thickness data: {e}")
        else:
            print("Warning: Thickness file not found")
        
        return results

    def _calculate_healing_time(self, cell_counts_df, sim_params):
        """Calculate healing time from cell count data."""
        if cell_counts_df.empty:
            return 0.0
                
        try:          
            # Key fix: Convert injury time from MCS to hours for data comparison
            injury_time_MCS = sim_params.get('InjuryTime', 500)
            injury_time_hours = injury_time_MCS / 10.0  # Convert to hours
            
            print(f"  Injury at {injury_time_MCS} MCS = {injury_time_hours} hours")
            
            # Check data availability
            max_time_hours = cell_counts_df['Time'].max()
            print(f"  Data available until {max_time_hours} hours")
            
            if max_time_hours <= injury_time_hours:
                print(f"  ERROR: No post-injury data (injury at {injury_time_hours}h, data until {max_time_hours}h)")
                return 0.0
            
            # Get pre-injury baseline using HOURS
            pre_injury = cell_counts_df[cell_counts_df['Time'] < injury_time_hours]
            if len(pre_injury) < 3:
                print(f"  Warning: Only {len(pre_injury)} pre-injury timepoints")
                return 0.0
            
            # Use last 20% for baseline
            baseline_window = max(3, len(pre_injury) // 5)
            baseline_data = pre_injury.tail(baseline_window)
            
            cell_types = ['Superficial', 'Wing', 'Basal', 'Stem']
            baseline_total = baseline_data[cell_types].sum(axis=1).mean()
            print(f"  Baseline: {baseline_total:.0f} cells (from {len(baseline_data)} timepoints)")
            
            # Get post-injury data using HOURS
            post_injury = cell_counts_df[cell_counts_df['Time'] > injury_time_hours]
            if post_injury.empty:
                print("  ERROR: No post-injury data found")
                return 0.0
            
            # Find minimum (maximum damage)
            post_totals = post_injury[cell_types].sum(axis=1)
            min_cells = post_totals.min()
            min_time_hours = post_injury.iloc[post_totals.argmin()]['Time']
            
            damage_percent = (baseline_total - min_cells) / baseline_total * 100
            print(f"  Max damage: {damage_percent:.1f}% at {min_time_hours} hours post-injury")
            
            # Find recovery (85% of baseline for short simulations)
            recovery_threshold = 0.85 * baseline_total
            
            for idx, row in post_injury.iterrows():
                current_total = row[cell_types].sum()
                if current_total >= recovery_threshold:
                    healing_time_hours = row['Time'] - injury_time_hours
                    healing_time_MCS = healing_time_hours * 10  # Convert back to MCS
                    print(f"  Healing detected: {healing_time_hours} hours = {healing_time_MCS} MCS")
                    return healing_time_MCS  # Return in MCS units
            
            # No full recovery
            final_recovery = (post_totals.iloc[-1] / baseline_total) * 100
            print(f"  No full recovery. Final: {final_recovery:.1f}% of baseline")
            return 0.0
            
        except Exception as e:
            print(f"  Error in healing calculation: {e}")
            import traceback
            traceback.print_exc()
            return 0.0
        
            # injury_time = sim_params.get('InjuryTime', 500)
            
            # # Simple healing metric: when total cell count returns to 95% of pre-injury
            # pre_injury_data = cell_counts_df[cell_counts_df['Time'] < injury_time]
            # if pre_injury_data.empty:
            #     return 0.0
            
            # # Calculate pre-injury baseline (last few time points before injury)
            # baseline_data = pre_injury_data.tail(10)
            # baseline_total = baseline_data[['Superficial', 'Wing', 'Basal', 'Stem']].sum(axis=1).mean()
            
            # # Find when post-injury levels return to 95% of baseline
            # post_injury_data = cell_counts_df[cell_counts_df['Time'] > injury_time]
        #     injury_time_MCS = sim_params.get('InjuryTime', 500)
        #     injury_time_hours = injury_time_MCS / 10.0  # THE KEY FIX!
            
        #     # Now use injury_time_hours when filtering the dataframe
        #     pre_injury = cell_counts_df[cell_counts_df['Time'] < injury_time_hours]
        #     post_injury = cell_counts_df[cell_counts_df['Time'] > injury_time_hours]

            
        #     for idx, row in post_injury_data.iterrows():
        #         current_total = row[['Superficial', 'Wing', 'Basal', 'Stem']].sum()
        #         if current_total >= 0.95 * baseline_total:
        #             healing_time = row['Time'] - injury_time
        #             return max(0.0, healing_time)
            
        #     return 0.0  # No healing detected
            
        # except Exception as e:
        #     print(f"Warning: Could not calculate healing time: {e}")
        #     return 0.0
