#!/usr/bin/env python
"""Freeze the source revision into the packaged wrapper packages at build time.

The installed application imports the wrappers from the packed environment's
site-packages (not from the staged payload copies), and the installer ships
without a .git directory. Without a stamp written here, every run performed by an
end user reports its code identity as 'unavailable' -- precisely the deployment
where a reviewer is least able to work out what produced a result.

Run from the build scripts while the repository checkout is still available:

    python installer/write_build_stamp.py <repo-root> [--dry-run]
    python installer/write_build_stamp.py <repo-root> --payload <staged-payload-dir>

Both destinations are needed, because the two applications resolve the wrappers
differently: vcornea-gui/run_gui.py puts the payload's vivarium-vcornea directory
at the front of sys.path, so V-Cornea imports the PAYLOAD copy, while angio-gui
does not and falls through to SITE-PACKAGES. Stamping only one would leave the
other reporting an unknown revision.

The provenance module is loaded from the REPOSITORY by path, not imported from the
installed package, so that its git lookup starts inside the checkout.

Never fails the build: a missing stamp costs provenance, not function.
"""
import importlib
import importlib.util
import pathlib
import sys

PACKAGES = [
    ('vivarium_vcornea', 'vivarium-vcornea'),
    ('vivarium_angio', 'vivarium-angio'),
]


def _load_provenance(src_path):
    spec = importlib.util.spec_from_file_location(f'_prov_{src_path.parent.parent.name}',
                                                  str(src_path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv):
    if not argv:
        print(__doc__)
        return 0
    repo = pathlib.Path(argv[0]).resolve()
    dry_run = '--dry-run' in argv
    payload = None
    if '--payload' in argv:
        idx = argv.index('--payload')
        if idx + 1 < len(argv):
            payload = pathlib.Path(argv[idx + 1]).resolve()

    written = 0
    for pkg_name, dir_name in PACKAGES:
        src = repo / dir_name / pkg_name / 'utils' / 'provenance.py'
        if not src.is_file():
            print(f"   build stamp: {pkg_name}: no provenance module at {src}; skipped")
            continue

        if payload is not None:
            # Stamp the staged source copy rather than the installed package.
            dest = payload / dir_name / pkg_name
            if not dest.is_dir():
                print(f"   build stamp: {pkg_name}: no staged copy at {dest}; skipped")
                continue
        else:
            try:
                installed = importlib.import_module(pkg_name)
                dest = pathlib.Path(installed.__file__).resolve().parent
            except Exception as exc:
                print(f"   build stamp: {pkg_name}: not importable in this env ({exc}); skipped")
                continue

        try:
            prov = _load_provenance(src)
            identity = prov.code_provenance(src.parent)
            label = identity.get('describe') or identity.get('commit_short') or identity.get('source')
            if dry_run:
                print(f"   build stamp: {pkg_name}: would write {dest / prov.BUILD_STAMP_NAME} "
                      f"({label})")
                written += 1
                continue
            out = prov.write_build_stamp(dest, src.parent)
            if out:
                print(f"   build stamp: {pkg_name}: {out} ({label})")
                written += 1
            else:
                # write_build_stamp returns None when there is no git checkout to
                # describe -- e.g. building from an exported tarball.
                print(f"   build stamp: {pkg_name}: no git checkout to record; skipped")
        except Exception as exc:
            print(f"   build stamp: {pkg_name}: failed ({exc}); skipped")

    if not written:
        print("   build stamp: nothing recorded; packaged runs will report code "
              "identity as unavailable")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
