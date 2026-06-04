#!/usr/bin/env python3
"""
Comprehensive end-to-end test for vCornea-Vivarium wrapper using pytest.

This test actually runs minimal vCornea simulations to verify the complete workflow:
- Parameter injection
- File creation and naming
- Output parsing
- Vivarium integration
- Multiple replicates

Usage:

    Full test suite:
        pytest E2E_test.py -v 

    Or run a single test:
        pytest E2E_test.py::TestCompleteWorkflow::test_minimal_simulation -v 
"""

import pytest
import tempfile
import shutil
import time
from pathlib import Path
import pandas as pd
import json
import os

# from vivarium_vcornea.utils.simple_config import get_test_config

import json

def load_test_config():
    """Load test configuration from JSON file."""
    config_locations = [
        Path.cwd() / "vcornea_config.json",
        Path(__file__).parent / "vcornea_config.json",
        Path.home() / ".vcornea_config.json"
    ]
    
    for config_file in config_locations:
        if config_file.exists():
            try:
                with open(config_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                continue
    
    # Fallback: try auto-discovery paths
    search_paths = [
        Path(__file__).parent.parent / "vCornea/Local/Project/paper_version",
        Path.home() / "vCornea/Local/Project/paper_version",
    ]
    
    for path in search_paths:
        if path.exists() and (path / "vCornea_v2.cc3d").exists():
            return {
                'vcornea_project_path': str(path),
                'cc3d_conda_env_name': 'vcornea'
            }
    
    return None

try:
    config = load_test_config()
    if not config:
        pytest.skip("No vCornea configuration found. Create vcornea_config.json or place vCornea in standard location.", allow_module_level=True)
    
    VCORNEA_PROJECT_PATH = Path(config['vcornea_project_path'])
    CONDA_ENV_NAME ='vc' #config['cc3d_conda_env_name']
except Exception as e:
    pytest.skip(f"Configuration error: {e}", allow_module_level=True)

@pytest.fixture
def vcornea_process():
    """Fixture providing a configured VCorneaProcess for testing."""
    from vivarium_vcornea.processes.vcornea_process import VCorneaProcess
    
    # with tempfile.TemporaryDirectory() as temp_dir:
    output_dir = Path.cwd() / "test_outputs"
    
    parameters = {
        'vcornea_project_path': str(VCORNEA_PROJECT_PATH),
        'cc3d_conda_env_name': CONDA_ENV_NAME,
        'output_base_dir': str(output_dir),            
        'replicates': 1
    }
    
    yield VCorneaProcess(parameters)

@pytest.fixture
def minimal_sim_params():
    """Fixture providing minimal simulation parameters for fast testing."""
    return {
        'SimTime': 50,  # Very short simulation
        'CC3D_PLOT': False,
        'IsInjury': False,
        'CellCount': True,
        'ThicknessPlot': True,
        'SurfactantTracking': False,
        'SnapShot': False
    }

@pytest.fixture
def custom_sim_params():
    """Fixture providing custom simulation parameters for parameter testing."""
    return {
        'SimTime': 30,
        'SLS_Concentration': 1500.0,  # Non-default value
        'InjuryTime': 10,             # Non-default value
        'IsInjury': True,
        'InjuryType': True,           # Chemical injury
        'CC3D_PLOT': False,
        'CellCount': True,
        'ThicknessPlot': True
    }

class TestCompleteWorkflow:
    """Test the complete vCornea-Vivarium workflow with actual simulations."""
    
    def test_auto_discovery_fallback(self):
        """Test that auto-discovery works when no explicit path provided."""
        from vivarium_vcornea.processes.vcornea_process import VCorneaProcess
        
        # Test with minimal config (should use auto-discovery)
        try:
            process = VCorneaProcess({
                'cc3d_conda_env_name': CONDA_ENV_NAME,
                'replicates': 1
            })
            # If this doesn't raise an exception, auto-discovery worked
            assert process.project_path.exists()
            assert (process.project_path / "vCornea_v2.cc3d").exists()
            
        except (ValueError, FileNotFoundError) as e:
            pytest.skip(f"Auto-discovery test skipped: {e}")

    def test_minimal_simulation(self, vcornea_process, minimal_sim_params):
        """Test running a minimal vCornea simulation and verify outputs."""
        # Run the simulation
        states = {'inputs': minimal_sim_params}
        start_time = time.time()
        
        results = vcornea_process.next_update(1.0, states)
        elapsed_time = time.time() - start_time
        
        print(f"Simulation completed in {elapsed_time:.1f} seconds")
        
        # Verify basic result structure
        assert 'outputs' in results
        assert 'simulation_success' in results['outputs']
        assert 'replicate_results' in results['outputs']
        assert 'output_directory' in results['outputs']
        
        # Verify simulation succeeded
        assert results['outputs']['simulation_success'] is True
        
        # Verify replicate results
        replicate_results = results['outputs']['replicate_results']
        assert len(replicate_results) == 1
        assert replicate_results[0]['success'] is True
        assert replicate_results[0]['replicate_id'] == 1
        
        # Verify output directory exists
        output_directory = Path(results['outputs']['output_directory'])
        assert output_directory.exists()
        
        # Verify replicate directory and files
        replicate_dir = output_directory / "replicate_1"
        assert replicate_dir.exists()
        
        # Check for expected output files
        expected_files = [
            f"cell_count_{minimal_sim_params['SimTime'] + 1}.csv",
            f"thickness_rep_{minimal_sim_params['SimTime'] + 1}.parquet",
            "run_metadata.json",
            "stdout.log",
            "stderr.log"
        ]
        
        for expected_file in expected_files:
            file_path = replicate_dir / expected_file
            assert file_path.exists(), f"Missing expected file: {expected_file}"
            assert file_path.stat().st_size > 0, f"Empty file: {expected_file}"

    def test_output_file_content(self, vcornea_process, minimal_sim_params):
        """Test that output files contain valid data."""
        states = {'inputs': minimal_sim_params}
        results = vcornea_process.next_update(1.0, states)
        
        assert results['outputs']['simulation_success'] is True
        
        replicate_dir = Path(results['outputs']['output_directory']) / "replicate_1"
        sim_time = minimal_sim_params['SimTime']
        
        # Test cell count CSV
        cell_count_file = replicate_dir / f"cell_count_{sim_time + 1}.csv"
        assert cell_count_file.exists()
        
        df = pd.read_csv(cell_count_file)
        assert not df.empty
        assert 'Time' in df.columns
        assert all(col in df.columns for col in ['Superficial', 'Wing', 'Basal', 'Stem'])
        assert df['Time'].max() <= sim_time + 1  # Final time point
        assert all((df[col] >= 0).all() for col in ['Superficial', 'Wing', 'Basal', 'Stem'])  # Cell counts should be non-negative
        
        # Test thickness parquet
        thickness_file = replicate_dir / f"thickness_rep_{sim_time + 1}.parquet"
        assert thickness_file.exists()
        
        df_thickness = pd.read_parquet(thickness_file)
        assert not df_thickness.empty
        assert 'Time' in df_thickness.columns
        
        # Test metadata JSON
        metadata_file = replicate_dir / "run_metadata.json"
        assert metadata_file.exists()
        
        with open(metadata_file, 'r') as f:
            metadata = json.load(f)
        
        assert 'run_name' in metadata
        assert 'created_at' in metadata
        assert 'simulation_success' in metadata
        assert metadata['simulation_success'] is True
        assert 'simulation_config' in metadata
        assert metadata['simulation_config']['sim_time'] == sim_time

    def test_parameter_injection(self, vcornea_process, custom_sim_params):
        """Test that custom parameters are properly injected and detected."""
        # Test parameter change detection
        parameter_changes = vcornea_process._identify_parameter_changes(custom_sim_params)
        
        # Should detect changes for non-default values
        expected_changes = ['SLS_Concentration', 'InjuryTime', 'InjuryType']
        for param in expected_changes:
            assert param in parameter_changes, f"Expected parameter change not detected: {param}"
        
        # Verify specific parameter values
        assert parameter_changes['SLS_Concentration']['current_value'] == 1500.0
        assert parameter_changes['SLS_Concentration']['default_value'] == 750.0
        assert parameter_changes['SLS_Concentration']['change_type'] == 'increased'
        
        assert parameter_changes['InjuryTime']['current_value'] == 10
        assert parameter_changes['InjuryTime']['default_value'] == 500
        assert parameter_changes['InjuryTime']['change_type'] == 'decreased'
        
        assert parameter_changes['InjuryType']['current_value'] is True
        assert parameter_changes['InjuryType']['default_value'] is False
        assert parameter_changes['InjuryType']['change_type'] == 'toggled'

    def test_run_name_generation(self, vcornea_process, custom_sim_params):
        """Test that run names are generated correctly from parameter changes."""
        parameter_changes = vcornea_process._identify_parameter_changes(custom_sim_params)
        run_name = vcornea_process._generate_run_name(parameter_changes)
        
        # Should contain parameter information
        assert 'SLS1500' in run_name
        assert 'InjT10' in run_name
        assert len(run_name) > 10  # Should be descriptive
        
        # Test with no changes
        no_changes = {}
        default_name = vcornea_process._generate_run_name(no_changes)
        assert 'default_run' in default_name
        
        # Test with custom name
        vcornea_process.parameters['run_name'] = 'my_custom_test'
        custom_name = vcornea_process._generate_run_name(parameter_changes)
        assert custom_name == 'my_custom_test'

    def test_simulation_with_custom_parameters(self, vcornea_process, custom_sim_params):
        """Test running simulation with custom parameters and verify they're applied."""
        states = {'inputs': custom_sim_params}
        results = vcornea_process.next_update(1.0, states)
        
        assert results['outputs']['simulation_success'] is True
        
        # Verify parameter changes are recorded
        parameter_changes = results['outputs']['parameter_changes']
        assert 'SLS_Concentration' in parameter_changes
        assert 'InjuryTime' in parameter_changes
        
        # Verify run metadata includes custom parameters
        run_metadata = results['outputs']['run_metadata']
        assert run_metadata['simulation_config']['sim_time'] == custom_sim_params['SimTime']
        assert run_metadata['simulation_config']['has_injury'] == custom_sim_params['IsInjury']
        assert run_metadata['simulation_config']['injury_type'] == 'chemical'  # InjuryType=True means chemical

    def test_multiple_replicates(self):
        """Test running multiple replicates."""
        from vivarium_vcornea.processes.vcornea_process import VCorneaProcess
        
        
        output_dir = Path.cwd() / "test_outputs" / "multi_replicate_test"
        
        parameters = {
            'vcornea_project_path': str(VCORNEA_PROJECT_PATH),
            'cc3d_conda_env_name': CONDA_ENV_NAME,
            'output_base_dir': str(output_dir),
            'keep_outputs': True,
            'replicates': 3  # Multiple replicates
        }
        
        process = VCorneaProcess(parameters)
        
        sim_params = {
            'SimTime': 25,  # Very short for speed
            'CC3D_PLOT': False,
            'IsInjury': False,
            'CellCount': True,
            'ThicknessPlot': False,  # Disable to speed up
            'SurfactantTracking': False
        }
        
        states = {'inputs': sim_params}
        results = process.next_update(1.0, states)
        
        assert results['outputs']['simulation_success'] is True
        
        # Verify all replicates completed
        replicate_results = results['outputs']['replicate_results']
        assert len(replicate_results) == 3
        
        for i, rep in enumerate(replicate_results, 1):
            assert rep['replicate_id'] == i
            assert rep['success'] is True
            
            # Verify each replicate has its own directory
            rep_dir = Path(rep['output_directory'])
            assert rep_dir.exists()
            assert rep_dir.name == f"replicate_{i}"

    def test_error_handling_missing_project(self):
        """Test error handling when project path is missing."""
        from vivarium_vcornea.processes.vcornea_process import VCorneaProcess
        
        with pytest.raises(FileNotFoundError, match="vCornea project path not found"):
            VCorneaProcess({'vcornea_project_path': '/nonexistent/path'})

    def test_error_handling_missing_files(self):
        """Test error handling when required files are missing."""
        from vivarium_vcornea.processes.vcornea_process import VCorneaProcess
        
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_project = Path(temp_dir) / "fake_project"
            fake_project.mkdir()
            
            # Create only some required files
            (fake_project / "vCornea_v2.cc3d").touch()
            
            with pytest.raises(FileNotFoundError, match="Required vCornea file not found"):
                VCorneaProcess({'vcornea_project_path': str(fake_project)})

    def test_parameter_file_writing(self, vcornea_process):
        """Test that parameter files are written correctly."""
        test_params = {
            'SLS_Concentration': 1500.0,
            'SimTime': 100,
            'IsInjury': True,
            'CC3D_PLOT': False
        }
        
        with tempfile.TemporaryDirectory() as temp_dir:
            params_file = Path(temp_dir) / "test_parameters.py"
            
            vcornea_process._write_parameters_file(params_file, test_params)
            
            assert params_file.exists()
            
            # Verify file content
            content = params_file.read_text()
            
            for param, value in test_params.items():
                expected_line = f"{param}={repr(value)}"
                assert expected_line in content
            
            # Verify it's valid Python
            compile(content, str(params_file), 'exec')
            
            # Verify we can execute it and get the values
            namespace = {}
            exec(content, namespace)
            
            for param, expected_value in test_params.items():
                assert namespace[param] == expected_value
    
    def test_temp_folder_parameters(self): 
        """Test that Parameters.py is created correctly in the temp project."""
        from vivarium_vcornea.processes.vcornea_process import VCorneaProcess
        import tempfile
        import shutil
        from pathlib import Path
        
        print("\n" + "="*60)
        print("TESTING PARAMETERS.PY IN TEMP FOLDER")
        print("="*60)
        
        process = VCorneaProcess({
            'vcornea_project_path': str(VCORNEA_PROJECT_PATH),
            'cc3d_conda_env_name': CONDA_ENV_NAME,
        })
        
        with tempfile.TemporaryDirectory() as temp_dir:
            print(f"Temp directory: {temp_dir}")
            
            # Step 1: Copy project to temp (like your process does)
            temp_project = Path(temp_dir) / "vcornea_sim"
            shutil.copytree(process.project_path, temp_project)
            print(f"Project copied to: {temp_project}")
            
            # Step 2: Check the Simulation folder structure
            sim_folder = temp_project / "Simulation"
            print(f"Simulation folder exists: {sim_folder.exists()}")
            
            if sim_folder.exists():
                print("Contents of Simulation folder BEFORE Parameters.py creation:")
                for item in sim_folder.iterdir():
                    print(f"  {item.name}")
            
            # Step 3: Create Parameters.py (like your process does)
            sim_params = {
                'SimTime': 25,
                'CC3D_PLOT': False,
                'IsInjury': False,
                'CellCount': True,
            }
            
            # This is the CRITICAL path - must be in temp project
            params_file = temp_project / "Simulation" / "Parameters.py"
            print(f"\nCreating Parameters.py at: {params_file}")
            
            process._write_parameters_file(params_file, sim_params)
            
            # Step 4: Verify creation
            print(f"Parameters.py exists: {params_file.exists()}")
            
            if params_file.exists():
                print(f"Parameters.py size: {params_file.stat().st_size} bytes")
                content = params_file.read_text()
                print(f"Parameters.py content:\n{content}")
                
                # Step 5: Test if CC3D can run with this setup
                output_dir = Path(temp_dir) / "output"
                output_dir.mkdir()
                
                # Redirect outputs
                process._redirect_outputs_in_copy(temp_project, output_dir)
                
                # Try to run CC3D for just a few seconds to see initial errors
                cc3d_file = temp_project / "vCornea_v2.cc3d"
                conda_env = CONDA_ENV_NAME
                
                import subprocess
                import os
                
                command = [
                    'conda', 'run', '-n', conda_env,
                    'python', '-m', 'cc3d.run_script',
                    '-i', os.fspath(cc3d_file)
                ]
                
                print(f"\nTesting CC3D execution:")
                print(f"Command: {' '.join(command)}")
                print(f"Working directory: {temp_project}")
                
                try:
                    # Run with a short timeout to capture initial errors
                    result = subprocess.run(
                        command,
                        cwd=os.fspath(temp_project),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=15  # 15 second timeout
                    )
                    
                    print(f"Exit code: {result.returncode}")
                    
                    if result.stdout:
                        print(f"STDOUT:\n{result.stdout}")
                    
                    if result.stderr:
                        print(f"STDERR:\n{result.stderr}")
                    
                    
                    
                except subprocess.TimeoutExpired as e:
                    print("Timed out after 15 seconds (might be normal CC3D startup)")
                    if e.stdout:
                        print(f"Partial STDOUT:\n{e.stdout}")
                    if e.stderr:
                        print(f"Partial STDERR:\n{e.stderr}")
                except Exception as e:
                    print(f"Error running CC3D: {e}")
            else:
                print("❌ Parameters.py was NOT created!")
                assert False, "Parameters.py creation failed"
            
            print("="*60)

    def test_capture_cc3d_errors(self, vcornea_process):
        """Capture and display the actual CC3D error messages."""
        from vivarium_vcornea.processes.vcornea_process import VCorneaProcess
        import tempfile
        from pathlib import Path
        
        print("\n" + "="*60)
        print("CAPTURING CC3D ERROR MESSAGES")
        print("="*60)
        
        output_dir = Path.cwd() / "test_outputs" / "cc3d_error_capture"
        
        process = VCorneaProcess({
            'vcornea_project_path': str(VCORNEA_PROJECT_PATH),
            'cc3d_conda_env_name': CONDA_ENV_NAME,
            'output_base_dir': str(output_dir),
            'keep_outputs': True,  # Keep outputs so we can read logs
            'replicates': 1
        })
        
        sim_params = {
            'SimTime': 10,  # Very short
            'CC3D_PLOT': False,
            'IsInjury': False,
            'CellCount': True,
        }
        
        states = {'inputs': sim_params}
        results = process.next_update(1.0, states)
        
        print(f"Simulation success: {results['outputs']['simulation_success']}")
        
        # Read and display the actual error logs
        for rep in results['outputs']['replicate_results']:
            if not rep['success']:
                rep_dir = Path(rep['output_directory'])
                
                stderr_log = rep_dir / "stderr.log"
                stdout_log = rep_dir / "stdout.log"
                
                print(f"\n--- REPLICATE {rep['replicate_id']} ERROR LOGS ---")
                
                if stderr_log.exists():
                    stderr_content = stderr_log.read_text()
                    if stderr_content.strip():
                        print("STDERR:")
                        print(stderr_content)
                    else:
                        print("STDERR: (empty)")
                
                if stdout_log.exists():
                    stdout_content = stdout_log.read_text()
                    if stdout_content.strip():
                        print("STDOUT:")
                        print(stdout_content)
                    else:
                        print("STDOUT: (empty)")
        
        print("="*60)

class TestVivarium_integration:
    """Test Vivarium-specific integration features."""

    def test_vivarium_engine_integration(self, vcornea_process):
        """Test that VCorneaProcess works properly within Vivarium Engine."""
        from vivarium.core.engine import Engine
        from vivarium.core.composer import Composer
        from vivarium_vcornea.processes.vcornea_process import VCorneaProcess
        
        class TestComposer(Composer):
            defaults = {
                'vcornea_process': {
                    'vcornea_project_path': str(VCORNEA_PROJECT_PATH),
                    'cc3d_conda_env_name': CONDA_ENV_NAME,
                    'replicates': 1,
                }
            }
            
            def generate_processes(self, config):
                return {'vcornea': VCorneaProcess(config['vcornea_process'])}
            
            def generate_topology(self, config):
                return {
                    'vcornea': {
                        'inputs': ('globals', 'inputs'),
                        'outputs': ('globals', 'outputs'),
                    }
                }
        
        # Create Vivarium engine
        composer = TestComposer()
        composite = composer.generate()
        
        initial_state = {
            'globals': {
                'inputs': {
                    'SimTime': 25,
                    'CC3D_PLOT': False,
                    'IsInjury': False
                }
            }
        }
        
        engine = Engine(composite=composite, initial_state=initial_state)
        
        # Verify engine was created successfully
        assert engine is not None
        
        # Verify the engine has the basic attributes we expect
        assert hasattr(engine, 'state')
        assert hasattr(engine, 'update')
        
        # Verify the initial state was set correctly
        assert 'globals' in engine.state.get_value()
        assert 'inputs' in engine.state.get_value()['globals']
        
        # Try running one update step to ensure integration works
        engine.update(1.0)  # This should work without errors if integration is correct

    def test_ports_schema_completeness(self, vcornea_process):
        """Test that ports schema includes all expected vCornea parameters."""
        schema = vcornea_process.ports_schema()
        
        # Check basic structure
        assert 'inputs' in schema
        assert 'outputs' in schema
        
        # Check for key vCornea parameters
        essential_inputs = [
            'SimTime', 'SLS_Concentration', 'IsInjury', 'InjuryTime',
            'SLS_Threshold', 'SLS_TEARDiffCoef',
            'EGF_STEM_HalfMaxValue', 'EGF_BASAL_HalfMaxValue'
        ]
        
        for param in essential_inputs:
            assert param in schema['inputs'], f"Missing essential input parameter: {param}"
            assert '_default' in schema['inputs'][param]
            assert '_updater' in schema['inputs'][param]
        
        # Check essential outputs
        essential_outputs = [
            'replicate_results', 'simulation_success', 
            'output_directory', 'parameter_changes'
        ]
        
        for param in essential_outputs:
            assert param in schema['outputs'], f"Missing essential output parameter: {param}"

if __name__ == "__main__":
    pytest.main([__file__, "-v"])