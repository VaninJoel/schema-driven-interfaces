# vivarium-vcornea

## Installation
To use this Vivarium wrapper, you will need two separate Conda environments. This is a best practice that ensures all software dependencies are managed correctly and prevents conflicts.

1. Install the vCornea Simulation Environment:
First, set up the environment that contains CompuCell3D and the vCornea model itself.

```Bash
# Create and activate the environment
conda create --name v_cornea python=3.9
conda activate v_cornea

# Install CC3D and other dependencies
mamba install -c compucell3d compucell3d=4.7.0 pandas fastparquet

# Clone the vCornea model repository
git clone https://github.com/VaninJoel/vCornea.git 
```

2. Install the vivarium-vcornea Wrapper:
Next, in a separate terminal, create an environment for your Vivarium project and install this wrapper library.

```Bash
# Create and activate your project environment
conda create --name my_vivarium_project python=3.9
conda activate my_vivarium_project

# Install the wrapper from GitHub (or PyPI if you publish it)
pip install git+https://github.com/VaninJoel/vivarium-vcornea.git
```
Usage
To use the VCorneaProcess in your own experiment, you must provide the full paths to the vCornea simulation and its Python executable. This ensures the wrapper can find and run the simulation correctly.

```Python
# In your experiment script
from vivarium_vcornea.processes.vcornea_process import VCorneaProcess

# Find the path to your v_cornea environment's Python
# (e.g., /Users/YourName/miniconda3/envs/v_cornea/bin/python)
VCORNEA_PYTHON = '/path/to/your/v_cornea/python'
VCORNEA_PROJECT = '/path/to/your/cloned/vCornea/clean_paper_version'

composer_config = {
'vcornea_process': {
'cc3d_project_path': VCORNEA_PROJECT,
'cc3d_python_executable': VCORNEA_PYTHON,
}
}
#... rest of your experiment setup...
```
## Usage examples
```Python
from vivarium_vcornea.utils.simple_config import create_vcornea_config, create_vivarium_experiment_state
from vivarium_vcornea.processes.vcornea_process import VCorneaProcess
from vivarium.core.engine import Engine

# Create configuration (replaces hardcoded paths)
config = create_vcornea_config(
    vcornea_project_path="/path/to/vcornea/project",
    conda_env_name="my_cc3d_env"
)

# Create your process 
process = VCorneaProcess(config)

# Create experiment state 
sim_params = {
    'SimTime': 1000,
    'IsInjury': True, 
    'SLS_Concentration': 1500.0
}
initial_state = create_vivarium_experiment_state(sim_params)

# Run experiment 
engine = Engine(
    processes={'vcornea': process},
    topology={'vcornea': {'inputs': ('inputs',), 'outputs': ('outputs',)}}, 
    initial_state=initial_state
)

results = engine.update(1.0)
```
