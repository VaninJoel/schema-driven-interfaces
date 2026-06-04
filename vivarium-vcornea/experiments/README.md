# vivarium-vcornea

**A Vivarium wrapper for the vCornea computational corneal epithelium model**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)

---

## What is vCornea?

vCornea is a computational model of corneal epithelium tissue that simulates:

- **Tissue homeostasis** - How healthy corneal tissue maintains itself
- **Injury response** - What happens when the tissue is damaged  
- **Healing dynamics** - How the tissue recovers over time

This Vivarium wrapper transforms the vCornea CompuCell3D model into a composable process that can be easily used in computational studies, integrated with other models, and deployed in high-throughput research workflows.

**Published Research**: This model is described in [Vanin et al. (2025)](https://doi.org/10.1101/2025.08.11.669602) and demonstrates accurate prediction of healing timeframes for different injury severities.

---

## For Different User Types

### 🔬 Experimentalists & Researchers
**Goal**: Run corneal injury simulations for research studies

- **What you need**: Basic familiarity with Python, no CompuCell3D experience required
- **Use cases**: Dose-response studies, treatment comparisons, injury mechanism research
- **Time investment**: 30 minutes setup, immediate results

[**→ Jump to Experimentalist Quick Start**](#quick-start-for-experimentalists)

### 🏗️ Computational Modelers & Developers  
**Goal**: Integrate vCornea with other computational models

- **What you need**: Experience with Vivarium framework and multi-scale modeling
- **Use cases**: Multi-scale simulations, model coupling, custom analysis pipelines  
- **Time investment**: 1-2 hours integration, extensive customization possible

[**→ Jump to Integration Guide**](#integration-guide-for-modelers)

---

## Installation

### Prerequisites

You'll need two separate conda environments (recommended approach):

1. **vCornea simulation environment** - Contains CompuCell3D and the vCornea model
2. **Your project environment** - Contains this wrapper and your analysis code

### Step 1: Install vCornea Simulation Environment

```bash
# Create environment for CompuCell3D and vCornea
conda create --name vcornea python=3.9
conda activate vcornea

# Install CompuCell3D
mamba install -c compucell3d compucell3d=4.7.0 pandas fastparquet

# Clone the vCornea model (choose one location)
git clone https://github.com/VaninJoel/vCornea.git
# Note the path - you'll need it for configuration
```

### Step 2: Install Vivarium Wrapper

```bash
# Create your project environment (or use existing)
conda create --name my_project python=3.9  
conda activate my_project

# Install this wrapper
pip install git+https://github.com/VaninJoel/vivarium-vcornea.git

# Or for development:
git clone https://github.com/VaninJoel/vivarium-vcornea.git
cd vivarium-vcornea
pip install -e .
```

### Verification

Test your installation:

```python
from vivarium_vcornea.processes.vcornea_process import VCorneaProcess
print("✓ Wrapper installed successfully")
```

---

## Quick Start for Experimentalists

### Basic Configuration

Create a simple configuration file to avoid hardcoding paths:

```python
# config.py
VCORNEA_CONFIG = {
    'vcornea_project_path': '/path/to/vCornea/Local/Project/paper_version',
    'cc3d_conda_env_name': 'vcornea',  # Name of your CC3D environment
    'output_base_dir': './results'      # Where to save results
}
```

### Running Your First Simulation

```python
from vivarium.core.engine import Engine
from vivarium.core.composer import Composer
from vivarium_vcornea.processes.vcornea_process import VCorneaProcess
from vivarium_vcornea.utils.simple_config import create_vivarium_experiment_state
from config import VCORNEA_CONFIG

# Define your simulation parameters
sim_params = {
    'SimTime': 3000,           # Simulation duration
    'IsInjury': True,          # Include injury
    'InjuryType': True,        # True = chemical, False = ablation  
    'SLS_Concentration': 1500.0, # Injury severity
    'InjuryTime': 500,         # When injury occurs
}

# Set up the simulation
class MyStudy(Composer):
    defaults = {'vcornea': VCORNEA_CONFIG}
    
    def generate_processes(self, config):
        return {'cornea': VCorneaProcess(config['vcornea'])}
    
    def generate_topology(self, config):
        return {'cornea': {'inputs': ('inputs',), 'outputs': ('outputs',)}}

# Run simulation
composer = MyStudy()
composite = composer.generate()
initial_state = create_vivarium_experiment_state(sim_params)

sim = Engine(composite=composite, initial_state=initial_state)
sim.update(1.0)

# Get results
results = sim.emitter.get_data()[1.0]['outputs']
print(f"Simulation completed: {results['simulation_success']}")
print(f"Results saved to: {results['output_directory']}")
```

### Key Parameters for Experiments

| Parameter | Description | Typical Values |
|-----------|-------------|----------------|
| `SLS_Concentration` | Chemical injury severity | 750 (mild), 1500 (moderate), 2500 (severe) |
| `InjuryTime` | When injury occurs (hours) | 50-200 |
| `InjuryType` | Chemical (True) vs ablation (False) | True for chemical studies |
| `SimTime` | Total experiment duration (hours) | 3000-7500 |
| `IsInjury` | Include injury event | True/False |

### Example Studies

See the [`experiments/`](experiments/) folder for complete examples:

- **`injury_comparison_study.py`** - Compare different injury types
- **`parameter_sweep_example.py`** - Systematic parameter exploration  
- **`run_vcornea_test.py`** - Basic functionality test

---

## Integration Guide for Modelers

### Why Use the Vivarium Wrapper?

This wrapper enables vCornea to be:

- **Composable**: Integrate with other Vivarium processes
- **Parameterizable**: Programmatic control over all model parameters  
- **Reproducible**: Automatic experiment tracking and metadata
- **Scalable**: Support for parallel execution and batch processing

### Process Interface

```python
from vivarium_vcornea.processes.vcornea_process import VCorneaProcess

# Minimal configuration
config = {
    'vcornea_project_path': '/path/to/vCornea/Local/Project/paper_version',
    'cc3d_conda_env_name': 'vcornea'
}

process = VCorneaProcess(config)

# View all available parameters
schema = process.ports_schema()
print(f"Available parameters: {len(schema['inputs'])}")

# Parameters are organized by category:
# - Cell Properties (stem, basal, wing, superficial cells)
# - Growth Factors (EGF dynamics)
# - Injury Settings (timing, severity, type)
# - Tissue Mechanics (adhesion, boundary interactions)
# - Data Collection (what to track and save)
```

### Multi-Scale Integration Example

```python
from vivarium.core.composer import Composer

class MultiScaleStudy(Composer):
    def generate_processes(self, config):
        return {
            'cornea': VCorneaProcess(config['vcornea']),
            'drug_pk': PharmacokineticProcess(config['pk']),
            'treatment': TreatmentControllerProcess(config['treatment'])
        }
    
    def generate_topology(self, config):
        return {
            'cornea': {
                'inputs': ('tissue_state',),
                'outputs': ('tissue_state', 'damage_level')
            },
            'drug_pk': {
                'inputs': ('drug_dose',),
                'outputs': ('tissue_state',)  # Drug affects tissue
            },
            'treatment': {
                'inputs': ('damage_level',),
                'outputs': ('drug_dose',)     # Dose based on damage
            }
        }
```

### Advanced Features

- **Automatic replicates**: Set `replicates: N` for statistical studies
- **Parallel execution**: Multiple simulations run concurrently 
- **Smart naming**: Descriptive run names based on parameter changes
- **Comprehensive logging**: Full experiment metadata and provenance
- **Flexible outputs**: Cell counts, tissue metrics, spatial data

### Performance Characteristics

- **Runtime**: 30 seconds to 40 minutes per simulation (depends on `SimTime`)
- **Memory**: 2-4 GB RAM per simulation
- **Storage**: 10-50 MB per simulation output
- **Parallelization**: Limited by system cores, not the wrapper

---

## Configuration Options

### Environment Variables

For convenience, you can set:

```bash
export VCORNEA_PROJECT_PATH="/path/to/vCornea/Local/Project/paper_version"
export VCORNEA_CONDA_ENV="vcornea"
```

### Configuration File

Create `vcornea_config.json`:

```json
{
  "vcornea_project_path": "/path/to/vCornea/Local/Project/paper_version",
  "cc3d_conda_env_name": "vcornea",
  "output_base_dir": "./simulation_results"
}
```

Load with:

```python
from vivarium_vcornea.utils.simple_config import load_config_file
config = load_config_file('vcornea_config.json')
```

---

## Project Structure

```
vivarium-vcornea/
├── vivarium_vcornea/           # Main package
│   ├── processes/              # Vivarium process implementations
│   ├── utils/                  # Configuration helpers
│   └── composites/             # Pre-built composite processes
├── experiments/                # Example studies and workflows
│   ├── injury_comparison_study.py
│   ├── parameter_sweep_example.py
│   └── README.md              # Detailed experiment guide
├── tests/                      # Unit and integration tests
└── docs/                       # Additional documentation
```

---

## Common Issues & Solutions

**"CC3D not found"**
- Verify CompuCell3D installation: `conda list compucell3d`
- Check conda environment name in configuration

**"vCornea project not found"**  
- Use absolute paths for `vcornea_project_path`
- Verify the path contains `vCornea_v2.cc3d` and required files

**"Simulations hang or crash"**
- Reduce `SimTime` for testing
- Ensure adequate system memory (2-4 GB per simulation)
- Disable `CC3D_PLOT` for headless execution

**"Import errors"**
- Install in development mode: `pip install -e .`
- Verify Python environment: `which python`

---

## Contributing

We welcome contributions! Areas of interest:

- **New analysis metrics**: Additional output processing and analysis
- **Integration examples**: Demonstrations with other Vivarium processes  
- **Performance optimizations**: Faster execution or reduced memory usage
- **Documentation**: Tutorials, examples, and scientific use cases

### Development Setup

```bash
git clone https://github.com/VaninJoel/vivarium-vcornea.git
cd vivarium-vcornea
pip install -e .
pytest tests/  # Run test suite
```

---

## Citation

If you use this wrapper in your research:

### Vivarium Wrapper
```bibtex
@software{vivarium_vcornea_wrapper,
  author = {Vanin, Joel},
  title = {Vivarium vCornea: A Vivarium wrapper for the vCornea CompuCell3D model},
  year = {2025},
  url = {https://github.com/VaninJoel/vivarium-vcornea}
}
```

### Original vCornea Model
```bibtex
@article{Vanin2025VCornea,
  author = {Vanin, Joel and Getz, Michael and Mahony, Catherine and Knudsen, Thomas B. and Glazier, James A.},
  title = {{V-Cornea: A computational model of corneal epithelium homeostasis, injury, and recovery}},
  journal = {bioRxiv},
  year = {2025},
  doi = {10.1101/2025.08.11.669602}
}
```

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

- **📖 Documentation**: See [`experiments/README.md`](experiments/README.md) for detailed examples
- **🐛 Issues**: [GitHub Issues](https://github.com/VaninJoel/vivarium-vcornea/issues)
- **💬 Discussions**: [GitHub Discussions](https://github.com/VaninJoel/vivarium-vcornea/discussions)
- **📧 Contact**: [Primary author](mailto:your-email@example.com)
