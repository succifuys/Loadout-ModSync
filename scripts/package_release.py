"""Package only application artifacts; never include Workshop, secrets or audit input."""
import hashlib
import importlib.metadata as metadata
import json
import shutil
import sys
import zipfile
from pathlib import Path

root=Path(__file__).resolve().parent.parent
version='0.1.3'
bundle=root/'dist'/version/'DNTSNE-ModSync'
assert (bundle/'DNTSNE-ModSync.exe').is_file()
shutil.copytree(root/'docs',bundle/'docs',dirs_exist_ok=True)
for name in ('README.md','readmeJP.md','THIRD-PARTY-NOTICES.md'):
    shutil.copyfile(root/name,bundle/name)
notices=bundle/'THIRD-PARTY-LICENSES'
notices.mkdir(exist_ok=True)
packages=['flet','flet-desktop','oauthlib','repath','msgpack','httpx','httpcore','anyio','idna','certifi','click','rich','markdown-it-py','mdurl','six','colorama','typing-extensions','pygments','setuptools','packaging','pyinstaller']
for name in packages:
    distribution=metadata.distribution(name)
    for item in distribution.files or ():
        upper=Path(item).name.upper()
        if not upper.startswith(('LICENSE','LICENCE','COPYING','NOTICE')):
            continue
        path=distribution.locate_file(item)
        if path.is_file() and path.suffix not in ('.py','.pyc'):
            destination=notices/name/str(item).replace('..','_')
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(path,destination)
python_license=Path(sys.base_prefix)/'LICENSE.txt'
if python_license.is_file():
    shutil.copyfile(python_license,notices/'Python-LICENSE.txt')
portable=root/f'dist/DNTSNE-ModSync-{version}-candidate-Windows-x64.zip'
with zipfile.ZipFile(portable,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
    for path in sorted(bundle.rglob('*')):
        if path.is_file():
            assert not path.is_symlink()
            archive.write(path,path.relative_to(bundle.parent).as_posix())
source_zip=root/f'dist/DNTSNE-ModSync-{version}-source.zip'
with zipfile.ZipFile(source_zip,'w',compression=zipfile.ZIP_DEFLATED) as archive:
    for folder in ('dntsne','scripts','tests','docs','deploy'):
        for path in sorted((root/folder).rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts:
                archive.write(path,path.relative_to(root).as_posix())
    for name in ('README.md','readmeJP.md','THIRD-PARTY-NOTICES.md','pyproject.toml','requirements-server.lock','requirements-client.lock','client_app.py','.gitignore'):
        archive.write(root/name,name)
server_zip=root/f'dist/DNTSNE-ModSync-{version}-server.zip'
with zipfile.ZipFile(server_zip,'w',compression=zipfile.ZIP_DEFLATED) as archive:
    for folder in ('dntsne','deploy'):
        for path in sorted((root/folder).rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts:
                archive.write(path,path.relative_to(root).as_posix())
    for name in ('README.md','pyproject.toml','requirements-server.lock',
                 'readmeJP.md','docs/SERVER-SETUP.md','docs/SERVER-SETUP-JP.md','docs/PROTOCOL.md','docs/LICENSES.md','THIRD-PARTY-NOTICES.md',
                 'scripts/install-server.sh','scripts/uninstall-server.sh'):
        archive.write(root/name,name)
checksums={p.name:hashlib.file_digest(p.open('rb'),'sha256').hexdigest() for p in (portable,source_zip,server_zip,bundle/'DNTSNE-ModSync.exe')}
(root/f'dist/SHA256SUMS-{version}.json').write_text(json.dumps(checksums,indent=2),encoding='utf-8')
print(json.dumps({p.name:p.stat().st_size for p in (portable,source_zip,server_zip)},indent=2))
