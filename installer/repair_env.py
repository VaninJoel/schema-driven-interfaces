#!/usr/bin/env python
"""Repair conda-unpack backslash corruption (conda-pack issue #154).

After conda-pack relocation, `conda-unpack` rewrites the build prefix to the
install prefix with a naive path-separator replacement. On Windows this can
mangle .py files that contain backslash escape sequences — e.g.
``_pytest/pathlib.py`` (`"\\\\?\\"` -> `"\\\"`, an unterminated string),
``scipy/__config__.py``, etc. — leaving a SyntaxError that crashes imports.

Pure-Python source never legitimately contains the env prefix, so it never
needed rewriting in the first place. This script finds every .py under the
install prefix that no longer compiles and restores the pristine copy from the
(pre-unpack) conda-pack tarball. It is a no-op on a clean env.

Usage:
    python repair_env.py <prefix> <tarball>
"""
import py_compile
import sys
import tarfile
from pathlib import Path


def find_broken(prefix: Path):
    """Return prefix-relative POSIX paths of .py files that fail to compile."""
    broken = {}
    for py in prefix.rglob("*.py"):
        try:
            py_compile.compile(str(py), doraise=True)
        except py_compile.PyCompileError:
            broken[py.relative_to(prefix).as_posix()] = py
        except (SyntaxError, ValueError, UnicodeDecodeError):
            broken[py.relative_to(prefix).as_posix()] = py
    return broken


def main():
    if len(sys.argv) != 3:
        print("usage: python repair_env.py <prefix> <tarball>")
        return 2
    prefix = Path(sys.argv[1]).resolve()
    tarball = Path(sys.argv[2]).resolve()

    broken = find_broken(prefix)
    if not broken:
        print("  - integrity check: all Python files compile OK")
        return 0

    print("  - found %d file(s) corrupted by conda-unpack; restoring from "
          "the packed env..." % len(broken))
    restored = 0
    with tarfile.open(tarball) as tf:
        for member in tf.getmembers():
            if not member.isfile():
                continue
            key = member.name[2:] if member.name.startswith("./") else member.name
            target = broken.get(key)
            if target is None:
                continue
            src = tf.extractfile(member)
            if src is None:
                continue
            target.write_bytes(src.read())
            restored += 1

    still_broken = find_broken(prefix)
    print("  - restored %d file(s); %d still failing" %
          (restored, len(still_broken)))
    for rel in sorted(still_broken):
        print("      ! %s" % rel)
    # Don't fail the install over residual issues — the env is usable and the
    # installer prints what (if anything) is still wrong.
    return 0


if __name__ == "__main__":
    sys.exit(main())
