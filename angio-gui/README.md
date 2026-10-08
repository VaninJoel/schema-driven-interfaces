# Angio-GUI: A Standalone Application for Angiogenesis Simulations

**Democratizing CompuCell3D Through Accessible, Reproducible Interfaces**

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.12.*-blue)
![CompuCell3D](https://img.shields.io/badge/CompuCell3D-4.7.0-green)
![Vivarium](https://img.shields.io/badge/Vivarium-1.0-green)


---

## Table of Contents

- [Overview](#overview)
- [Project Vision](#project-vision)
- [Key Features](#key-features)
- [Architecture](#architecture)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [User Guide](#user-guide)
- [Analysis & Visualization](#analysis--visualization)
- [Data Management](#data-management)
- [Reproducibility & CURE Compliance](#reproducibility--cure-compliance)
- [Technical Details](#technical-details)
- [Future Directions](#future-directions)
- [Citation](#citation)
- [Contact](#contact)

---

## Overview

**Angio-GUI** is a standalone application that transforms a sophisticated CompuCell3D (CC3D) angiogenesis model into an accessible, user-friendly tool for biological researchers. It bridges the **"usability gap"** between expert-oriented computational modeling platforms and end-users such as experimental biologists, clinicians, and educators.

This application exemplifies the **Integrated Architecture** pattern for packaging CC3D simulations, leveraging:
- **SimService API** for direct programmatic control
- **Zarr storage** for efficient, cloud-ready data management
- **PyQt5 GUI** for intuitive parameter configuration and workflow management
- **Vivarium Process integration** for composable multi-scale modeling
- **Comprehensive analysis tools** for post-simulation visualization and statistical analysis

### Who Is This For?

**Model Developers** can use this as a blueprint for packaging their own CC3D models into distributable applications.

**End Users** (biologists, clinicians, students) can run sophisticated angiogenesis simulations without writing code, exploring parameters like cell adhesion, chemotaxis, and VEGF dynamics through an intuitive interface.

**Educators** can use this as a teaching tool for computational biology, systems modeling, and reproducible science workflows.

---

## Project Vision

### Bridging the Usability Gap

Computational modeling platforms like CompuCell3D are powerful but expert-oriented. They require:
- Deep knowledge of scripting and model configuration
- Familiarity with development interfaces (Twedit++/Player)
- Expertise in debugging and parameter tuning

This creates **significant accessibility barriers** for domain experts who want to *use* validated models rather than *develop* them.

### Our Solution: Architectural Patterns for Accessible Simulations

Angio-GUI represents a modular architectural strategy for transforming complex CC3D models into standalone applications that:

1. **Abstract Complexity**: Hide XML configuration and Python steppables behind a clean GUI
2. **Guide Scientific Inquiry**: Expose only biologically meaningful parameters
3. **Ensure Reproducibility**: Systematically link parameters with outputs in structured formats
4. **Enable Scale**: Support batch execution, parameter sweeps, and parallel processing
5. **Facilitate Integration**: Provide pathway for Vivarium ecosystem compatibility

| **Model Developers** | **End Users (This GUI)** |
|----------------------|--------------------------|
| Design, debug, optimize simulations | Run validated models for specific tasks |
| Full scripting access | Simplified, guided workflow |
| Multi-layered visualization with debugging | High-level, interpretable visuals |
| Raw data, advanced tools | Processed results in user-friendly formats |
| Version control, advanced guides | Guided tutorials, easy report generation |

---

## Key Features

### **User-Friendly Parameter Configuration**
- **Schema-driven GUI**: Automatically generated controls from Vivarium ports_schema()
- **Biologically meaningful inputs**: Cell adhesion energies, chemotaxis strength, VEGF production
- **Validation**: Input constraints prevent biologically implausible values
- **Parameter presets**: Normal, High VEGF, Low VEGF, Fast Simulation configurations
- **Expertise levels**: Adjust parameter visibility (Basic, Intermediate, Advanced)

### **Flexible Execution Modes**
- **Single Simulations**: Run with specific parameter combinations
- **Parameter Sweeps**: Systematic exploration of parameter space using comma-separated values
  - Example: `jee: 2,4,6,8` creates 4 variations
  - Full factorial design: Combine multiple parameters
- **Replicate Batches**: Multiple runs (1-100) with identical settings for statistical analysis
- **Concurrent Execution**: Parallel simulation scheduling with process isolation
- **Real-time Monitoring**: Live progress tracking via Zarr store monitoring

### **Efficient Data Management**
- **Unified Zarr Storage**: All runs, parameters, and outputs in single hierarchical structure
- **Incremental Writing**: Task-aware data capture (write/skip_write directives)
- **Configurable Write Frequency**: Balance temporal resolution vs. I/O performance
  - High resolution: Every 5-10 MCS (detailed temporal data)
  - Balanced: Every 20 MCS (good performance)
  - Minimal I/O: Every 50 MCS or final state only (fastest, ~10x speedup)
- **Cloud-Ready**: Format compatible with S3, GCS, Azure Blob (requires fsspec)
- **Metadata Linking**: Parameters intrinsically linked to results for perfect reproducibility

### **Comprehensive Analysis & Visualization**

#### **5-Tab Analysis Interface**
1. **📊 Metrics Tab**
   - **Network connectivity metrics**:
     - Cell density, number of clusters, fragmentation index
     - Connectivity index, compactness, network perimeter
   - **Cell-based metrics**: Cell count, mean/std cell size
   - **VEGF statistics**: Min, max, mean, std, percentiles
   - **Time series plots** with interactive matplotlib controls
   - **CSV export** for external analysis

2. **🔬 Visualization Tab**
   - **Cell field visualization** with customizable colormaps
   - **VEGF field visualization** with **locked colorbar** (consistent across timesteps)
   - **Cell boundary overlay** (1-pixel accurate from cell ID field)
   - **Timestep navigation** and animation playback
   - **Side-by-side or individual view modes**

3. **💾 Export Tab**
   - **Video Export**: MP4 (H.264) and GIF animation generation
   - **Configurable FPS** and layer selection (cells, VEGF, boundaries)
   - **Frame-by-frame PNG export**
   - **High-resolution metric plots export**
   - **Progress monitoring** for long exports

4. **📊 Statistics Tab**
   - **Replicate Analysis**: Compare multiple runs of same parameters
   - **Statistical metrics**: Mean, std, SEM, 95% confidence intervals, median
   - **Box plots** with individual data points
   - **Bar charts** with error bars
   - **Supports all network and VEGF metrics**

5. **📈 Comparison Tab**
   - **Multi-experiment overlay plots**
   - **Parameter value comparison**
   - **Batch folder selection** (Ctrl+multi-select support)
   - **Side-by-side metric visualization**

### **Advanced Capabilities**
- **Multi-Selection**: Batch add experiments with Ctrl+click for efficient workflow
- **Complete Provenance**: Automatic logging and metadata generation
- **Organized Output**: Auto-generated folder structure with clear naming conventions

---

## Architecture

Angio-GUI implements the **Integrated Architecture** pattern described in our methodology paper. This design prioritizes performance, data efficiency, and runtime control while enabling Vivarium ecosystem integration.

### System Architecture

```
┌─────────────────────────────────────────────────────┐
│              PyQt5 GUI Layer                        │
│  • Parameter Configuration (Schema-Driven)          │
│  • Execution Control (Run/Batch/Cancel)             │
│  • Analysis Interface (5-Tab Window)                │
└────────────────────┬────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────┐
│         Scheduler/Worker Layer                      │
│  • Task Queue Management                            │
│  • Process Isolation (Subprocess per Simulation)    │
│  • Threading (QThread for GUI Responsiveness)       │
│  • Real-time Progress Monitoring                    │
└────────────────────┬────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────┐
│         Vivarium Process Layer                      │
│  • AngiogenesisProcess (Vivarium Wrapper)           │
│  • ports_schema() → Parameter Definition            │
│  • next_update() → Simulation Step                  │
│  • State Management via Stores                      │
└────────────────────┬────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────┐
│         Core Simulation Layer (CC3D)                │
│  • SimService API Control                           │
│  • WriterSteppable (Task-Aware I/O)                 │
│  • Biological Steppables (Model Logic)              │
└────────────────────┬────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────┐
│         Zarr Storage Layer                          │
│  • Hierarchical Data Store (.CC3Dstore)             │
│  • Incremental Writes (Chunked Arrays)              │
│  • Metadata Attributes (Parameters, Provenance)     │
│  • Time-Resolved 4D Arrays [x, y, z, channels]      │
└─────────────────────────────────────────────────────┘
```

### Core Components

#### **1. Vivarium Integration Layer**
- **AngiogenesisProcess**: Vivarium-compatible wrapper around CC3D simulation
- **ports_schema()**: Defines parameters and their types/constraints
- **Schema-driven GUI**: Automatically generates widgets from schema
- **Composable**: Can be combined with other Vivarium processes

#### **2. Core Simulation Module (`angio-core/`)**
- Built around `CC3DSimService` for direct programmatic control
- Custom `WriterSteppable` with task-aware execution
- Task directives: `write`, `skip_write` (extensible to dynamic steering)
- Encapsulated simulation logic independent of GUI

#### **3. Batch queue & Execution (`gui/main_window.py`, `gui/simulation_worker.py`)**
- Batch queue (in `AngiogenesisMainWindow.launch_batch_simulation` / `_start_queued_runs`): expands sweeps × replicates into runs, stamps each with its seed, scan point and schema fingerprint, and starts at most **Max simultaneous runs** at a time (default: CPU cores − 1, adjustable in the Batch panel and remembered between sessions); the rest queue and start as slots free. Cancel stops running processes and discards the queue.
- `SimulationWorker`: subprocess-based execution for process isolation; one CC3D process per run
- Real-time progress tracking via Zarr store monitoring

#### **4. GUI Layer (`gui/`)**
- `main_window.py`: Parameter configuration, execution control, batch setup
- `analysis_window.py`: 5-tab post-simulation analysis interface
- Schema-driven widget generation (extensible)
- Signal/slot architecture for clean separation of concerns

#### **5. Storage Layer (`*.zarr/` or `*.CC3Dstore`)**
- **Zarr**: Chunked, compressed N-dimensional arrays
- Hierarchical groups: One per simulation run
- Metadata attributes: All parameters stored with results
- Time-resolved arrays: Cell types, cell IDs, VEGF concentrations
- Incremental writes: Direct-to-disk during simulation

### Why This Architecture?

✅ **Performance**: Process isolation, efficient parallel I/O, incremental writes
✅ **Scalability**: Cloud-ready storage, distributed computing compatible
✅ **Reproducibility**: Parameters and results intrinsically linked
✅ **Composability**: Vivarium integration enables multi-scale modeling
✅ **Extensibility**: Clear interfaces for adding features (ML, advanced steering)

### Comparison with Decoupled Architecture

This integrated approach trades implementation complexity for performance and flexibility. For simpler conversion of existing CC3D projects with minimal refactoring, see our **decoupled subprocess-based architecture** (corneal epithelium example in the companion paper).

| Feature | Integrated (This GUI) | Decoupled (vCornea) |
|---------|----------------------|---------------------|
| **Core Technology** | SimService API + Vivarium | subprocess + file I/O |
| **Complexity** | Higher (deeper integration) | Lower (minimal changes) |
| **Performance** | High (in-memory, parallel I/O) | Moderate (file-based) |
| **Runtime Control** | Full (task-aware execution) | Limited (fire-and-forget) |
| **Portability** | Best for new projects | Excellent for existing models |
| **Data Format** | Unified Zarr hierarchy | Individual CSV/Parquet files |
| **Best Use Case** | High-throughput, cloud-scale | Rapid conversion, stability |

---

## 📦 Installation

### Prerequisites

- **Python 3.12**
- **CompuCell3D 4.7** (with conda installation recommended)
- **Operating System**: Linux, macOS, or Windows

### Step 1: Install CompuCell3D

```bash
# Using conda (recommended)
conda create -n cc3d-env -c compucell3d -c conda-forge cc3d
conda activate cc3d-env
```

### Step 2: Clone Repository

```bash
git clone https://github.com/VaninJoel/angio-gui.git
cd angio-gui
```

### Step 3: Install Python Dependencies

```bash
pip install PyQt5 numpy scipy zarr matplotlib vivarium-core
```

**Optional (for video export):**
```bash
pip install imageio imageio-ffmpeg  # For MP4 export
```

### Step 4: Verify Installation

```bash
python run_gui.py
```

You should see the main application window open.

---

## 🚀 Quick Start

### Running Your First Simulation

1. **Launch the GUI:**
   ```bash
   python run_gui.py
   ```

2. **Select a Preset (Optional):**
   - Choose "Normal" for standard parameters
   - Or "Fast Simulation" for quick testing

3. **Configure Basic Parameters:**
   - **Adhesion energies**: `jee` (EC-EC), `jem` (EC-Medium)
   - **Chemotaxis**: `lchem`, `lsc`, `vedir`, `veder`
   - **VEGF**: `vesec` (secretion rate)
   - **Simulation**: `sim_time` (MCS), `write_frequency`

4. **Set Output Directory:**
   - Default: `./experiments/`
   - Or click "Browse..." to select custom location

5. **Enter Experiment Name:**
   - Example: `baseline_test`

6. **Run Simulation:**
   - Click "▶ Run Simulation"
   - Monitor progress in status bar and console

7. **Analyze Results:**
   - Click "📊 Analyze Results" when complete
   - Explore the 5-tab analysis interface

### Example: Parameter Sweep with Replicates

```python
# In GUI parameter fields:
jee: 2,4,6          # EC-EC adhesion sweep (3 values)
jem: 2              # Keep constant
Replicates: 3       # Three runs per parameter value
Experiment: adhesion_sweep

# This creates: 3 parameters × 3 replicates = 9 simulations
# Output folder: experiments/adhesion_sweep_20250106_143052/
#   - adhesion_sweep_combo001_rep01/ (jee=2)
#   - adhesion_sweep_combo001_rep02/ (jee=2)
#   - adhesion_sweep_combo001_rep03/ (jee=2)
#   - adhesion_sweep_combo002_rep01/ (jee=4)
#   - ... etc.
```

---

## 📖 User Guide

### Parameter Reference

#### Cell Adhesion Parameters
- **`jee`** (EC-EC adhesion): Strength of endothelial cell-cell bonds
  - Range: 0-10 | Default: 2.0
  - Higher values → stronger cohesion, less migration

- **`jem`** (EC-Medium adhesion): Cell-substrate interaction
  - Range: 0-10 | Default: 2.0
  - Higher values → cells prefer medium over neighbors

#### Chemotaxis Parameters
- **`lchem`** (chemotaxis lambda): Overall strength of VEGF response
  - Range: 0-1000 | Default: 500.0
  - Higher values → stronger directional migration

- **`lsc`** (chemotaxis saturation): VEGF concentration at half-maximal response
  - Range: 0.01-10 | Default: 0.1
  - Controls sensitivity curve

- **`vedir`** (directed velocity): Movement speed toward VEGF gradient
  - Range: 0-2 | Default: 1.0

- **`veder`** (random velocity): Baseline random motility
  - Range: 0-1 | Default: 0.3

#### VEGF Parameters
- **`vesec`** (VEGF secretion): Production rate per cell
  - Range: 0-1 | Default: 0.3
  - Higher values → stronger chemical fields

#### Simulation Control
- **`sim_time`**: Total Monte Carlo Steps (MCS)
  - Range: 10-1000 | Default: 100

- **`write_frequency`**: How often to save snapshots
  - Range: 1-100 | Default: 10
  - Every N steps (e.g., 10 = save at 10, 20, 30...)
  - Lower values = more temporal resolution but slower

### Batch Execution

#### Parameter Sweeps
1. Use comma-separated values in any parameter field:
   - `jee: 2,4,6,8` → Creates 4 variations
   - Combine parameters for full factorial:
     - `jee: 2,4` + `jem: 2,4` + `lchem: 250,500` = 2×2×2 = 8 combinations

2. Set number of replicates (1-100)
   - Enables statistical analysis of stochastic behavior

3. Application generates all combinations automatically

#### Folder Organization
```
experiments/
└── experiment_name_20250106_143052/  # Batch folder with timestamp
    ├── experiment_name_combo001_rep01/
    │   ├── data.zarr/                # Simulation data (Zarr format)
    │   ├── logs/
    │   │   ├── stdout.log
    │   │   └── stderr.log
    │   └── run_metadata.json         # Complete parameter record
    ├── experiment_name_combo001_rep02/
    ├── experiment_name_combo002_rep01/
    └── ...
```

**Naming Convention:**
- Single run: `experiment_name/`
- Replicates only: `experiment_name_rep01/`, `experiment_name_rep02/`, ...
- Sweep only: `experiment_name_combo001/`, `experiment_name_combo002/`, ...
- Both: `experiment_name_combo001_rep01/`, `experiment_name_combo002_rep02/`, ...

---

## 📊 Analysis & Visualization

### Metrics Tab

#### Network Connectivity Metrics
- **Cell Density**: Fraction of domain occupied by cells
- **Number of Clusters**: Connected component count (requires scipy)
- **Fragmentation Index**: 1 - (largest cluster size / total cells)
- **Connectivity Index**: Largest cluster / total EC pixels
- **Network Perimeter**: Boundary pixel count (using binary erosion)
- **Compactness**: 4π × area / perimeter² (1.0 = perfect circle)

#### Cell-Based Metrics (from Cell ID field)
- **Number of Cells**: Unique cell ID count
- **Mean Cell Size**: Average pixels per cell
- **Std Cell Size**: Variation in cell sizes

#### VEGF Field Statistics
- **Min, Max, Mean**: Field value range
- **Standard Deviation**: Spatial heterogeneity
- **Median**: Central tendency
- **95th Percentile**: High-concentration regions

#### Time Series Visualization
- Interactive matplotlib plots with zoom, pan, save
- Cell density evolution over time
- Network fragmentation dynamics
- VEGF concentration trends
- Export as high-resolution PNG

### Visualization Tab

#### Cell Field Rendering
- **Colormap**: White (Medium) → Dark Red (Endothelial Cells)
- **Cell Boundaries**: 1-pixel accurate from cell ID field
  - Toggle on/off with checkbox
  - Black lines show cell-cell interfaces

#### VEGF Field Rendering
- **Colormap**: Viridis (purple → yellow)
- **Locked Colorbar**: Uses global min/max across ALL timesteps
  - Ensures consistent scale for temporal comparison
  - Range displayed in status bar on load
  - Prevents misleading color shifts between frames

#### Controls
- **Timestep Navigation**: Dropdown menu or play button
- **Layer Selection**: Show Cells, Show VEGF, Show Cell Borders
- **Animation Playback**: Automatic stepping with adjustable speed
- **View Modes**: Side-by-side or individual plots

### Export Tab

#### Video Export (Priority Feature!)

**MP4 Format:**
- H.264 codec (broad compatibility)
- Configurable FPS (1-30)
- High quality encoding
- Requires `imageio-ffmpeg`: `pip install imageio imageio-ffmpeg`

**GIF Format:**
- Animated GIF for presentations/web
- Looping playback
- Larger file sizes than MP4
- Requires `imageio`: `pip install imageio`

**Layer Selection:**
- ☑ Show Cells
- ☑ Show VEGF
- ☑ Show Cell Borders

**Export Process:**
1. Select layers to include
2. Set FPS (frames per second)
3. Click "Export Animation as MP4" or "GIF"
4. Progress dialog shows frame generation and encoding
5. Choose save location

#### Still Image Export
- **Current Frame**: High-DPI PNG of visualization
- **Metric Plots**: Publication-quality time series figures
- Preserves matplotlib formatting and labels

### Statistics Tab (Advanced Analysis)

#### Replicate Analysis
**Purpose**: Compare multiple runs with identical parameters to assess stochastic variation

**Workflow:**
1. Click "Add Replicate" (Ctrl+click for multi-select)
2. Select all replicate folders (e.g., `exp_rep01`, `exp_rep02`, `exp_rep03`)
3. Choose metric from dropdown:
   - Network: `cell_density`, `num_clusters`, `connectivity_index`, `compactness`
   - VEGF: `vegf_mean`, `vegf_max`, `vegf_std`
4. Click "Analyze Replicates"

**Output:**
- **Summary Table**: n, mean, std, SEM, 95% CI (t-distribution), median
- **Box Plot**: Shows distribution with quartiles and individual data points
- **Bar Chart**: Mean with 95% confidence interval error bars

**Statistical Methods:**
- Standard Error of Mean (SEM): std / √n
- 95% Confidence Interval: t-distribution (scipy.stats)
- Visual representation aids in identifying significant effects

### Comparison Tab

**Purpose**: Overlay multiple experiments with different parameters

**Workflow:**
1. Click "Add Experiment" (Ctrl+multi-select supported)
2. Select 2+ experiments to compare
3. Click "Generate Comparison"

**Visualizations:**
- **Time Series Overlay**: All experiments on same plot
  - Cell density comparison
  - Cluster count comparison
  - VEGF evolution comparison
- **Parameter Comparison**: Bar chart showing parameter values
- **Legend**: Color-coded by experiment name

---

## 💾 Data Management

### Zarr Storage Format

#### Why Zarr?
- **Chunked**: Efficient random access to large arrays
- **Compressed**: Automatic compression (blosc, gzip, etc.)
- **Parallel I/O**: Multi-threaded read/write
- **Cloud-Native**: Works with S3, GCS, Azure Blob Storage
- **Portable**: Pure Python, cross-platform
- **Metadata**: Attributes store parameters with data

#### Hierarchy Structure

```
data.zarr/  (or custom .CC3Dstore extension)
├── zarr.json                    # Root metadata
├── 10/                          # Timestep 10 MCS
│   ├── zarr.json
│   └── data/
│       ├── zarr.json            # Shape: [200, 200, 1, 3]
│       └── c/                   # Chunked binary data
│           ├── 0.0.0.0
│           ├── 0.0.0.1
│           └── ...
├── 20/                          # Timestep 20 MCS
├── 30/
└── ...
```

#### Data Channels (4D Arrays: [x, y, z, channels])
- **Channel 0**: Cell types (0=Medium, 1=Endothelial Cell)
- **Channel 1**: Cell IDs (unique identifier per cell, 0=Medium)
- **Channel 2**: VEGF concentration field (continuous values)

**Note**: Angiogenesis model is 2D, so z-dimension = 1

#### Metadata Storage

**In Zarr attributes:**
```python
import zarr
root = zarr.open('experiment_dir/data.zarr', mode='r')
params = dict(root.attrs)  # All simulation parameters
```

**In run_metadata.json:**
```json
{
  "experiment_name": "adhesion_sweep_combo001_rep01",
  "timestamp": "2025-01-06T14:30:22.325550",
  "parameters": {
    "jee": 2.0,
    "jem": 2.0,
    "lchem": 500.0,
    "lsc": 0.1,
    "vedir": 1.0,
    "veder": 0.3,
    "vesec": 0.3,
    "sim_time": 100.0,
    "write_frequency": 10
  },
  "execution": {
    "exit_code": 0,
    "success": true,
    "final_step": 100,
    "duration_seconds": 45.2
  }
}
```

### Accessing Data Programmatically

```python
from pathlib import Path
import zarr
import numpy as np

# Open Zarr store
exp_dir = Path("experiments/my_experiment")
root = zarr.open(str(exp_dir / "data.zarr"), mode='r')

# List available timesteps
timesteps = sorted([int(k) for k in root.keys() if k.isdigit()])
print(f"Timesteps: {timesteps}")

# Load data for timestep 50
data = root['50']['data'][:]  # Shape: [200, 200, 1, 3]

# Extract channels
cell_types = data[:, :, 0, 0]  # 2D array [200, 200]
cell_ids = data[:, :, 0, 1]
vegf_field = data[:, :, 0, 2]

# Compute custom metrics
ec_density = (cell_types == 1).sum() / cell_types.size
unique_cells = np.unique(cell_ids[cell_ids > 0]).size
mean_vegf = vegf_field.mean()

print(f"EC Density: {ec_density:.3f}")
print(f"Number of Cells: {unique_cells}")
print(f"Mean VEGF: {mean_vegf:.3f}")
```

### Integration with Analysis Pipeline

```python
from gui.analysis_utils import ExperimentData, analyze_time_series

# High-level API
exp = ExperimentData(exp_dir)
results = analyze_time_series(exp)

# Access metrics
for t, metrics in zip(results['timesteps'], results['network_metrics']):
    density = metrics['cell_density']
    clusters = metrics['num_clusters']
    print(f"t={t}: density={density:.3f}, clusters={clusters}")
```

---

## 🔬 Reproducibility & CURE Compliance

This application embodies the **CURE principles** for trustworthy computational models:

### **C - Credible**
- Literature-based parameter ranges
- Validated angiogenesis model from published research
- Transparent biological assumptions
- Parameter presets guide users toward plausible values

### **U - Understandable**
- GUI abstracts technical complexity
- Biologically meaningful parameter names (not code variables)
- Intuitive visualizations with clear legends
- Comprehensive documentation and tooltips

### **R - Reproducible**
- **Perfect Parameter Capture**: Every input saved with outputs
- **Structured Data Format**: Zarr links metadata and results
- **Unique Run IDs**: Timestamped directories prevent overwrites
- **Complete Provenance**: run_metadata.json records full execution context
- **Version Control**: Git tracks code changes (commit SHA future feature)
- **Archival**: Zenodo DOI for permanent citation (recommended workflow)

### **E - Extensible**
- **Modular Architecture**: Clear interfaces for new features
- **Vivarium Integration**: Composable with other models
- **Open Data Format**: Zarr works with standard Python tools
- **Plugin System**: Easy to add custom metrics, visualizations
- **ML Integration**: Ready for surrogate modeling, active learning

### Reproducibility Checklist

When publishing results from Angio-GUI:

- [ ] Archive code on Zenodo with DOI
- [ ] Include `run_metadata.json` as supplementary material
- [ ] Document software versions:
  - CompuCell3D version (`cc3d --version`)
  - Python version (`python --version`)
  - Key dependencies (`pip list > requirements.txt`)
- [ ] Share Zarr stores (or subsampled versions) on data repositories
- [ ] Record random seeds if stochastic behavior is critical
- [ ] Include Git commit SHA in manuscript methods

**Example Methods Section:**
> "Simulations were performed using Angio-GUI v1.0.0 (DOI:10.5281/zenodo.XXXXXX) with CompuCell3D 4.3.0 and Python 3.9.7. All parameters and complete simulation outputs are available at Zenodo (DOI:10.5281/zenodo.YYYYYY). The simulation code and GUI are version-controlled at github.com/VaninJoel/angio-gui (commit SHA: abc123)."

---

## 🔧 Technical Details

### Execution Flow

```
User configures parameters in GUI
     ↓
Scheduler creates Task from parameter values
     ↓
SimulationWorker spawns subprocess
     ↓
AngiogenesisProcess (Vivarium) initializes
     ↓
Core module controls CC3D via SimService
     ↓
Simulation loop with task-aware WriterSteppable
     ↓
Incremental write to Zarr store (every write_frequency MCS)
     ↓
Subprocess completes, returns exit code
     ↓
GUI updates status, enables analysis
     ↓
Analysis Window loads Zarr data on demand
```

### Task-Aware Execution

The `WriterSteppable` responds to external directives passed via `external_input`:

```python
class WriterSteppable(SteppableBasePy):
    def __init__(self, frequency=1):
        super().__init__(frequency)
        self.external_input = None  # Task directive from scheduler

    def step(self, mcs):
        if self.external_input == 'write':
            self.write_data_to_zarr()
        elif self.external_input == 'skip_write':
            pass  # Evolve simulation without I/O overhead
        # Future directives:
        # - 'checkpoint': Save full state for resuming
        # - 'update_param': Dynamic parameter steering
        # - 'diagnose': Runtime diagnostics
```

**Benefits:**
- Selective data capture reduces I/O overhead
- Enables dynamic behaviors (parameter updates, staged perturbations)
- Supports advanced workflows (checkpointing, ML-guided steering)

### Threading Model

- **Main Thread**: PyQt5 GUI event loop (user interaction)
- **Worker Subprocess**: Each simulation runs in isolated process
- **Progress Monitoring**: Periodic Zarr store checks in background thread
- **Signal/Slot Communication**: Thread-safe updates to GUI

**Why Subprocess (Not QThread)?**
- Process isolation: Crash in simulation doesn't kill GUI
- True parallelism: Bypasses Python GIL for CPU-intensive work
- Clean resource cleanup: OS handles memory on process exit

### Performance Considerations

**Zarr Chunking Strategy:**
- Default chunk size: Auto-optimized by Zarr
- Compression: Blosc (balanced speed/compression ratio)
- Trade-off: Larger chunks = fewer files but less granular access

**Write Frequency Trade-off:**
| write_frequency | Temporal Resolution | Execution Time | Use Case |
|-----------------|--------------------|--------------------|----------|
| 5 | High (20 snapshots for 100 MCS) | ~1.5x slower | Detailed analysis |
| 10 | Balanced (10 snapshots) | Baseline | Standard workflow |
| 50 | Low (2 snapshots) | ~1.2x faster | Parameter sweeps |
| 100 | Minimal (1 snapshot) | ~10x faster | High-throughput screening |

**Parallel Execution:**
- Max concurrent simulations: Configurable (default: CPU cores - 1)
- Queue-based scheduling prevents resource exhaustion
- Process pool reuse for efficiency

---

## 🚀 Future Directions

### Near-Term Enhancements
- [ ] **Advanced Network Metrics**:
  - Tortuosity measurement (vessel path length / straight-line distance)
  - Branching point detection (3+ neighbors in graph)
  - Fractal dimension analysis
- [ ] **Export Formats**:
  - OME-TIFF for microscopy software compatibility
  - HDF5 for matlab/IDL users
  - CSV time series export
- [ ] **Parameter Sensitivity**:
  - Sobol indices, Morris method
  - Automated sensitivity analysis GUI
- [ ] **Report Generation**:
  - Automated PDF/HTML reports with plots
  - Publication-ready figure export templates
- [ ] **Checkpointing**:
  - Resume simulations from saved state
  - Staged experiments (baseline → perturbation)

### Vivarium Ecosystem Integration

**Current Status**: Angio-GUI already uses Vivarium Process wrapper!

**Completed:**
✅ `AngiogenesisProcess` implements Vivarium `Process` interface
✅ `ports_schema()` defines parameters for composition
✅ Schema-driven GUI auto-generation

**Next Steps:**
1. **Composite Simulations**:
   - Couple angiogenesis with tumor growth model
   - Add immune cell process
   - Integrate metabolic/signaling networks

2. **Hierarchical Modeling**:
   - Multi-scale: Molecular → Cellular → Tissue
   - Different time scales (fast metabolism, slow angiogenesis)

3. **Vivarium Marketplace**:
   - Publish AngiogenesisProcess as reusable component
   - Enable plug-and-play composition by other researchers

**Example Composite (Future):**
```python
from vivarium import Composer
from angiogenesis_process import AngiogenesisProcess
from tumor_process import TumorGrowthProcess
from immune_process import ImmuneResponseProcess

# Compose multi-scale model
composer = Composer(processes={
    'angio': AngiogenesisProcess,
    'tumor': TumorGrowthProcess,
    'immune': ImmuneResponseProcess
})

# Define connections between processes
composer.connect('angio', 'vegf_field', 'tumor', 'growth_signal')
composer.connect('tumor', 'necrotic_region', 'immune', 'target_location')

# Run composite simulation
composite = composer.generate()
composite.run(1000)  # 1000 time units
```

### Machine Learning Integration
- **Surrogate Modeling**: Train neural networks to approximate slow simulations
- **Active Learning**: Intelligently sample parameter space
- **Real-time Steering**: ML predicts optimal next parameters
- **Dimensionality Reduction**: PCA/t-SNE for high-dimensional exploration
- **Anomaly Detection**: Flag unexpected simulation behavior

### Cloud & High-Performance Computing
- **AWS Batch**: Submit parameter sweeps to cloud
- **Google Cloud Platform**: Use Dataflow for distributed analysis
- **Kubernetes**: Container orchestration for massive scale
- **Zarr Cloud Storage**: S3/GCS for collaborative workflows
- **Cost Optimization**: Spot instances, preemptible VMs

---

## 📚 Citation

If you use Angio-GUI in your research, please cite:

```bibtex
@article{AngiogenesisGUI2025,
  title={From Expert Model to User Application: Architectural Patterns for Accessible CompuCell3D Simulations},
  author={Vanin, Joel and [Co-authors]},
  journal={[Journal TBD]},
  year={2025},
  note={Software available at: https://github.com/VaninJoel/angio-gui}
}
```

**Underlying angiogenesis model:**
The CC3D model wrapped by this GUI is based on the vasculogenesis model of Merks et al.:
> Merks RMH, Brodsky SV, Goligorksy MS, Newman SA, Glazier JA. *Cell elongation is
> key to in silico replication of in vitro vasculogenesis and subsequent remodeling.*
> Developmental Biology. 2006;289(1):44–54. doi:[10.1016/j.ydbio.2005.10.003](https://doi.org/10.1016/j.ydbio.2005.10.003)

```bibtex
@article{Merks2006,
  title={Cell elongation is key to in silico replication of in vitro vasculogenesis and subsequent remodeling},
  author={Merks, Roeland M H and Brodsky, Sergey V and Goligorksy, Michael S and Newman, Stuart A and Glazier, James A},
  journal={Developmental Biology},
  volume={289},
  number={1},
  pages={44--54},
  year={2006},
  publisher={Elsevier},
  doi={10.1016/j.ydbio.2005.10.003}
}
```

**CompuCell3D Citation:**
```bibtex
@article{Swat2012,
  title={Multi-Scale Modeling of Tissues Using CompuCell3D},
  author={Swat, Maciej H and Thomas, Gilberto L and Belmonte, Julio M and others},
  journal={Methods in Cell Biology},
  volume={110},
  pages={325--366},
  year={2012},
  publisher={Elsevier}
}
```

**Vivarium Citation:**
```bibtex
@article{Vivarium2020,
  title={Vivarium: an interface and engine for integrative multiscale modeling in computational biology},
  author={Agmon, Eran and Spangler, Ryan K and Skalnik, Christopher J and others},
  journal={bioRxiv},
  year={2020},
  publisher={Cold Spring Harbor Laboratory}
}
```

---

## 📄 License

This project is licensed under the **MIT License** - see [LICENSE](LICENSE) file for details.

**Third-Party Components:**
- **CompuCell3D**: Licensed under respective terms
- **PyQt5**: GPL v3 (note: commercial license available for proprietary use)
- **Vivarium**: MIT License
- **Zarr, NumPy, SciPy, Matplotlib**: BSD-style licenses

---

## 📞 Contact & Support

- **Primary Contact**: Joel Vanin <joelvanin@example.com>
- **Issues**: [GitHub Issues](https://github.com/VaninJoel/angio-gui/issues)
- **Discussions**: [GitHub Discussions](https://github.com/VaninJoel/angio-gui/discussions)
- **Forum**: [CompuCell3D Forum](https://compucell3d.org/Forum)

---

## 🎓 Educational Use

This application is ideal for:
- **Computational Biology Courses**: Hands-on exploration of cellular behavior
- **Systems Biology Labs**: Hypothesis testing without coding barrier
- **Clinical Research**: Parameter exploration for translational studies
- **Software Engineering Education**: GUI design, threading, data management examples

**Teaching Modules Available:**
1. **Introduction to Angiogenesis Modeling**
2. **Parameter Sensitivity Analysis Workshop**
3. **Reproducible Computational Science Workflows**
4. **Multi-Scale Modeling with Vivarium**

---

## 🙏 Acknowledgments

- **CompuCell3D Team**: For the powerful simulation framework
- **Vivarium Project**: For composable modeling standards
- **Open Source Community**: Python, Qt, Zarr, NumPy, SciPy, Matplotlib
- **Funding**: [Grant agencies if applicable]

---

## Appendix: Troubleshooting

### Common Issues

**❌ GUI doesn't launch**
✅ Check PyQt5 installation: `pip show PyQt5`
✅ Ensure X11 forwarding if using SSH: `export DISPLAY=:0`

**❌ "zarr not available" warning**
✅ Install: `pip install zarr`

**❌ Video export fails**
✅ Install ffmpeg: `pip install imageio-ffmpeg`
✅ For GIF: `pip install imageio`

**❌ Simulation won't start**
✅ Verify CC3D installation: `python -c "import cc3d"`
✅ Check conda environment is activated

**❌ Analysis window shows no data**
✅ Ensure simulation completed (check `run_metadata.json`)
✅ Verify `data.zarr` folder exists and isn't empty
✅ Check logs in `logs/stderr.log` for errors

**❌ "Process terminated" error**
✅ Increase memory limit if sweeping many parameters
✅ Reduce concurrent simulations (default: CPU cores - 1)
✅ Check disk space for Zarr writes

### Performance Tips
- **Use SSD** for output directory (10x faster I/O)
- **Reduce write_frequency** for faster parameter sweeps (100 = final state only)
- **Limit concurrent simulations** based on RAM (each run ~500MB-2GB)
- **Close unused analysis windows** to free memory
- **Compress Zarr** with blosc for 3-5x space savings (default)

### Getting Help
1. **Check FAQ**: [GitHub Wiki](https://github.com/VaninJoel/angio-gui/wiki)
2. **Search Issues**: [Existing solutions](https://github.com/VaninJoel/angio-gui/issues?q=is%3Aissue)
3. **CC3D Forum**: [Community support](https://compucell3d.org/Forum)
4. **Report Bug**: Include `run_metadata.json`, logs, and system info

---

**Built with ❤️ for the computational biology community**

*Making sophisticated simulations accessible, reproducible, and extensible.*

---

**Last Updated:** January 2025
**Version:** 1.0.0
**Compatibility:** CompuCell3D 4.x, Python 3.8+, Vivarium 1.x
