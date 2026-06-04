#!/usr/bin/env python
"""
Main entry point for vCornea CellFate GUI.

This script launches the GUI application from the vcornea-cellfate-gui root directory.
The default output location for experiments is ./experiments relative to this file.

Usage:
    python run_gui.py
"""

import sys
from pathlib import Path

# Add gui directory to Python path
gui_dir = Path(__file__).parent / 'gui'
sys.path.insert(0, str(gui_dir))

# Add local vivarium-vcornea repo to Python path
project_root = Path(__file__).parent.parent
vivarium_vcornea_dir = project_root / 'vivarium-vcornea'
if vivarium_vcornea_dir.exists():
    sys.path.insert(0, str(vivarium_vcornea_dir))

# Import and run main window
from main_window import main

if __name__ == '__main__':
    main()
