import os
import pytest
from dntsne.local_mods import prepare, MARKER


def source(tmp_path):
    folder = tmp_path / 'content/108600/123/mods/Example/42.0'
    folder.mkdir(parents=True)
    (folder / 'mod.info').write_text('id=example\n')
    (folder / 'payload.txt').write_text('version A')
    return folder


def test_real_layer_shares_inodes_and_replaces_deleted_files(tmp_path):
    original = source(tmp_path)
    first = prepare(tmp_path, ['123'], ['example'])
    layer = tmp_path / '.dntsne-local-mods'
    linked = layer / 'Example/42.0/payload.txt'
    assert not linked.is_symlink()
    assert os.path.samefile(linked, original / 'payload.txt')
    assert first['files']['Example/42.0/payload.txt']['size'] == 9
    # SteamCMD's replace-on-refresh keeps the old runtime inode unchanged.
    (original / 'payload.txt').unlink()
    (original / 'new.txt').write_text('version B')
    assert linked.read_text() == 'version A'
    prepare(tmp_path, ['123'], ['example'])
    assert not linked.exists()
    assert os.path.samefile(layer / 'Example/42.0/new.txt', original / 'new.txt')


def test_missing_id_and_foreign_layer_fail_before_replacement(tmp_path):
    source(tmp_path)
    with pytest.raises(ValueError, match='Active IDs missing'):
        prepare(tmp_path, ['123'], ['missing'])
    layer = tmp_path / '.dntsne-local-mods'
    layer.mkdir()
    (layer / 'personal.txt').write_text('preserve')
    with pytest.raises(ValueError, match='unowned'):
        prepare(tmp_path, ['123'], ['example'])
    assert (layer / 'personal.txt').read_text() == 'preserve'


def test_duplicate_folder_never_selects_arbitrary_package(tmp_path):
    source(tmp_path)
    (tmp_path / 'content/108600/456/mods/Example').mkdir(parents=True)
    with pytest.raises(ValueError, match='Duplicate'):
        prepare(tmp_path, ['123', '456'], ['example'])
