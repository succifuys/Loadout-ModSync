import importlib.util
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "package_release", ROOT / "scripts/package_release.py"
)
release = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release)


def assert_markdown_links(files):
    for file, text in files.items():
        for target in re.findall(r"\]\(([^)]+)\)", text):
            link = urlsplit(target)
            if link.scheme or not link.path:
                continue
            # Normalize '..' without depending on the host OS's separators.
            parts = []
            for part in (PurePosixPath(file).parent / unquote(link.path)).parts:
                if part == "..":
                    assert parts, (file, target)
                    parts.pop()
                elif part != ".":
                    parts.append(part)
            dest = "/".join(parts)
            assert dest in files, (file, target)
            if link.fragment:
                headings = re.findall(r"^#+ (.+)$", files[dest], re.MULTILINE)
                slugs = [re.sub(r"[^\w -]", "", h.lower()).replace(" ", "-") for h in headings]
                assert unquote(link.fragment) in slugs, (file, target)


def test_markdown_links():
    files = {f: (ROOT / f).read_text(encoding="utf-8") for f in release.README + release.DOCS}
    assert_markdown_links(files)


def test_release_layout_and_private_files(tmp_path):
    paths = (*release.README, *release.DOCS, *release.CLIENT, *release.SERVER,
             *release.TESTS, ".gitattributes", ".gitignore", "scripts/package_release.py")
    for path in set(paths):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, target)
    dist = tmp_path / "dist"
    bundle = dist / "0.1.3/DNTSNE-ModSync"
    (bundle / "_internal").mkdir(parents=True)
    (bundle / "THIRD-PARTY-LICENSES").mkdir()
    for relative in ("DNTSNE-ModSync.exe", "_internal/runtime.dll", "THIRD-PARTY-LICENSES/license.txt"):
        (bundle / relative).write_bytes(b"test fixture, not executable code")
    for relative in (".env", "deploy/.env", "scripts/token.txt", "tests/world.zip", "dist/0.1.3/DNTSNE-ModSync/private.ini"):
        (tmp_path / relative).write_text("must not ship", encoding="utf-8")
    portable, source, server, build = release.package(tmp_path)
    for path in (portable, source, server, build):
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            assert archive.testzip() is None
            assert all(not name.endswith((".env", "token.txt", "world.zip", "private.ini")) for name in names)
            docs = {f: archive.read(f).decode("utf-8") for f in names if f.endswith(".md")}
            assert_markdown_links(docs)
    with zipfile.ZipFile(portable) as archive:
        assert "DNTSNE-ModSync/_internal/runtime.dll" in archive.namelist()
    with zipfile.ZipFile(server) as archive:
        assert "dntsne/gui.py" not in archive.namelist()
        assert "scripts/install-server.sh" in archive.namelist()
    with zipfile.ZipFile(build) as archive:
        assert "scripts/build-exe.ps1" in archive.namelist()
        assert "scripts/windows-build-common.ps1" in archive.namelist()
        assert "dntsne/server.py" not in archive.namelist()
        kit = tmp_path / "extracted-build-kit"
        archive.extractall(kit)
    # Run in a fresh Python process with no checkout imports. This is the
    # same self-test the generated EXE runs from its isolated bundle.
    check = subprocess.run(
        [sys.executable, "-I", "-c",
         "import runpy,sys; sys.path.insert(0,'.'); sys.argv=['client_app.py','--self-test']; "
         "runpy.run_path('client_app.py',run_name='__main__')"],
        cwd=kit, capture_output=True, text=True, timeout=20, check=True,
    )
    assert json.loads(check.stdout)["result"] == "passed"
    sums = json.loads((dist / "SHA256SUMS-0.1.3.json").read_text(encoding="utf-8"))
    assert set(sums) == {path.name for path in (portable, source, server, build)}
