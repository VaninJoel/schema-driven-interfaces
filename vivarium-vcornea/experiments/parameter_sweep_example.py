# parameter_sweep_example.py
from vivarium.core.engine import Engine
import pandas as pd

from vivarium_vcornea.composites import VCorneaComposer

if __name__ == '__main__':
    # Parameters to sweep
    sls_concentrations = [500.0, 1500.0, 2500.0]
    num_replicates = 2

    # Prepare to store results
    all_results = []
    
    for conc in sls_concentrations:
        print(f"--- Running sweep for SLS_Concentration: {conc} ---")
        
        # Process configuration (includes replicates)
        vcornea_config = {
            'cc3d_conda_env_name': 'vc',  # Adjust for your environment
            'replicates': num_replicates,  # Move replicates to process config
        }
        
        # Simulation parameters for this specific run (what goes to CC3D)
        sim_params = {
            'SimTime': 500,
            'IsInjury': True,
            'InjuryTime': 50,
            'InjuryType': True,  # Chemical injury
            'SLS_Concentration': conc,  # This parameter varies in the sweep
            'CellCount': True,
            'CC3D_PLOT': False,
            # Remove 'replicates' from here - it belongs in process config
        }

        try:
            # Create Vivarium engine using standard composer
            composer = VCorneaComposer({'vcornea': vcornea_config})
            composite = composer.generate()
            
            # Create initial state directly (no helper function needed)
            initial_state = {
                'inputs': sim_params,
                'outputs': {}
            }
            
            sim = Engine(
                composite=composite,
                initial_state=initial_state
            )
            sim.update(1.0)
            
            # Collect and process results
            output_data = sim.emitter.get_data()
            final_output = output_data[1.0]['outputs']
            
            print(f"  Simulation success: {final_output['simulation_success']}")
            print(f"  Expected {num_replicates} replicates, got: {len(final_output['replicate_results'])}")
            
            for rep_result in final_output['replicate_results']:
                if rep_result['success']:
                    healing_time = rep_result['results']['healing_time']
                    print(f"    Replicate {rep_result['replicate_id']}: healing_time = {healing_time}")
                else:
                    healing_time = None
                    print(f"    Replicate {rep_result['replicate_id']}: FAILED - {rep_result.get('error_message', 'Unknown error')}")
                
                all_results.append({
                    'SLS_Concentration': conc,
                    'replicate_id': rep_result['replicate_id'],
                    'healing_time_mcs': healing_time,
                    'simulation_success': rep_result['success']
                })
                
        except Exception as e:
            print(f"  ERROR: Failed to run simulation for SLS_Concentration {conc}: {e}")
            # Record failed runs in results
            for rep_id in range(1, num_replicates + 1):
                all_results.append({
                    'SLS_Concentration': conc,
                    'replicate_id': rep_id,
                    'healing_time_mcs': None,
                    'simulation_success': False
                })

    # Save all results to a CSV file
    results_df = pd.DataFrame(all_results)
    output_filename = "sls_concentration_sweep_results.csv"
    results_df.to_csv(output_filename, index=False)
    
    print(f"\n--- Parameter sweep complete ---")
    print(f"Results saved to {output_filename}")
    
    # Summary statistics
    print("\nSummary of results:")
    successful_results = results_df[results_df['simulation_success'] == True]
    
    if len(successful_results) > 0:
        summary = successful_results.groupby('SLS_Concentration')['healing_time_mcs'].agg(['count', 'mean', 'std']).reset_index()
        print(summary)
        
        print("\nIndividual results:")
        for _, row in successful_results.iterrows():
            print(f"  SLS {row['SLS_Concentration']}, replicate {row['replicate_id']}: {row['healing_time_mcs']} MCS")
    else:
        print("No successful simulations to analyze")
        
    # Show failure summary if any
    failed_results = results_df[results_df['simulation_success'] == False]
    if len(failed_results) > 0:
        print(f"\nFailed simulations: {len(failed_results)}")