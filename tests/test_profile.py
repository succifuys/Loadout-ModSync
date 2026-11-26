import sqlite3
from contextlib import closing
from pathlib import Path
from dntsne.profile import import_preferences
from dntsne.state import default_home, read_json


def test_preferences_and_favorites_import_once_with_backup(tmp_path):
    source=tmp_path/'usual'
    target=tmp_path/'dedicated'
    (source/'Lua').mkdir(parents=True)
    (source/'db').mkdir()
    target.mkdir()
    (source/'options.ini').write_text('usual graphics')
    (source/'Lua/keysB42.ini').write_text('usual controls')
    (target/'options.ini').write_text('previous dedicated graphics')
    with closing(sqlite3.connect(source/'db/ServerListSteam.db')) as db:
        db.execute('create table favorites(name text)')
        db.execute("insert into favorites values ('friend server')")
        db.commit()
    copied=import_preferences(target,source)
    assert set(copied)=={'options.ini','Lua/keysB42.ini','db/ServerListSteam.db'}
    assert (target/'options.ini').read_text()=='usual graphics'
    with closing(sqlite3.connect(target/'db/ServerListSteam.db')) as db:
        assert db.execute('select name from favorites').fetchone()==('friend server',)
    assert (source/'options.ini').read_text()=='usual graphics'
    assert any(p.read_text()=='previous dedicated graphics' for p in target.glob('.dntsne-preferences-backups/*/options.ini'))
    (target/'options.ini').write_text('my newer dedicated graphics')
    assert import_preferences(target,source)==[]
    assert (target/'options.ini').read_text()=='my newer dedicated graphics'
    assert import_preferences(target,source,force=True)


def test_import_does_not_copy_mods_worlds_or_override_missing_source(tmp_path):
    source=tmp_path/'usual'
    (source/'mods').mkdir(parents=True)
    (source/'mods/private.lua').write_text('mod')
    target=tmp_path/'dedicated'
    assert import_preferences(target,source)==[]
    assert not (target/'mods').exists()
    assert import_preferences(target,tmp_path/'missing')==[]


def test_application_state_is_independent_of_release_folder(tmp_path,monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path/'appdata'))
    first=tmp_path/'0.1.1'
    second=tmp_path/'0.1.2'
    first.mkdir();second.mkdir()
    monkeypatch.chdir(first)
    before=default_home()
    monkeypatch.chdir(second)
    assert default_home()==before==tmp_path/'appdata/DNTSNE/ModSync'
