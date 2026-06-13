#!/usr/bin/env python
"""
Main entry point for Angiogenesis GUI.

This script launches the GUI application from the angio-gui root directory.
The default output location for experiments is ./experiments relative to this file.

Usage:
    python run_gui.py
"""

import os
import sys
from pathlib import Path


def _register_conda_dll_dirs():
    """Make the packaged conda env usable when launched without `conda activate`.

    The installer runs this env by calling its python.exe directly, so conda's
    DLL directories are not on the search path. numpy's MKL/LAPACK chain (which
    matplotlib invokes for every plot — e.g. the Analyze window and the PDF
    reports) then fails to load and crashes the whole process with a delay-load
    error (0xc06d007f). Registering the conda DLL dirs explicitly fixes it.
    No-op off Windows or in an already-activated env.
    """
    if sys.platform != 'win32' or not hasattr(os, 'add_dll_directory'):
        return
    for sub in ('Library\\bin', 'Library\\mingw-w64\\bin',
                'Library\\usr\\bin', 'Scripts', ''):
        d = os.path.join(sys.prefix, sub)
        if os.path.isdir(d):
            try:
                os.add_dll_directory(d)
            except OSError:
                pass


_register_conda_dll_dirs()

# Add gui directory to Python path
gui_dir = Path(__file__).parent / 'gui'
sys.path.insert(0, str(gui_dir))

# Add parent directory for vivarium_angio import
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import and run main window
from main_window import main

if __name__ == '__main__':
    main()
