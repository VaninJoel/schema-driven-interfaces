"""Run identity: which parameter definitions, and which code, produced a run.

Two *separate* identifiers are recorded, because they answer different questions
and have different failure modes:

  * **schema fingerprint** — a SHA-256 content hash over the canonical form of the
    process's ``ports_schema()``. Answers "were these two runs interpreted under
    the same parameter definitions?". It is derived from the schema itself, so it
    cannot drift from what the code declares, and it is available in every
    deployment. This is the identifier requirement 2.5.1 calls for.

  * **code provenance** — the git commit of the working tree (with an explicit
    dirty flag) resolving to a public commit URL, or, when there is no checkout, a
    build stamp written at packaging time. Answers "where do I obtain the code
    that ran?".

Why not use the commit alone as the schema version: the packaged conda-pack
installer ships the application payload *without* ``.git`` (see installer/build.sh),
so an end user's runs would have no commit at all; and a commit taken from a dirty
working tree names a state that was never actually executed. The fingerprint has
neither problem, so it is the primary identifier and the commit is corroborating
provenance rather than a substitute for it.

Stdlib only, and every function is best-effort: provenance capture must never be
able to fail a simulation run.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# git is invoked with a short timeout so a wedged/networked git can never stall a
# run, and (on Windows) without a console window so the GUI does not flash a shell.
_GIT_TIMEOUT_S = 5
_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if sys.platform == 'win32' else 0

# Written next to the payload by the installer build so packaged (non-git)
# deployments still carry code identity. See write_build_stamp().
BUILD_STAMP_NAME = '_build_stamp.json'

# Truncation of the schema hash. 64 bits is ample to distinguish schema revisions
# and keeps the value readable in reports and file names; the full digest adds no
# practical discrimination here.
_FINGERPRINT_HEX = 16


# =============================================================================
# Schema fingerprint
# =============================================================================

def _canonical(obj: Any) -> Any:
    """Deterministic, JSON-safe projection of a schema fragment.

    Dict keys are sorted so the hash does not depend on declaration order.
    Callables (e.g. the ``_conditional_display`` predicates used by other
    processes in this repository) are replaced by a stable marker rather than
    raising, so this helper works against any ports_schema().
    """
    if isinstance(obj, dict):
        return {str(k): _canonical(v)
                for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))}
    if isinstance(obj, (list, tuple)):
        return [_canonical(v) for v in obj]
    if callable(obj):
        return f"<callable:{getattr(obj, '__name__', 'lambda')}>"
    if obj is None or isinstance(obj, (str, bool, int, float)):
        return obj
    return str(obj)


def schema_fingerprint(schema: Dict[str, Any], *, port: str = 'inputs') -> str:
    """Content hash of one port of a ports_schema(), as ``sha256:<hex>``.

    ANY change to a parameter's declared semantics — its default, unit, ranges,
    description, ontology term, or annotations — produces a new fingerprint. That
    is deliberate: the schema is the parameter documentation, so a run recorded
    under a given fingerprint was interpreted under exactly those definitions.
    Adding or removing a parameter changes it too.
    """
    section = (schema or {}).get(port, {})
    blob = json.dumps(_canonical(section), sort_keys=True,
                      separators=(',', ':'), ensure_ascii=False)
    digest = hashlib.sha256(blob.encode('utf-8')).hexdigest()[:_FINGERPRINT_HEX]
    return f'sha256:{digest}'


# =============================================================================
# Code provenance (git checkout -> build stamp -> unavailable)
# =============================================================================

def _run_git(args, cwd, allow_empty: bool = False) -> Optional[str]:
    """Run a git command, returning stripped stdout, or None on failure.

    `allow_empty` distinguishes "ran fine and produced no output" from "failed".
    That difference matters for queries whose empty result is the answer — e.g.
    `branch -r --contains <sha>` prints nothing when no remote branch contains the
    commit, which is exactly the case the caller needs to detect. Without it an
    unpushed commit is indistinguishable from a git error.
    """
    try:
        proc = subprocess.run(
            ['git', *args], cwd=str(cwd), capture_output=True, text=True,
            timeout=_GIT_TIMEOUT_S, creationflags=_NO_WINDOW,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None  # git absent, not executable, or timed out
    if proc.returncode != 0:
        return None
    out = proc.stdout.strip()
    return out if (out or allow_empty) else None


def _normalize_remote(url: Optional[str]) -> Optional[str]:
    """Normalize a git remote to a browsable https URL (``git@host:a/b.git`` ->
    ``https://host/a/b``) so the recorded provenance is directly resolvable."""
    if not url:
        return None
    u = url.strip()
    if u.startswith('git@') and ':' in u:
        host, _, path = u[4:].partition(':')
        u = f'https://{host}/{path}'
    elif u.startswith('ssh://git@'):
        u = 'https://' + u[len('ssh://git@'):]
    if u.endswith('.git'):
        u = u[:-4]
    return u or None


def _read_build_stamp(start: Path) -> Optional[Dict[str, Any]]:
    """Find and read a build stamp at or above `start` (bounded search)."""
    for d in [start, *start.parents][:8]:
        f = d / BUILD_STAMP_NAME
        if f.is_file():
            try:
                data = json.loads(f.read_text(encoding='utf-8'))
                return data if isinstance(data, dict) else None
            except Exception:
                return None
    return None


def code_provenance(start_path=None) -> Dict[str, Any]:
    """Identify the code that is running. Never raises.

    Resolution order:
      1. a git checkout containing this module — records commit, branch, commit
         timestamp, remote, and whether the working tree was dirty;
      2. a build stamp written at packaging time (the packaged installer case);
      3. ``{'source': 'unavailable'}`` — recorded explicitly rather than guessed.

    ``repo_root`` is always reported alongside a git result so a reader can see
    which checkout the commit refers to (guarding the pathological case of an
    installation living inside an unrelated repository).
    """
    here = Path(start_path) if start_path else Path(__file__).resolve().parent

    commit = _run_git(['rev-parse', 'HEAD'], here)
    if commit:
        # Modified TRACKED files and merely-untracked files are reported
        # separately, because they carry different risk. A tracked modification
        # means the commit demonstrably does not describe the code that ran. An
        # untracked file usually does not affect the run at all (editor state,
        # scratch output, tool configuration) — treating it as equivalent would
        # leave every run flagged as modified and make the flag meaningless.
        dirty = bool(_run_git(['status', '--porcelain', '--untracked-files=no'], here))
        untracked = [ln[3:] for ln in (_run_git(['status', '--porcelain'], here) or '')
                     .splitlines() if ln.startswith('??')]
        remote = _normalize_remote(_run_git(['config', '--get', 'remote.origin.url'], here))

        # A commit URL is only worth publishing if the commit is actually reachable
        # from the remote. Constructing it from the hash alone yields a link that
        # 404s for every unpushed commit -- an archive asserting a source location
        # that does not exist. None means "could not determine" (no remote, or git
        # failed); a stale remote-tracking ref can only produce a false NEGATIVE,
        # which under-claims rather than over-claims.
        on_remote = None
        remote_contains = _run_git(['branch', '-r', '--contains', commit], here,
                                   allow_empty=True)
        if remote_contains is not None:
            on_remote = any(ln.strip() for ln in remote_contains.splitlines())

        info: Dict[str, Any] = {
            'source': 'git',
            'commit': commit,
            'commit_short': commit[:7],
            'dirty': dirty,
            'untracked_present': bool(untracked),
            'commit_on_remote': on_remote,
            # Human-facing version anchored to the repository's tag history when
            # tags exist (e.g. v0.1.0-3-g44e563d), so a released build reports the
            # release it came from rather than a bare hash.
            'describe': _run_git(['describe', '--tags', '--always', '--dirty'], here),
            'branch': _run_git(['rev-parse', '--abbrev-ref', 'HEAD'], here),
            'committed_at': _run_git(['show', '-s', '--format=%cI', 'HEAD'], here),
            'remote_url': remote,
            'repo_root': _run_git(['rev-parse', '--show-toplevel'], here),
        }
        # A URL is published only when the commit both describes the code that ran
        # (clean tree) and can actually be fetched by a reader (present on the
        # remote). Anything less is recorded as a note rather than a link.
        notes = []
        if dirty:
            notes.append(
                'Tracked files were modified relative to this commit when the run '
                'executed. The commit identifies the nearest committed state only '
                'and does NOT fully describe the code that produced this result.')
        if on_remote is False:
            notes.append(
                'This commit exists only in the local repository and has not been '
                'pushed, so the source is not publicly resolvable. Push the commit '
                'before distributing this archive.')
        elif on_remote is None and remote:
            notes.append(
                'Could not determine whether this commit is present on the remote; '
                'no source link is asserted.')
        if untracked:
            # Not a warning about the result, but recorded so an auditor can see
            # the workspace was not pristine.
            notes.append(
                f'{len(untracked)} untracked path(s) were present in the working '
                'tree and are not described by this commit.')

        info['commit_url'] = (f'{remote}/commit/{commit}'
                              if (remote and not dirty and on_remote) else None)
        if notes:
            info['note'] = ' '.join(notes)
        return info

    stamp = _read_build_stamp(here)
    if stamp:
        return {'source': 'build_stamp', **stamp}

    return {
        'source': 'unavailable',
        'note': ('No git checkout and no build stamp were found alongside the '
                 'installed package; code identity was not recorded for this run.'),
    }


# =============================================================================
# Combined record + helpers
# =============================================================================

def run_provenance(schema: Optional[Dict[str, Any]] = None, *,
                   port: str = 'inputs', start_path=None) -> Dict[str, Any]:
    """The provenance block embedded in run metadata and the OMEX archive."""
    record: Dict[str, Any] = {'code': code_provenance(start_path)}
    if schema is not None:
        record['schema_fingerprint'] = schema_fingerprint(schema, port=port)
    return record


def short_label(record: Optional[Dict[str, Any]]) -> str:
    """One-line human-readable identity for report headers and figure captions,
    e.g. ``code 25c5c26 (modified) | schema sha256:1a2b3c4d5e6f7a8b``."""
    if not record:
        return 'code unrecorded | schema unrecorded'
    code = record.get('code') or {}
    src = code.get('source')
    if src == 'git':
        code_txt = f"code {code.get('describe') or code.get('commit_short', '?')}"
        if code.get('dirty'):
            code_txt += ' (modified)'
    elif src == 'build_stamp':
        code_txt = f"build {code.get('commit_short') or code.get('built_at') or '?'}"
    else:
        code_txt = 'code unrecorded'
    return f"{code_txt} | schema {record.get('schema_fingerprint', 'unrecorded')}"


def write_build_stamp(dest_dir, source_dir=None) -> Optional[Path]:
    """Freeze the current git identity into ``<dest_dir>/_build_stamp.json``.

    Called by the installer build scripts while the repository checkout is still
    available, so the packaged application (which ships without ``.git``) can
    still report which commit it was built from.
    """
    dest = Path(dest_dir)
    prov = code_provenance(source_dir or Path(__file__).resolve().parent)
    if prov.get('source') != 'git':
        return None
    stamp = {k: v for k, v in prov.items() if k != 'source'}
    stamp['stamped_by'] = 'vivarium_vcornea.utils.provenance'
    try:
        from datetime import datetime, timezone
        stamp['built_at'] = datetime.now(timezone.utc).isoformat()
        dest.mkdir(parents=True, exist_ok=True)
        out = dest / BUILD_STAMP_NAME
        out.write_text(json.dumps(stamp, indent=2), encoding='utf-8')
        return out
    except Exception:
        return None


if __name__ == '__main__':
    # `python -m vivarium_vcornea.utils.provenance --write-stamp <dir>` gives the
    # installer build scripts a one-line hook; with no arguments it prints the
    # provenance of the current checkout for inspection.
    if len(sys.argv) >= 3 and sys.argv[1] == '--write-stamp':
        path = write_build_stamp(sys.argv[2])
        print(f'build stamp: {path}' if path else 'build stamp: not written (no git checkout)')
    else:
        print(json.dumps(code_provenance(), indent=2))
