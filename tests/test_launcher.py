from pathlib import Path
import pytest
from dntsne.game import launch_arguments
from dntsne.common import SyncError


def test_local_profile_excludes_workshop_search_and_preserves_spaces(tmp_path):
    game = tmp_path/'Steam Games/ProjectZomboid'
    mods = tmp_path/'DNTSNE Profile/mods'
    command = launch_arguments(game,mods)
    assert command == [str(game/'ProjectZomboid64.exe'),'--','-cachedir='+str(mods.parent),'-modfolders','mods']
    assert all('workshop' not in arg.lower() for arg in command)


def test_unconfirmed_folder_cannot_silently_launch_wrong_mods(tmp_path):
    game = tmp_path/'game'
    with pytest.raises(SyncError,match='mods folder'):
        launch_arguments(game,tmp_path/'custom-name')
    with pytest.raises(SyncError,match='outside'):
        launch_arguments(game,game/'mods')
