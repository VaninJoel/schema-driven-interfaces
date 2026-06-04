import subprocess
import os
import pandas as pd
import tempfile
import shutil
import json
import glob
import uuid
from pathlib import Path
from vivarium.core.process import Process

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
        'cc3d_conda_env_name': 'v_cornea',  # Name of conda environment with CC3D 'v_cornea'
        'python_executable': 'python',  # Usually just 'python' when using conda
        
        'output_base_dir': None, #Path.cwd()/ "simulation_results",  # Permanent location        
        'run_name': None,  # Custom name for this run; if None, generates descriptive name
        'max_params_in_name': 3,  # Max number of changed parameters to include in auto-generated names
        'replicates': 1,  # Number of times to run the simulation with the same parameters
        'run_id': 0,
    }

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
        """Define inputs and outputs for the vCornea wrapper."""
        return {
            'inputs': {
                # --- STEM Cell Parameters ---
                # 'InitSTEM_LambdaSurface': {
                #     '_default': 2.0,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'InitSTEM_LambdaSurface': {
                    '_default': 2.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Stem Surface Regulation',
                    '_description': 'How strongly a stem cell regulates its surface area towards a desired size',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Stem Cells',
                    # '_units': 'force/area',
                    '_biological_range': (0.1, 10.0),
                    '_expert_level': 'advanced',
                    '_hidden_basic': True,
                },
                # 'InitSTEM_TargetSurface': {
                #     '_default': 18.0,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'InitSTEM_TargetSurface': {
                    '_default': 18.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Stem Target Surface Area',
                    '_description': 'The ideal surface area each stem cell tries to maintain',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Stem Cells',
                    # '_units': 'pixels²',
                    '_biological_range': (10.0, 30.0),
                    '_expert_level': 'intermediate',
                },
                # 'InitSTEM_LambdaVolume': {
                #     '_default': 2.0,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'InitSTEM_LambdaVolume': {
                    '_default': 2.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Stem Volume Regulation',
                    '_description': 'How strongly a stem cell regulates its volume towards a desired size',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Stem Cells',
                    # '_units': 'force/volume',
                    '_biological_range': (0.1, 10.0),
                    '_expert_level': 'advanced',
                    '_hidden_basic': True,
                },
                # 'InitSTEM_TargetVolume': {
                #     '_default': 25.0,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'InitSTEM_TargetVolume': {
                    '_default': 25.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Stem Target Volume',
                    '_description': 'The ideal volume each stem cell tries to maintain',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Stem Cells',
                    # '_units': 'pixels²',
                    '_biological_range': (15.0, 40.0),
                    '_expert_level': 'intermediate',
                },
                # 'DensitySTEM_HalfMaxValue': {
                #     '_default': 125,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'DensitySTEM_HalfMaxValue': {
                    '_default': 125,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Stem Density Sensitivity',
                    '_description': 'Cell density at which stem cells achieve half their maximum growth response',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Stem Cells',
                    # '_units': 'pressure units',
                    '_biological_range': (50, 300),
                    '_expert_level': 'intermediate',
                },
                # 'EGF_STEM_HalfMaxValue': {
                #     '_default': 3.5,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'EGF_STEM_HalfMaxValue': {
                    '_default': 3.5,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Stem EGF Sensitivity',
                    '_description': 'EGF concentration at which stem cells achieve half their maximum growth response',
                    '_category': 'Growth Factors',
                    '_subcategory': 'EGF Response',
                    # '_units': 'ng/mL equivalent',
                    '_biological_range': (1.0, 10.0),
                    '_expert_level': 'basic',
                    '_related_parameters': ['EGF_BASAL_HalfMaxValue'],
                },
                # 'STEM_beta_EGF': {
                #     '_default': 1,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'STEM_beta_EGF': {
                    '_default': 1,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Stem EGF Dependence',
                    '_description': 'How much stem cell behavior depends on EGF levels (0=independent, 1=fully dependent)',
                    '_category': 'Growth Factors',
                    '_subcategory': 'EGF Response',
                    # '_units': 'fraction (0-1)',
                    '_biological_range': (0.0, 1.0),
                    '_expert_level': 'intermediate',
                },
                # 'InitSTEM_LambdaChemo': {
                #     '_default': 100.0,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'InitSTEM_LambdaChemo': {
                    '_default': 100.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Stem Movement Response',
                    '_description': 'How strongly stem cells move toward areas with guidance signals',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Stem Cells',
                    # '_units': 'force/gradient',
                    '_biological_range': (10.0, 1000.0),
                    '_expert_level': 'advanced',
                },

                # --- BASAL Cell Parameters ---
                # 'InitBASAL_LambdaSurface': {
                #     '_default': 2.0,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'InitBASAL_LambdaSurface': {
                    '_default': 2.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Basal Surface Regulation',
                    '_description': 'How strongly a basal cell regulates its surface area towards a desired size',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Basal Cells',
                    # '_units': 'force/area',
                    '_biological_range': (0.1, 10.0),
                    '_expert_level': 'advanced',
                    '_hidden_basic': True,
                },
                # 'InitBASAL_TargetSurface': {
                #     '_default': 20.0,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'InitBASAL_TargetSurface': {
                    '_default': 20.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Basal Target Surface Area',
                    '_description': 'The ideal surface area each basal cell tries to maintain',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Basal Cells',
                    # '_units': 'pixels²',
                    '_biological_range': (10.0, 35.0),
                    '_expert_level': 'intermediate',
                },
                # 'InitBASAL_LambdaVolume': {
                #     '_default': 2.0,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'InitBASAL_LambdaVolume': {
                    '_default': 2.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Basal Volume Regulation',
                    '_description': 'How strongly a basal cell regulates its volume towards a desired size',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Basal Cells',
                    # '_units': 'force/volume',
                    '_biological_range': (0.1, 10.0),
                    '_expert_level': 'advanced',
                    '_hidden_basic': True,
                },
                # 'InitBASAL_TargetVolume': {
                #     '_default': 25.0,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'InitBASAL_TargetVolume': {
                    '_default': 25.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Basal Target Volume',
                    '_description': 'The ideal volume each basal cell tries to maintain',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Basal Cells',
                    # '_units': 'pixels³',
                    '_biological_range': (15.0, 40.0),
                    '_expert_level': 'intermediate',
                },
                # 'InitBASAL_LambdaChemo': {
                #     '_default': 1000.0,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'InitBASAL_LambdaChemo': {
                    '_default': 1000.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Basal Movement Response',
                    '_description': 'How strongly basal cells move toward areas with guidance signals',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Basal Cells',
                    # '_units': 'force/gradient',
                    '_biological_range': (100.0, 5000.0),
                    '_expert_level': 'advanced',
                },
                # 'InitBASAL_Division': {
                #     '_default': 20000.0,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'InitBASAL_Division': {
                    '_default': 20000.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Basal Division Capacity',
                    '_description': 'Maximum number of times a basal cell can divide before exhaustion',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Basal Cells',
                    # '_units': 'division cycles',
                    '_biological_range': (5000.0, 50000.0),
                    '_expert_level': 'advanced',
                },
                # 'DensityBASAL_HalfMaxValue': {
                #     '_default': 125,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'DensityBASAL_HalfMaxValue': {
                    '_default': 125,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Basal Density Sensitivity',
                    '_description': 'Cell density at which basal cells achieve half their maximum growth response',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Basal Cells',
                    # '_units': 'pressure units',
                    '_biological_range': (50, 300),
                    '_expert_level': 'intermediate',
                },
                # 'EGF_BASAL_HalfMaxValue': {
                #     '_default': 7.0,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'EGF_BASAL_HalfMaxValue': {
                    '_default': 7.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Basal EGF Sensitivity',
                    '_description': 'EGF concentration at which basal cells achieve half their maximum growth response',
                    '_category': 'Growth Factors',
                    '_subcategory': 'EGF Response',
                    # '_units': 'ng/mL equivalent',
                    '_biological_range': (3.0, 15.0),
                    '_expert_level': 'basic',
                    '_related_parameters': ['EGF_STEM_HalfMaxValue', 'EGF_SecreteAmount',
                                             'EGF_FieldUptakeBASAL', 'EGF_GlobalDecay', 'EGF_FieldUptakeSTEM',
                                             'EGF_FieldUptakeSuper', 'EGF_FieldUptakeWing', 'EGF_SUPERDiffCoef'],
                },
                # 'BASAL_beta_EGF': {
                #     '_default': 1,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'BASAL_beta_EGF': {
                    '_default': 1,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Basal EGF Dependence',
                    '_description': 'How much basal cell behavior depends on EGF levels',
                    '_category': 'Growth Factors',
                    '_subcategory': 'EGF Response',
                    # '_units': 'fraction (0-1)',
                    '_biological_range': (0.0, 1.0),
                    '_expert_level': 'intermediate',
                },

                # --- WING Cell Parameters ---
                # 'InitWING_LambdaSurface': {
                #     '_default': 5.0,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'InitWING_LambdaSurface': {
                    '_default': 5.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Wing Surface Regulation',
                    '_description': 'How strongly a wing cell regulates its surface area towards a desired size',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Wing Cells',
                    # '_units': 'force/area',
                    '_biological_range': (1.0, 20.0),
                    '_expert_level': 'advanced',
                    '_hidden_basic': True,
                },
                # 'InitWING_TargetSurface': {
                #     '_default': 25,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'InitWING_TargetSurface': {
                    '_default': 25,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Wing Target Surface Area',
                    '_description': 'The ideal surface area each wing cell tries to maintain',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Wing Cells',
                    # '_units': 'pixels²',
                    '_biological_range': (15.0, 40.0),
                    '_expert_level': 'intermediate',
                },
                # 'InitWING_LambdaVolume': {
                #     '_default': 2.0,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'InitWING_LambdaVolume': {
                    '_default': 2.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Wing Volume Regulation',
                    '_description': 'How strongly a wing cell regulates its volume towards a desired size',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Wing Cells',
                    # '_units': 'force/volume',
                    '_biological_range': (0.1, 10.0),
                    '_expert_level': 'advanced',
                    '_hidden_basic': True,
                },
                # 'InitWING_TargetVolume': {
                #     '_default': 25.0,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'InitWING_TargetVolume': {
                    '_default': 25.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Wing Target Volume',
                    '_description': 'The ideal volume each wing cell tries to maintain',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Wing Cells',
                    # '_units': 'pixels²',
                    '_biological_range': (15.0, 40.0),
                    '_expert_level': 'intermediate',
                },
                # 'InitWING_EGFLambdaChemo': {
                #     '_default': 20.0,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'InitWING_EGFLambdaChemo': {
                    '_default': 20.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Wing EGF Movement Response',
                    '_description': 'How strongly wing cells move toward regions with higher EGF concentration',
                    '_category': 'Growth Factors',
                    '_subcategory': 'EGF Response',
                    # '_units': 'force/gradient',
                    '_biological_range': (5.0, 100.0),
                    '_expert_level': 'intermediate',
                },
                # --- SUPERFICIAL Cell Parameters ---
                # 'InitSUPER_LambdaSurface': {
                #     '_default': 5.0,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'InitSUPER_LambdaSurface': {
                    '_default': 5.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Superficial Surface Regulation',
                    '_description': 'How strongly a superficial cell regulates its surface area towards a desired size',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Superficial Cells',
                    # '_units': 'force/area',
                    '_biological_range': (1.0, 20.0),
                    '_expert_level': 'advanced',
                    '_hidden_basic': True,
                },
                # 'InitSUPER_TargetSurface': {
                #     '_default': 25.0,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'InitSUPER_TargetSurface': {
                    '_default': 25.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Superficial Target Surface Area',
                    '_description': 'The ideal surface area each superficial cell tries to maintain',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Superficial Cells',
                    # '_units': 'pixels²',
                    '_biological_range': (15.0, 40.0),
                    '_expert_level': 'intermediate',
                },
                # 'InitSUPER_LambdaVolume': {
                #     '_default': 5.0,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'InitSUPER_LambdaVolume': {
                    '_default': 5.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Superficial Volume Regulation',
                    '_description': 'How strongly a superficial cell regulates its volume towards a desired size',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Superficial Cells',
                    # '_units': 'force/volume',
                    '_biological_range': (1.0, 20.0),
                    '_expert_level': 'advanced',
                    '_hidden_basic': True,
                },
                # 'InitSUPER_TargetVolume': {
                #     '_default': 25.0,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'InitSUPER_TargetVolume': {
                    '_default': 25.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Superficial Target Volume',
                    '_description': 'The ideal volume each superficial cell tries to maintain',
                    '_category': 'Cell Properties',
                    '_subcategory': 'Superficial Cells',
                    # '_units': 'pixels³',
                    '_biological_range': (15.0, 40.0),
                    '_expert_level': 'intermediate',
                },
                # 'EGF_SUPERDiffCoef': {
                #     '_default': 20.0,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'EGF_SUPERDiffCoef': {
                    '_default': 20.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Superficial EGF Diffusion',
                    '_description': 'How quickly EGF diffuses (spreads) through superficial cells',
                    '_category': 'Growth Factors',
                    '_subcategory': 'EGF Dynamics',
                    # '_units': 'diffusion rate',
                    '_biological_range': (5.0, 100.0),
                    '_expert_level': 'intermediate',
                },
                # --- Movement Bias Field Parameters ---
                # 'MovementBiasScreteAmount': {
                #     '_default': 1,  # Corrected from 5.0 to match vCornea default
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'MovementBiasScreteAmount': {
                    '_default': 1,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Guidance Signal Strength',
                    '_description': 'Amount of guidance signal secreted by boundary structures to direct cell movement',
                    '_category': 'Tissue Guidance',
                    '_subcategory': 'Movement Signals',
                    # '_units': 'signal strength',
                    '_biological_range': (0.1, 10.0),
                    '_expert_level': 'intermediate',
                },
                # 'MovementBiasUptake': {
                #     '_default': 1.0,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'MovementBiasUptake': {
                    '_default': 1.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Guidance Signal Uptake',
                    '_description': 'How quickly basal cells absorb guidance signals from their environment',
                    '_category': 'Tissue Guidance',
                    '_subcategory': 'Movement Signals',
                    # '_units': 'uptake rate',
                    '_biological_range': (0.1, 10.0),
                    '_expert_level': 'advanced',
                },
                # --- EGF Field Parameters ---
                # 'EGF_ScreteAmount': {
                #     '_default': 1.0,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'EGF_ScreteAmount': {
                    '_default': 1.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'EGF Production Rate',
                    '_description': 'Amount of EGF continuously produced (e.g., from tear fluid)',
                    '_category': 'Growth Factors',
                    '_subcategory': 'EGF Production',
                    # '_units': 'ng/mL/hour equivalent',
                    '_biological_range': (0.1, 10.0),
                    '_expert_level': 'intermediate',
                },
                # 'EGF_FieldUptakeBASAL': {
                #     '_default': 0.0,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'EGF_FieldUptakeBASAL': {
                    '_default': 0.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Basal EGF Consumption',
                    '_description': 'How quickly basal cells consume EGF from their surroundings',
                    '_category': 'Growth Factors',
                    '_subcategory': 'EGF Consumption',
                    # '_units': 'consumption rate',
                    '_biological_range': (0.0, 5.0),
                    '_expert_level': 'advanced',
                },
                # 'EGF_FieldUptakeSTEM': {
                #     '_default': 0.0,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'EGF_FieldUptakeSTEM': {
                    '_default': 0.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Stem EGF Consumption',
                    '_description': 'How quickly stem cells consume EGF from their surroundings',
                    '_category': 'Growth Factors',
                    '_subcategory': 'EGF Consumption',
                    # '_units': 'consumption rate',
                    '_biological_range': (0.0, 5.0),
                    '_expert_level': 'advanced',
                },
                # 'EGF_FieldUptakeSuper': {
                #     '_default': 0.0,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'EGF_FieldUptakeSuper': {
                    '_default': 0.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Superficial EGF Consumption',
                    '_description': 'How quickly superficial cells consume EGF',
                    '_category': 'Growth Factors',
                    '_subcategory': 'EGF Consumption',
                    # '_units': 'consumption rate',
                    '_biological_range': (0.0, 5.0),
                    '_expert_level': 'advanced',
                },
                # 'EGF_FieldUptakeWing': {
                #     '_default': 0.0,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'EGF_FieldUptakeWing': {
                    '_default': 0.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Wing EGF Consumption',
                    '_description': 'How quickly wing cells consume EGF',
                    '_category': 'Growth Factors',
                    '_subcategory': 'EGF Consumption',
                    # '_units': 'consumption rate',
                    '_biological_range': (0.0, 5.0),
                    '_expert_level': 'advanced',
                },
                # 'EGF_GlobalDecay': {
                #     '_default': 0.5,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'EGF_GlobalDecay': {
                    '_default': 0.5,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'EGF Natural Decay',
                    '_description': 'Rate at which EGF naturally breaks down over time',
                    '_category': 'Growth Factors',
                    '_subcategory': 'EGF Dynamics',
                    # '_units': '1/hour equivalent',
                    '_biological_range': (0.1, 2.0),
                    '_expert_level': 'intermediate',
                },

                # --- Link Parameters (SUPER-WALL) ---
                # 'LINKWALL_lambda_distance': {
                #     '_default': 50,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'LINKWALL_lambda_distance': {
                    '_default': 50,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Boundary Attachment Strength',
                    '_description': 'How strongly superficial cells try to maintain distance from tissue boundary',
                    '_category': 'Tissue Mechanics',
                    '_subcategory': 'Boundary Interactions',
                    # '_units': 'force constant',
                    '_biological_range': (10, 200),
                    '_expert_level': 'advanced',
                },
                # 'LINKWALL_target_distance': {
                #     '_default': 3,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'LINKWALL_target_distance': {
                    '_default': 3,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Boundary Target Distance',
                    '_description': 'Desired distance between superficial cells and tissue boundary',
                    '_category': 'Tissue Mechanics',
                    '_subcategory': 'Boundary Interactions',
                    # '_units': 'pixels',
                    '_biological_range': (1, 10),
                    '_expert_level': 'advanced',
                },
                # 'LINKWALL_max_distance': {
                #     '_default': 1000,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'LINKWALL_max_distance': {
                    '_default': 1000,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Boundary Max Interaction',
                    '_description': 'Maximum distance at which boundary forces apply to cells',
                    '_category': 'Tissue Mechanics',
                    '_subcategory': 'Boundary Interactions',
                    # '_units': 'pixels',
                    '_biological_range': (100, 2000),
                    '_expert_level': 'advanced',
                },

                # --- Link Parameters (SUPER-SUPER) ---
                # 'LINKSUPER_lambda_distance': {
                #     '_default': 50,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'LINKSUPER_lambda_distance': {
                    '_default': 50,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Cell-Cell Adhesion Strength',
                    '_description': 'How strongly superficial cells stick together',
                    '_category': 'Tissue Mechanics',
                    '_subcategory': 'Cell Adhesion',
                    # '_units': 'force constant',
                    '_biological_range': (10, 200),
                    '_expert_level': 'intermediate',
                },
                # 'LINKSUPER_target_distance': {
                #     '_default': 3,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'LINKSUPER_target_distance': {
                    '_default': 3,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Cell-Cell Target Distance',
                    '_description': 'Preferred distance between adjacent superficial cells',
                    '_category': 'Tissue Mechanics',
                    '_subcategory': 'Cell Adhesion',
                    # '_units': 'pixels',
                    '_biological_range': (1, 10),
                    '_expert_level': 'intermediate',
                },
                # 'LINKSUPER_max_distance': {
                #     '_default': 1000,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'LINKSUPER_max_distance': {
                    '_default': 1000,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Cell-Cell Max Interaction',
                    '_description': 'Maximum distance at which cells can interact with each other',
                    '_category': 'Tissue Mechanics',
                    '_subcategory': 'Cell Adhesion',
                    # '_units': 'pixels',
                    '_biological_range': (100, 2000),
                    '_expert_level': 'advanced',
                },
                # 'AutoAdjustLinks': {
                #     '_default': True,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'AutoAdjustLinks': {
                    '_default': True,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Dynamic Tissue Tension',
                    '_description': 'Allow tissue tension to adjust automatically to maintain stability',
                    '_category': 'Tissue Mechanics',
                    '_subcategory': 'Adaptive Behavior',
                    # '_units': 'boolean',
                    '_expert_level': 'intermediate',
                },

                # --- Injury Parameters ---
                # 'IsInjury': {
                #     '_default': True,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'IsInjury': {
                    '_default': True,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Include Injury Event',
                    '_description': 'Whether to include a tissue injury in the simulation',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Basic Setup',
                    # '_units': 'boolean',
                    '_expert_level': 'basic',
                    '_affects_output': ['healing_time', 'cell_recovery_pattern'],
                },
                # 'InjuryType': {
                #     '_default': False,  # False = ablation, True = chemical
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'InjuryType': {
                    '_default': False,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Injury Type',
                    '_description': 'Type of tissue injury to simulate',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Basic Setup',
                    # '_units': 'categorical',
                    '_expert_level': 'basic',
                    '_value_mapping': {True: 'Mechanical Ablation', False: 'Chemical Exposure'},
                    '_depends_on': ['IsInjury'],
                    '_conditional_display': lambda params: params.get('IsInjury', False),
                },
                # 'InjuryTime': {
                #     '_default': 500,  # match vCornea default
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'InjuryTime': {
                    '_default': 500,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Injury Timing',
                    '_description': 'When during simulation the injury occurs (allows tissue stabilization first)',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Timing',
                    # '_units': 'hours',
                    '_conversion_factor': 10,  # MCS to hours
                    '_biological_range': (24, 720),  # 1 day to 30 days
                    '_expert_level': 'intermediate',
                    '_depends_on': ['IsInjury'],
                },

                # --- Ablation Injury Parameters ---
                # 'InjuryX_Center': {
                #     '_default': 100,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'InjuryX_Center': {
                    '_default': 100,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Injury X Position',
                    '_description': 'Horizontal position of the injury center on the tissue',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Mechanical Injury',
                    # '_units': 'pixels from left edge',
                    '_biological_range': (20, 180),
                    '_expert_level': 'intermediate',
                    '_depends_on': ['IsInjury'],
                    '_conditional_display': lambda params: params.get('IsInjury', False) and params.get('InjuryType', False),
                },
                # 'InjuryY_Center': {
                #     '_default': 75,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'InjuryY_Center': {
                    '_default': 75,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Injury Y Position',
                    '_description': 'Vertical position of the injury center on the tissue',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Mechanical Injury',
                    # '_units': 'pixels from bottom',
                    '_biological_range': (10, 140),
                    '_expert_level': 'intermediate',
                    '_depends_on': ['IsInjury'],
                    '_conditional_display': lambda params: params.get('IsInjury', False) and not params.get('InjuryType', False),
                },
                # 'InjuryRadius': {
                #     '_default': 45,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'InjuryRadius': {
                    '_default': 45,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Injury Size',
                    '_description': 'Radius of the circular injury area',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Mechanical Injury',
                    # '_units': 'pixels',
                    '_biological_range': (10, 80),
                    '_expert_level': 'basic',
                    '_depends_on': ['IsInjury'],
                    '_conditional_display': lambda params: params.get('IsInjury', False) and not params.get('InjuryType', False),
                },

                # --- Chemical Injury Parameters ---
                # 'SLS_Injury': {
                #     '_default': True,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'SLS_Injury': {
                    '_default': True,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Enable Chemical Damage',
                    '_description': 'Whether chemical exposure causes cell death',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Chemical Injury',
                    # '_units': 'boolean',
                    '_expert_level': 'intermediate',
                    '_depends_on': ['IsInjury', 'InjuryType'],
                    '_conditional_display': lambda params: params.get('IsInjury', False) and not params.get('InjuryType', False),
                },
                # 'SLS_X_Center': {
                #     '_default': 100,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'SLS_X_Center': {
                    '_default': 100,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Chemical X Position',
                    '_description': 'Horizontal position where chemical is applied',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Chemical Injury',
                    # '_units': 'pixels from left edge',
                    '_biological_range': (20, 180),
                    '_expert_level': 'intermediate',
                    '_depends_on': ['IsInjury', 'InjuryType'],
                    '_conditional_display': lambda params: params.get('IsInjury', False) and params.get('InjuryType', False),
                },
                # 'SLS_Y_Center': {
                #     '_default': 65,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'SLS_Y_Center': {
                    '_default': 65,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Chemical Y Position',
                    '_description': 'Vertical position where chemical is applied',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Chemical Injury',
                    # '_units': 'pixels from bottom',
                    '_biological_range': (10, 140),
                    '_expert_level': 'intermediate',
                    '_depends_on': ['IsInjury', 'InjuryType'],
                    '_conditional_display': lambda params: params.get('IsInjury', False) and params.get('InjuryType', False),
                },
                # 'SLS_Concentration': {
                #     '_default': 750.0,  # Corrected to match vCornea default
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'SLS_Concentration': {
                    '_default': 750.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Chemical Concentration',
                    '_description': 'Concentration of chemical irritant (higher = more severe damage)',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Chemical Injury',
                    # '_units': 'µg/mL equivalent',
                    '_biological_range': (100.0, 5000.0),
                    '_expert_level': 'basic',
                    '_severity_mapping': {
                        (100, 500): 'Mild',
                        (500, 1500): 'Moderate', 
                        (1500, 5000): 'Severe'
                    },
                    '_depends_on': ['IsInjury', 'InjuryType'],
                    '_conditional_display': lambda params: params.get('IsInjury', False) and not params.get('InjuryType', False),
                },
                # 'SLS_Gaussian_pulse': {
                #     '_default': True,  # Corrected to match vCornea default
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'SLS_Gaussian_pulse': {
                    '_default': True,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Chemical Distribution Pattern',
                    '_description': 'How chemical spreads: concentrated droplet vs uniform coating',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Chemical Injury',
                    # '_units': 'categorical',
                    '_expert_level': 'intermediate',
                    '_value_mapping': {True: 'Concentrated Droplet', False: 'Uniform Coating'},
                    '_depends_on': ['IsInjury', 'InjuryType'],
                    '_conditional_display': lambda params: params.get('IsInjury', False) and params.get('InjuryType', False),
                },
                # 'SLS_STEMDiffCoef': {
                #     '_default': 5.0,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'SLS_STEMDiffCoef': {
                    '_default': 5.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Chemical Spread in Stem Cells',
                    '_description': 'How quickly chemical spreads through stem cells',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Chemical Diffusion',
                    # '_units': 'diffusion rate',
                    '_biological_range': (1.0, 20.0),
                    '_expert_level': 'advanced',
                    '_depends_on': ['SLS_Injury'],
                },
                # 'SLS_BASALDiffCoef': {
                #     '_default': 5.0,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'SLS_BASALDiffCoef': {
                    '_default': 5.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Chemical Spread in Basal Cells',
                    '_description': 'How quickly chemical spreads through basal cells',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Chemical Diffusion',
                    # '_units': 'diffusion rate',
                    '_biological_range': (1.0, 20.0),
                    '_expert_level': 'advanced',
                    '_depends_on': ['SLS_Injury'],
                },
                # 'SLS_WINGDiffCoef': {
                #     '_default': 5.0,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'SLS_WINGDiffCoef': {
                    '_default': 5.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Chemical Spread in Wing Cells',
                    '_description': 'How quickly chemical spreads through wing cells',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Chemical Diffusion',
                    # '_units': 'diffusion rate',
                    '_biological_range': (1.0, 20.0),
                    '_expert_level': 'advanced',
                    '_depends_on': ['SLS_Injury'],
                },
                # 'SLS_SUPERDiffCoef': {
                #     '_default': 5.0,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'SLS_SUPERDiffCoef': {
                    '_default': 5.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Chemical Spread in Superficial Cells',
                    '_description': 'How quickly chemical spreads through superficial cells',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Chemical Diffusion',
                    # '_units': 'diffusion rate',
                    '_biological_range': (1.0, 20.0),
                    '_expert_level': 'advanced',
                    '_depends_on': ['SLS_Injury'],
                },
                # 'SLS_MEMBDiffCoef': {
                #     '_default': 5.0,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'SLS_MEMBDiffCoef': {
                    '_default': 5.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Chemical Spread in Membrane',
                    '_description': 'How quickly chemical spreads through boundary membrane',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Chemical Diffusion',
                    # '_units': 'diffusion rate',
                    '_biological_range': (1.0, 20.0),
                    '_expert_level': 'advanced',
                    '_depends_on': ['SLS_Injury'],
                },
                # 'SLS_LIMBDiffCoef': {
                #     '_default': 5.0,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'SLS_LIMBDiffCoef': {
                    '_default': 5.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Chemical Spread in Limbal Region',
                    '_description': 'How quickly chemical spreads through limbal tissue',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Chemical Diffusion',
                    # '_units': 'diffusion rate',
                    '_biological_range': (1.0, 20.0),
                    '_expert_level': 'advanced',
                    '_depends_on': ['SLS_Injury'],
                },
                # 'SLS_TEARDiffCoef': {
                #     '_default': 5.0,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'SLS_TEARDiffCoef': {
                    '_default': 5.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Chemical Spread in Tear Layer',
                    '_description': 'How quickly chemical spreads through tear film',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Chemical Diffusion',
                    # '_units': 'diffusion rate',
                    '_biological_range': (1.0, 20.0),
                    '_expert_level': 'advanced',
                    '_depends_on': ['SLS_Injury'],
                },
                # 'SLS_Threshold_Method': {
                #     '_default': True,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'SLS_Threshold_Method': {
                    '_default': True,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Use Chemical Death Threshold',
                    '_description': 'Whether cells die when chemical concentration exceeds threshold',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Chemical Injury',
                    # '_units': 'boolean',
                    '_expert_level': 'intermediate',
                    '_depends_on': ['SLS_Injury'],
                },
                # 'SLS_Threshold': {
                #     '_default': 2.0,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'SLS_Threshold': {
                    '_default': 2.0,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Chemical Death Threshold',
                    '_description': 'Chemical concentration level above which cells die',
                    '_category': 'Injury Settings',
                    '_subcategory': 'Chemical Injury',
                    # '_units': 'relative concentration',
                    '_biological_range': (0.5, 10.0),
                    '_expert_level': 'intermediate',
                    '_depends_on': ['SLS_Threshold_Method'],
                },

                # --- Function Control Parameters ---
                # 'GrowthControl': {
                #     '_default': True,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'GrowthControl': {
                    '_default': True,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Enable Cell Growth',
                    '_description': 'Allow cells to increase in size over time',
                    '_category': 'Simulation Control',
                    '_subcategory': 'Biological Processes',
                    # '_units': 'boolean',
                    '_expert_level': 'intermediate',
                    '_debug_parameter': True,
                },
                # 'MitosisControl': {
                #     '_default': True,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'MitosisControl': {
                    '_default': True,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Enable Cell Division',
                    '_description': 'Allow cells to divide and create new cells',
                    '_category': 'Simulation Control',
                    '_subcategory': 'Biological Processes',
                    # '_units': 'boolean',
                    '_expert_level': 'intermediate',
                    '_debug_parameter': True,
                },
                # 'DeathControl': {
                #     '_default': True,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'DeathControl': {
                    '_default': True,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Enable Cell Death',
                    '_description': 'Allow cells to die under appropriate conditions',
                    '_category': 'Simulation Control',
                    '_subcategory': 'Biological Processes',
                    # '_units': 'boolean',
                    '_expert_level': 'intermediate',
                    '_debug_parameter': True,
                },
                'DifferentiationControl': {
                    '_default': True,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Enable Cell Differentiation',
                    '_description': 'Allow cells to change from one type to another',
                    '_category': 'Simulation Control',
                    '_subcategory': 'Biological Processes',
                    # '_units': 'boolean',
                    '_expert_level': 'intermediate',
                    '_debug_parameter': True,
                },
                # 'DeathTimeScalar': {
                #     '_default': 1,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'DeathTimeScalar': {
                    '_default': 1,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Cell Death Rate Modifier',
                    '_description': 'Multiplier for how quickly cells die (1.0 = normal rate)',
                    '_category': 'Simulation Control',
                    '_subcategory': 'Biological Processes',
                    # '_units': 'rate multiplier',
                    '_biological_range': (0.1, 10.0),
                    '_expert_level': 'advanced',
                    '_depends_on': ['DeathControl'],
                },
                # 'DifferentiationControl': {
                #     '_default': True,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                
                # --- Plot and Data Collection Parameters ---
                # 'CC3D_PLOT': {
                #     '_default': False,  # Disable for headless runs
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'CC3D_PLOT': {
                    '_default': False,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Real-time Visualization',
                    '_description': 'Show live simulation progress (slower but educational)',
                    '_category': 'Visualization',
                    '_subcategory': 'Real-time Display',
                    # '_units': 'boolean',
                    '_expert_level': 'basic',
                    '_performance_impact': 'high',
                },
                # 'CellCount': {
                #     '_default': True,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'CellCount': {
                    '_default': True,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Track Cell Populations',
                    '_description': 'Record how many cells of each type exist over time',
                    '_category': 'Data Collection',
                    '_subcategory': 'Population Tracking',
                    # '_units': 'boolean',
                    '_expert_level': 'basic',
                    '_output_files': ['cell_count_*.csv'],
                    '_biological_meaning': 'Essential for analyzing healing and regeneration',
                },
                # 'PressureTracker': {
                #     '_default': True,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'PressureTracker': {
                    '_default': True,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Track Cell Pressure (Real-time)',
                    '_description': 'Monitor mechanical stress experienced by cells',
                    '_category': 'Data Collection',
                    '_subcategory': 'Mechanical Properties',
                    # '_units': 'boolean',
                    '_expert_level': 'intermediate',
                    '_biological_meaning': 'Indicates tissue tension and growth constraints',
                    '_performance_impact': 'high',
                },
                # 'EGF_SeenByCell': {
                #     '_default': True,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'EGF_SeenByCell': {
                    '_default': True,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Track EGF Exposure (Real-time)',
                    '_description': 'Monitor EGF concentration experienced by each cell',
                    '_category': 'Data Collection',
                    '_subcategory': 'Growth Factor Tracking',
                    # '_units': 'boolean',
                    '_expert_level': 'intermediate',
                    '_biological_meaning': 'Shows growth factor signaling patterns',
                    '_performance_impact': 'high',
                },
                # 'SLS_SeenByCell': {
                #     '_default': True,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'SLS_SeenByCell': {
                    '_default': True,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Track Chemical Exposure (Real-time)',
                    '_description': 'Monitor chemical concentration experienced by each cell',
                    '_category': 'Data Collection',
                    '_subcategory': 'Chemical Tracking',
                    # '_units': 'boolean',
                    '_expert_level': 'intermediate',
                    '_depends_on': ['SLS_Injury'],
                    '_biological_meaning': 'Critical for understanding chemical toxicity patterns',
                    '_performance_impact': 'high',
                },
                # 'CenterBias': {
                #     '_default': False,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'CenterBias': {
                    '_default': False,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Track Movement Guidance (Real-time)',
                    '_description': 'Monitor guidance signals that direct cell movement',
                    '_category': 'Data Collection',
                    '_subcategory': 'Movement Tracking',
                    # '_units': 'boolean',
                    '_expert_level': 'advanced',
                    '_biological_meaning': 'Shows how cells navigate during tissue repair',
                    '_performance_impact': 'high',
                },
                # 'ThicknessPlot': {
                #     '_default': True,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'ThicknessPlot': {
                    '_default': True,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Track Tissue Thickness',
                    '_description': 'Monitor how tissue thickness changes during healing',
                    '_category': 'Data Collection',
                    '_subcategory': 'Tissue Metrics',
                    # '_units': 'boolean',
                    '_expert_level': 'basic',
                    '_output_files': ['thickness_*.parquet'],
                    '_biological_meaning': 'Key indicator of tissue regeneration success',
                },
                # 'SurfactantTracking': {
                #     '_default': True,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'SurfactantTracking': {
                    '_default': True,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Track Chemical Distribution',
                    '_description': 'Monitor how chemicals spread throughout the tissue',
                    '_category': 'Data Collection',
                    '_subcategory': 'Chemical Tracking',
                    # '_units': 'boolean',
                    '_expert_level': 'intermediate',
                    '_depends_on': ['SLS_Injury'],
                    '_biological_meaning': 'Shows chemical penetration and clearance',
                },
                # 'SnapShot': {
                #     '_default': False,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'SnapShot': {
                    '_default': False,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Take Periodic Snapshots',
                    '_description': 'Save images of tissue state at regular intervals',
                    '_category': 'Data Collection',
                    '_subcategory': 'Visual Documentation',
                    # '_units': 'boolean',
                    '_expert_level': 'basic',
                    '_storage_impact': 'high',
                },
                # 'SnapShot_time': {
                #     '_default': 10,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'SnapShot_time': {
                    '_default': 10,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Snapshot Frequency',
                    '_description': 'How often to take snapshots',
                    '_category': 'Data Collection',
                    '_subcategory': 'Visual Documentation',
                    # '_units': 'hours',
                    '_conversion_factor': 10,  # MCS to hours
                    '_biological_range': (1, 48),
                    '_expert_level': 'basic',
                    '_depends_on': ['SnapShot'],
                },

                # --- Simulation Time ---
                # 'SimTime': {
                #     '_default': 7700,  # Corrected to match vCornea default
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'SimTime': {
                    '_default': 7700,
                    '_updater': 'set',
                    '_emit': True,
                    '_display_name': 'Simulation Duration',
                    '_description': 'How long the simulation runs in biological time',
                    '_category': 'Simulation Setup',
                    '_subcategory': 'Duration',
                    # '_units': 'days',
                    '_conversion_factor': 240,  # MCS to days
                    '_biological_range': (7, 180),  # 1 week to 6 months
                    '_expert_level': 'basic',
                    '_presets': {
                        'short_term': 1680,   # 1 week
                        'wound_healing': 7700,  # ~1 month
                        'long_term': 21600,   # 3 months
                    },
                    '_biological_meaning': 'Determines observation window for healing processes',
                },
            },

            'outputs': {
                # 'cell_counts': {
                #     '_default': {},
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                # 'tissue_thickness': {
                #     '_default': {},
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                # 'healing_time': {
                #     '_default': 0.0,
                #     '_updater': 'set',
                #     '_emit': True,
                # },
                'replicate_results': {
                    '_default': [],
                    '_updater': 'set',
                    '_emit': True,                   
                },
                'simulation_success': {
                    '_default': False,
                    '_updater': 'set',
                    '_emit': True,                    
                },
                'output_directory': {
                    '_default': '',
                    '_updater': 'set',
                    '_emit': True,
                },
                'parameter_changes': {
                    '_default': {},
                    '_updater': 'set',
                    '_emit': True,
                },
                'run_metadata': {
                    '_default': {},
                    '_updater': 'set',
                    '_emit': True,                    
                }
            }
        }

    def next_update(self, timestep, states):
        """Executes a batch of vCornea simulations in parallel and returns results."""
        sim_params = states['inputs']
        num_replicates = self.parameters.get('replicates', 1)
        print(f"VCorneaProcess: Starting batch of {num_replicates} parallel replicate(s).")

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
            
            temp_dir = tempfile.mkdtemp()
            
            try:
                # Setup the simulation environment in a temporary directory
                temp_project = Path(temp_dir) / "vcornea_sim"
                shutil.copytree(self.project_path, temp_project)
                self._redirect_outputs_in_copy(temp_project, run_output_dir)
                sim_params_file = temp_project / "Simulation" / "Parameters.py"
                self._write_parameters_file(sim_params_file, sim_params)

                temp_sim_dir = temp_project / "Simulation"
                before_snapshot = self._take_directory_snapshot(temp_sim_dir)

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
            
            try:
                # Wait for this specific process to complete
                exit_code = process.wait(timeout=86400)
            except subprocess.TimeoutExpired:
                print(f"  > TIMEOUT ERROR: Replicate {job['replicate_id']} exceeded the 24-hour time limit.")
                process.kill()  # Terminate the runaway process
                exit_code = -9  # specific exit code for timeouts

            temp_sim_dir = job['temp_project'] / "Simulation"
            after_snapshot = self._take_directory_snapshot(temp_sim_dir)

            job['exit_code'] = exit_code
            job['completed_at'] = time.time()
            
            # Close log files
            job['stdout_log'].close()
            job['stderr_log'].close()
            
            return job

        print("\n--- Phase 2: Monitoring all processes concurrently ---")

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

            # Get the before/after snapshots from the job
            before_files = job.get('before_snapshot', set())
            after_files = job.get('after_snapshot', set())
            
            # Close log files
            job['stdout_log'].close()
            job['stderr_log'].close()
            
            # Take snapshots to track generated files
            temp_sim_dir = temp_project / "Simulation"
            before_files = set()  # We could take this earlier, but for now just track what exists
            after_files = self._take_directory_snapshot(temp_sim_dir)
            
            # Process based on exit code
            if exit_code == 0:
                # Success - collect files and parse results
                print(f"    - Collecting output files...")
                files_moved = self._collect_output_files(temp_project, run_output_dir, sim_params)
                
                # Get list of files that look like they were generated
                generated_files = self._get_generated_files_list(temp_project, before_files, after_files)
                
                print(f"    - Parsing simulation results...")
                results = self._parse_simulation_results(run_output_dir, sim_params)
                
                run_metadata.update({
                    'simulation_success': True, 
                    'simulation_completed_at': pd.Timestamp.now().isoformat(), 
                    'healing_time': results.get('healing_time'),
                    'files_collected': files_moved,
                    'files_generated': generated_files
                })
                
                replicate_outputs.append({
                    'replicate_id': replicate_id, 
                    'success': True, 
                    'output_directory': str(run_output_dir), 
                    'error_message': None, 
                    'results': results,
                    'files_generated': generated_files,
                    'files_collected': files_moved
                })
                
                print(f"    - Replicate {replicate_id} completed successfully")
                
            else:
                # Failure - record error
                error_message = f"Simulation process failed with exit code {exit_code}. Check stderr.log in the output directory."
                run_metadata.update({
                    'simulation_success': False, 
                    'error_message': error_message
                })
                
                replicate_outputs.append({
                    'replicate_id': replicate_id, 
                    'success': False, 
                    'output_directory': str(run_output_dir), 
                    'error_message': error_message, 
                    'results': None,
                    'files_generated': [],
                    'files_collected': []
                })
                
                print(f"    - Replicate {replicate_id} failed with exit code {exit_code}")
            
            # Save metadata and clean up
            with open(run_output_dir / "run_metadata.json", 'w') as f:
                json.dump(run_metadata, f, indent=2)
            self._update_experiment_log(output_base, run_metadata)
            shutil.rmtree(job['temp_dir'], ignore_errors=True)

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
        """Generate a descriptive run name based on parameter changes."""
        
        # If user provided a custom name, use it
        if self.parameters.get('run_name'):
            return self.parameters['run_name']

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

    def _redirect_outputs_in_copy(self, temp_project, external_output_dir):
        """Modify the copied vCornea steppables to redirect outputs to external directory."""
        steppables_file = temp_project / "Simulation" / "vCornea_v2Steppables.py"
        
        if not steppables_file.exists():
            raise FileNotFoundError(f"Steppables file not found: {steppables_file}")
        
        # Read the original steppables file
        with open(steppables_file, 'r') as f:
            content = f.read()

        safe_path = str(external_output_dir).replace('\\', '/')

        # Replace the output directory line - use forward slashes
        old_line = r'output_directory = current_script_directory\.joinpath\("Output",time\.strftime\("%m%d%Y_%H%M%S"\)\)'
        new_line = f'output_directory = Path(r"{safe_path}")'
        
        if old_line in content:
            content = content.replace(old_line, new_line)
        else:
            # If the exact line isn't found, try a more flexible approach
            import re
            pattern = r'output_directory = current_script_directory\.joinpath\("Output".*?\)\)'
            replacement = f'output_directory = Path(r"{safe_path}")'  # Now using safe_path with forward slashes
            content = re.sub(pattern, replacement, content)
        
        # Also ensure Path is imported
        if 'from pathlib import Path' not in content:
            content = 'from pathlib import Path\n' + content
        
        # Write the modified content back
        with open(steppables_file, 'w') as f:
            f.write(content)

    def _write_parameters_file(self, params_file, sim_params):
        """Write parameters to the vCornea Parameters.py file with ALL defaults."""
        params_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Get ALL default values from ports schema
        all_defaults = {}
        for param, schema in self.ports_schema()['inputs'].items():
            all_defaults[param] = schema['_default']
        
        # Merge user parameters with defaults (user parameters override defaults)
        final_params = {**all_defaults, **sim_params}
        
        with open(params_file, 'w') as f:
            f.write("# Parameters for vCornea simulation\n")
            f.write("# Generated by Vivarium wrapper\n\n")
            
            # Write ALL parameters, not just the changed ones
            for param_name, param_value in final_params.items():
                f.write(f"{param_name}={repr(param_value)}\n")

    def _run_cc3d_simulation(self, project_path, output_dir):
        """
        Launches the CC3D simulation as a separate process using Popen.
        Redirects stdout and stderr to log files in the replicate's output directory.
        """
        cc3d_file = project_path / "vCornea_v2.cc3d"
        conda_env = self.parameters['cc3d_conda_env_name']
        conda_exe = self.parameters.get('conda_executable_path', 'conda') # Use .get for safety
        
        import os
        command = [
            conda_exe, 'run', '-n', conda_env,
            'python', '-m', 'cc3d.run_script',
            '-i', os.fspath(cc3d_file)
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
        Collect output files from the temp directory and move them to the permanent output directory.
        This handles the fact that some files are still written to the temp script directory.
        """
        import glob
        from collections import defaultdict
        
        # Define the directories to search
        temp_simulation_dir = temp_project / "Simulation"
        
        # Track files we've already processed to avoid duplicates
        processed_files = set()
        files_moved = []
        collection_stats = defaultdict(int)
        
        # Expected output file patterns (in order of priority)
        sim_time = sim_params.get('SimTime', 7700)
        file_patterns = [
            f"cell_count_{sim_time + 1}.csv",
            f"thickness_rep_{sim_time + 1}.parquet", 
            f"thickness_rep_*_{sim_time + 1}.parquet",  # Catch variations
            "surfactant_*.csv",
            "center_bias_*.csv", 
            "pressure_*.csv",
            "*.png",  # Screenshots if enabled
            "*.jpg",  # Screenshots if enabled
        ]
        
        print(f"Searching for output files in: {temp_simulation_dir}")
        
        # First pass: Search with specific patterns
        for pattern in file_patterns:
            collection_stats[f'pattern_{pattern}'] = 0
            
            # Search in main directory
            search_paths = [
                temp_simulation_dir / pattern,
                temp_simulation_dir / "**" / pattern  # Recursive search
            ]
            
            for search_path in search_paths:
                found_files = glob.glob(str(search_path), recursive=True)
                
                for file_path in found_files:
                    source_file = Path(file_path)
                    
                    # Skip if already processed (avoid duplicates)
                    if source_file.resolve() in processed_files:
                        continue
                        
                    if source_file.exists() and source_file.is_file():
                        dest_file = output_dir / source_file.name
                        
                        # Skip if destination already exists (avoid overwrites)
                        if dest_file.exists():
                            print(f"Skipping {source_file.name} - destination already exists")
                            continue
                        
                        try:
                            # Copy the file to the permanent location
                            shutil.copy2(source_file, dest_file)
                            processed_files.add(source_file.resolve())
                            files_moved.append(source_file.name)
                            collection_stats[f'pattern_{pattern}'] += 1
                            print(f"Collected output file: {source_file.name}")
                        except Exception as e:
                            print(f"Warning: Could not move file {source_file}: {e}")
        
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
                if source_file.name.startswith(('cell_count_', 'thickness_', 'surfactant_', 
                                            'pressure_', 'center_bias_')) or \
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
        
        # Print collection summary
        total_collected = len(files_moved)
        if total_collected > 0:
            print(f"File collection summary: {total_collected} files collected")
            for category, count in collection_stats.items():
                if count > 0:
                    print(f"  {category}: {count} files")
        else:
            print("Warning: No output files were collected")
        
        return files_moved

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
        output_prefixes = {'cell_count_', 'thickness_', 'surfactant_', 'pressure_', 'center_bias_'}
        
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
        sim_time = sim_params.get('SimTime', 7700)
        
        # Look for output files in the external directory
        cell_count_file = output_dir / f"cell_count_{sim_time + 1}.csv"
        thickness_file = output_dir / f"thickness_rep_{sim_time + 1}.parquet"
        
        results = {
            'simulation_success': True,
            'healing_time': 0.0,
            'cell_counts': {},
            'tissue_thickness': {}
        }
        
        # Parse cell counts
        if cell_count_file.exists():
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
            print(f"Warning: Cell count file not found: {cell_count_file}")
        
        # Parse thickness data
        if thickness_file.exists():
            try:
                thickness_df = pd.read_parquet(thickness_file)
                results['tissue_thickness'] = thickness_df.to_dict('records')
            except Exception as e:
                print(f"Warning: Could not parse thickness data: {e}")
        else:
            print(f"Warning: Thickness file not found: {thickness_file}")
        
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