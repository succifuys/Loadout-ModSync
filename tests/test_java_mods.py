import pytest
from dntsne.java_mods import approvals, selected_jars


def test_selected_build_inherits_common_and_approves_exact_jar(tmp_path):
    folder = tmp_path / 'Example'
    (folder/'common').mkdir(parents=True)
    (folder/'common/mod.info').write_text('id=example\njavaPkgName=example.java\n')
    for version in ('42', '42.20', '42.22'):
        (folder/version).mkdir()
        (folder/version/'mod.info').write_text('javaJarFile=plugin.jar\n')
        (folder/version/'plugin.jar').write_bytes(version.encode())
    jars = selected_jars(tmp_path, ['example'])
    assert jars == [('example.java', folder/'42.20/plugin.jar')]
    first = approvals(tmp_path, ['example'])['mods'][0]
    (folder/'42.20/plugin.jar').write_bytes(b'updated')
    assert approvals(tmp_path, ['example'])['mods'][0]['jar_hash'] != first['jar_hash']
    assert selected_jars(tmp_path, ['other']) == []


def test_java_jar_cannot_escape_own_folder(tmp_path):
    folder = tmp_path/'Example/42'
    folder.mkdir(parents=True)
    (tmp_path/'foreign.jar').write_bytes(b'foreign')
    (folder/'mod.info').write_text('id=example\njavaPkgName=example\njavaJarFile=../../foreign.jar\n')
    with pytest.raises(ValueError, match='inside its own'):
        selected_jars(tmp_path, ['example'])
