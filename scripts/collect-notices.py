"""Collect available build dependency notices; review before publishing."""
import shutil
import sys
from importlib import metadata
from pathlib import Path

out = Path(sys.argv[1])
packages = (
    'flet', 'flet-desktop', 'flet-cli', 'oauthlib', 'repath', 'msgpack',
    'httpx', 'httpcore', 'anyio', 'idna', 'certifi', 'click', 'rich',
    'markdown-it-py', 'mdurl', 'six', 'colorama', 'typing-extensions',
    'pygments', 'setuptools', 'packaging', 'pyinstaller',
)
for name in packages:
    try:
        distribution = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        # Optional platform and build-time packages may not be installed.
        continue
    for item in distribution.files or ():
        if not item.name.upper().startswith(('LICENSE', 'LICENCE', 'COPYING', 'NOTICE')):
            continue
        if item.suffix in ('.py', '.pyc') or item.is_absolute() or '..' in item.parts:
            continue
        path = Path(distribution.locate_file(item))
        if path.is_file():
            dest = out / name / item
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dest)
python_license = Path(sys.base_prefix) / 'LICENSE.txt'
if python_license.is_file():
    out.mkdir(exist_ok=True, parents=True)
    shutil.copyfile(python_license, out / 'Python-LICENSE.txt')
