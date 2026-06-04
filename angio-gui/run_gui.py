#!/usr/bin/env python
"""
Main entry point for Angiogenesis GUI.

This script launches the GUI application from the angio-gui root directory.
The default output location for experiments is ./experiments relative to this file.

Usage:
    python run_gui.py
"""

import sys
from pathlib import Path

# Add gui directory to Python path
gui_dir = Path(__file__).parent / 'gui'
sys.path.insert(0, str(gui_dir))

# Add parent directory for vivarium_angio import
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import and run main window
from main_window import main

if __name__ == '__main__':
    main()
