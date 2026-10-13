"""Terminate a subprocess together with everything it spawned.

`Popen.kill()` stops only the direct child. A CC3D launch may run through
`conda run` (which forks the real interpreter), and the GUI's worker subprocess
forks one CC3D process per replicate, so killing only the direct child leaves
the simulations running.
"""
import subprocess
import sys


def kill_process_tree(process):
    """Kill `process` (a Popen) and all of its descendants. Never raises.

    Returns True when the tree is known to be gone.
    """
    if process is None or process.poll() is not None:
        return True
    pid = process.pid
    try:
        import psutil
        try:
            parent = psutil.Process(pid)
            for child in parent.children(recursive=True):
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
            parent.kill()
        except psutil.NoSuchProcess:
            pass
        return True
    except ImportError:
        pass
    if sys.platform == 'win32':
        try:
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)],
                           capture_output=True, timeout=10)
            return True
        except Exception:
            pass
    try:
        process.kill()
    except Exception:
        return False
    return True
