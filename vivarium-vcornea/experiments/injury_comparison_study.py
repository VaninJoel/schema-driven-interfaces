# injury_comparison_study.py
from vivarium.core.engine import Engine
import pandas as pd

from vivarium_vcornea.composites import VCorneaComposer

def run_experiment(injury_type, replicates):
    """A helper function to run a single experiment with specified parameters."""
    print(f"--- Running experiment: {injury_type} injury with {replicates} replicates ---")

    # Process configuration (includes replicates)
    vcornea_config = {
        'cc3d_conda_env_name': 'vc',  # Adjust for your environment
        'replicates': replicates,     # Move replicates to process config
    }

    # Simulation parameters (what gets passed to CC3D)
    sim_params = {
        'SimTime': 5000,
        'IsInjury': True,
        'InjuryTime': 500,
        'InjuryType': injury_type == 'chemical',  # True for chemical, False for ablation
        'CellCount': True,
        'CC3D_PLOT': False,
        # Remove 'replicates' from here - it belongs in process config
    }
    
    try:
        # Use the standard composer
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
        
        output_data = sim.emitter.get_data()
        final_output = output_data[1.0]['outputs']
        
        print(f"  Simulation success: {final_output['simulation_success']}")
        print(f"  Expected {replicates} replicates, got: {len(final_output['replicate_results'])}")
        
        results = []
        for rep_result in final_output['replicate_results']:
            if rep_result['success']:
                healing_time = rep_result['results']['healing_time']
                print(f"    Replicate {rep_result['replicate_id']}: healing_time = {healing_time}")
            else:
                healing_time = None
                print(f"    Replicate {rep_result['replicate_id']}: FAILED - {rep_result.get('error_message', 'Unknown error')}")
            
            results.append({
                'injury_type': injury_type,
                'replicate_id': rep_result['replicate_id'],
                'healing_time_mcs': healing_time,
                'simulation_success': rep_result['success']
            })
        
        return results
        
    except Exception as e:
        print(f"  ERROR: Failed to run {injury_type} injury experiment: {e}")
        # Return failed results for all expected replicates
        failed_results = []
        for rep_id in range(1, replicates + 1):
            failed_results.append({
                'injury_type': injury_type,
                'replicate_id': rep_id,
                'healing_time_mcs': None,
                'simulation_success': False
            })
        return failed_results

if __name__ == '__main__':
    all_results = []
    num_replicates_per_group = 3

    # Run ablation injury group
    ablation_results = run_experiment('ablation', num_replicates_per_group)
    all_results.extend(ablation_results)

    # Run chemical injury group
    chemical_results = run_experiment('chemical', num_replicates_per_group)
    all_results.extend(chemical_results)
    
    # Analyze and save combined results
    results_df = pd.DataFrame(all_results)
    output_filename = "injury_comparison_results.csv"
    results_df.to_csv(output_filename, index=False)
    
    print("\n--- Comparative study complete ---")
    print(f"Results saved to {output_filename}")
    print(f"Total simulations: {len(results_df)}")
    print(f"Successful simulations: {results_df['simulation_success'].sum()}")
    
    # Only analyze successful simulations with non-zero healing times
    successful_df = results_df[results_df['simulation_success'] == True]
    if len(successful_df) > 0:
        summary = successful_df.groupby('injury_type')['healing_time_mcs'].agg(['count', 'mean', 'std']).reset_index()
        print("\nSummary of healing times:")
        print(summary)
        
        # Also show individual results for debugging
        print("\nIndividual results:")
        for _, row in successful_df.iterrows():
            print(f"  {row['injury_type']} replicate {row['replicate_id']}: {row['healing_time_mcs']} MCS")
    else:
        print("No successful simulations to analyze")
        
    # Show failure summary if any
    failed_df = results_df[results_df['simulation_success'] == False]
    if len(failed_df) > 0:
        print(f"\nFailed simulations: {len(failed_df)}")
        failure_summary = failed_df.groupby('injury_type').size().reset_index(name='failed_count')
        print(failure_summary)