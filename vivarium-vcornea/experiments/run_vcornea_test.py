# run_vcornea_test.py
from vivarium.core.engine import Engine
from vivarium_vcornea.composites import VCorneaComposer

if __name__ == '__main__':
    # Minimal config - let VCorneaProcess auto-discover vCornea
    vcornea_config = {
        'cc3d_conda_env_name': 'vc',  # Only specify non-discoverable settings
        'replicates': 1,
    }
    
    sim_params = {
        'SimTime': 100,
        'IsInjury': True,
        'InjuryTime': 50,
        'CellCount': True,
        'CC3D_PLOT': False,
    }
    
    try:
        composer = VCorneaComposer({'vcornea': vcornea_config})
        composite = composer.generate()
        initial_state = {'inputs': sim_params, 'outputs': {}}
        
        sim = Engine(composite=composite, initial_state=initial_state)
        
        print("--- LAUNCHING VIVARIUM VCORNEA TEST ---")
        sim.update(1.0)
        print("--- TEST COMPLETE ---")
        
        # ... rest of result processing unchanged
        
    except (ValueError, FileNotFoundError) as e:
        print(f"Auto-discovery failed: {e}")
        print("Ensure vCornea is in a standard location or create vcornea_config.json")