"""Code identity: a source file that is not under version control is part of the
code that ran, so it makes the recorded tree dirty."""
from vivarium_angio.utils import provenance as prov


def _fake_git(untracked_in_package, tracked_modified=False, other_untracked=('notes.txt',)):
    def run(args, cwd, allow_empty=False):
        if args[:2] == ['rev-parse', 'HEAD']:
            return 'a' * 40
        if args[:2] == ['status', '--porcelain']:
            if '--untracked-files=no' in args:
                return ' M tracked.py' if tracked_modified else None
            if '--untracked-files=all' in args:
                return '\n'.join(f'?? {p}' for p in untracked_in_package) or None
            return '\n'.join(f'?? {p}' for p in other_untracked) or None
        if args[:2] == ['branch', '-r']:
            return '  origin/main'
        if args[:2] == ['config', '--get']:
            return 'https://example.org/owner/repo.git'
        return 'x'
    return run


def test_untracked_source_inside_the_package_makes_the_tree_dirty(monkeypatch):
    monkeypatch.setattr(prov, '_run_git', _fake_git(
        ['pkg/utils/new_module.py', 'pkg/utils/scratch.txt', 'pkg/out.png']))
    info = prov.code_provenance()
    assert info['dirty'] is True and info['dirty_tracked'] is False
    assert info['untracked_source_files'] == ['pkg/utils/new_module.py']
    assert 'not under version control' in info['note'] and info['commit_url'] is None


def test_other_untracked_paths_are_noted_but_do_not_dirty_the_tree(monkeypatch):
    monkeypatch.setattr(prov, '_run_git', _fake_git(['pkg/utils/scratch.txt']))
    info = prov.code_provenance()
    assert info['dirty'] is False and info['untracked_source_files'] == []
    assert info['untracked_present'] is True and info['commit_url']


def test_tracked_modification_is_still_dirty(monkeypatch):
    monkeypatch.setattr(prov, '_run_git', _fake_git([], tracked_modified=True))
    info = prov.code_provenance()
    assert info['dirty'] is True and info['dirty_tracked'] is True
