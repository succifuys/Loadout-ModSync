import ctypes
import os
import re
import struct
import subprocess
import tempfile
import zipfile
from pathlib import Path
from .common import SyncError, digest, safe_join


def find_games():
    roots=[]
    if os.name=='nt':
        import winreg
        for hive,key,value in ((winreg.HKEY_CURRENT_USER,r'Software\Valve\Steam','SteamPath'),(winreg.HKEY_LOCAL_MACHINE,r'SOFTWARE\WOW6432Node\Valve\Steam','InstallPath')):
            try:
                with winreg.OpenKey(hive,key) as handle:
                    roots.append(Path(winreg.QueryValueEx(handle,value)[0]))
            except OSError:
                pass
    roots.append(Path(os.getenv('ProgramFiles(x86)',r'C:\Program Files (x86)'))/'Steam')
    libraries=list(roots)
    for root in roots:
        vdf=root/'steamapps/libraryfolders.vdf'
        if vdf.exists():
            for path in re.findall(r'"path"\s*"((?:\\.|[^"\\])*)"',vdf.read_text(errors='replace')):
                libraries.append(Path(path.replace('\\\\','\\')))
    games=[]
    for library in libraries:
        folder=library/'steamapps/common/ProjectZomboid'
        if (folder/'projectzomboid.jar').is_file() and folder not in games:
            games.append(folder)
    return games


def verify_game(game):
    if not (game/'projectzomboid.jar').is_file():
        raise SyncError('Project Zomboid installation not found')
    if not any((game/name).exists() for name in ('ProjectZomboid64.exe','ProjectZomboid32.exe')):
        raise SyncError('Windows game executable not found')


def jar_versions(game):
    from .java_version import versions_from_core
    with zipfile.ZipFile(game/'projectzomboid.jar') as jar:
        data=jar.read('zombie/core/Core.class')
    return versions_from_core(data)


def require_compatibility(game,version):
    verify_game(game)
    try:
        versions=jar_versions(game)
    except (OSError,ValueError,KeyError,IndexError,struct.error) as e:
        raise SyncError('Cannot verify game version') from e
    if versions!={version}:
        raise SyncError('Game version does not match the server build')


def check_original_jar(game):
    backup=game/'projectzomboid.jar.dntsne-original.bak'
    if backup.exists() and digest(backup)!=digest(game/'projectzomboid.jar'):
        raise SyncError('Game JAR differs from original backup. Verify original files before connecting.')


def game_running():
    if os.name!='nt':
        raise SyncError('Process detection is implemented for Windows only')
    from ctypes import wintypes
    class PROCESSENTRY32W(ctypes.Structure):
        _fields_=[('dwSize',wintypes.DWORD),('cntUsage',wintypes.DWORD),('th32ProcessID',wintypes.DWORD),('th32DefaultHeapID',ctypes.c_size_t),('th32ModuleID',wintypes.DWORD),('cntThreads',wintypes.DWORD),('th32ParentProcessID',wintypes.DWORD),('pcPriClassBase',wintypes.LONG),('dwFlags',wintypes.DWORD),('szExeFile',wintypes.WCHAR*260)]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes=[wintypes.DWORD,wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype=wintypes.HANDLE
    kernel.Process32FirstW.argtypes=[wintypes.HANDLE,ctypes.POINTER(PROCESSENTRY32W)]
    kernel.Process32NextW.argtypes=[wintypes.HANDLE,ctypes.POINTER(PROCESSENTRY32W)]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    snapshot=kernel.CreateToolhelp32Snapshot(2,0)
    if snapshot==ctypes.c_void_p(-1).value:
        raise SyncError('Cannot inspect running processes')
    try:
        entry=PROCESSENTRY32W()
        entry.dwSize=ctypes.sizeof(entry)
        if not kernel.Process32FirstW(snapshot,ctypes.byref(entry)):
            raise SyncError('Cannot inspect running processes')
        while True:
            name=entry.szExeFile.lower()
            # Conservatively block Java launchers too; never update unknown running JVMs.
            if name.startswith('projectzomboid') or name in ('java.exe','javaw.exe'):
                return True
            if not kernel.Process32NextW(snapshot,ctypes.byref(entry)):
                break
        return False
    finally:
        kernel.CloseHandle(snapshot)


def write_probe(mods):
    safe_join(mods,'.dntsne-write-check')
    mods.mkdir(parents=True,exist_ok=True)
    try:
        with tempfile.TemporaryFile(dir=mods):
            pass
    except PermissionError as e:
        raise SyncError('No write permission. Choose a verified writable mod path or explicitly run with administrator approval.') from e


def default_mods():
    from .state import default_home
    return default_home()/'game-profile/mods'


def launch_arguments(game, mods):
    game, mods = Path(game).absolute(), Path(mods).absolute()
    if mods.name.lower()!='mods':
        raise SyncError('B42 requires a mods folder directly inside its selected cache directory')
    if mods.parent == game:
        raise SyncError('Select the dedicated game profile, outside the Steam installation')
    # Supported by client MainScreenState, NOT by dedicated GameServer.
    args = [str(game/'ProjectZomboid64.exe')]
    agent = safe_join(mods,'ZombieBuddy/libs/ZombieBuddy.jar')
    if agent.is_file():
        config = mods.parent/'.zombie_buddy'
        if ',' in str(config) or '=' in str(agent):
            raise SyncError('Java agent profile path contains an unsupported argument separator')
        args.append('-javaagent:'+str(agent)+'=policy=prompt,config_dir='+str(config))
    return args + ['--', '-cachedir='+str(mods.parent), '-modfolders', 'mods']


def launch(game, mods, log_path=None):
    verify_game(game)
    check_original_jar(game)
    if os.name!='nt':
        raise SyncError('Launcher is implemented for Windows only')
    environment = dict(os.environ)
    # Resolve instrument.dll's bundled JVM dependencies on Windows without
    # installing an agent DLL/JAR or changing the game's launcher JSON.
    environment['PATH'] = str(game/'jre64/bin') + os.pathsep + environment.get('PATH','')
    if log_path is not None:
        log_path=Path(log_path)
        log_path.parent.mkdir(parents=True,exist_ok=True)
        with log_path.open('ab') as output:
            return subprocess.Popen(launch_arguments(game,mods),cwd=game,env=environment,stdout=output,stderr=subprocess.STDOUT)
    return subprocess.Popen(launch_arguments(game,mods),cwd=game,env=environment)
