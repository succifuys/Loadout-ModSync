"""Build release ZIPs from explicit application file lists."""
import hashlib
import json
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ("README.md", "ReadMe-RU.md", "ReadMe-JP.md",
          "THIRD-PARTY-NOTICES.md")
DOCS = (
    "docs/BUILD.md", "docs/LICENSES.md", "docs/PROTOCOL.md", "docs/RELEASE-0.1.3.md",
    "docs/SERVER-SETUP.md", "docs/SERVER-SETUP-EN.md", "docs/SERVER-SETUP-JP.md",
)
SERVER = (
    "dntsne/__init__.py", "dntsne/common.py", "dntsne/host_monitor.py",
    "dntsne/java_mods.py", "dntsne/local_mods.py", "dntsne/manifest.py",
    "dntsne/server.py", "dntsne/server_index.py",
    "deploy/Dockerfile", "deploy/compose.modsync.yaml", "deploy/compose.pz.override.example.yaml",
    "deploy/dntsne-monitor.service", "deploy/patch-pz-init.py", "deploy/pz-entrypoint.sh",
    "deploy/pz-main.py", "scripts/install-server.sh", "scripts/uninstall-server.sh",
    "requirements-server.lock", "pyproject.toml", ".dockerignore",
)
CLIENT = (
    "client_app.py", "requirements-client.lock", "dntsne/__init__.py",
    "dntsne/cli.py", "dntsne/common.py", "dntsne/game.py", "dntsne/gui.py",
    "dntsne/java_version.py", "dntsne/manifest.py", "dntsne/network.py",
    "dntsne/profile.py", "dntsne/selftest.py", "dntsne/server_index.py", "dntsne/state.py", "dntsne/sync.py",
    "scripts/build-client.ps1", "scripts/build-exe.ps1", "scripts/collect-notices.py",
    "scripts/install-client.ps1", "scripts/uninstall-client.ps1", "scripts/windows-build-common.ps1",
)
TESTS = (
    "tests/TEST_BY_CODEX.md", "tests/conftest.py", "tests/test_bundles.py",
    "tests/test_gui.py", "tests/test_java_mods.py", "tests/test_junctions.py",
    "tests/test_launcher.py", "tests/test_live_api.py", "tests/test_local_mods.py",
    "tests/test_manifest_server.py", "tests/test_monitor.py", "tests/test_network.py",
    "tests/test_profile.py", "tests/test_release_packaging.py", "tests/test_sync.py",
    "tests/test_validation_progress.py",
)


def write_zip(target, entries):
    # Check the inputs before opening/truncating the artifact.
    entries = list(entries)
    for path, _ in entries:
        if not path.is_file() or path.is_symlink():
            raise SystemExit(f"Missing or unsafe release input: {path}")
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, name in entries:
            archive.write(path, name)


def artifact_files(folder):
    if not folder.is_dir() or folder.is_symlink() or folder.is_junction():
        raise SystemExit(f"Missing or unsafe build folder: {folder}")
    for path in sorted(folder.iterdir()):
        if path.is_symlink() or path.is_junction():
            raise SystemExit(f"Unsafe build entry: {path}")
        if path.is_dir():
            yield from artifact_files(path)
        elif path.is_file():
            yield path


def package(root=ROOT):
    with (root / "pyproject.toml").open("rb") as stream:
        version = tomllib.load(stream)["project"]["version"]
    dist = root / "dist"
    bundle = dist / version / "DNTSNE-ModSync"
    exe = bundle / "DNTSNE-ModSync.exe"
    if not exe.is_file():
        raise SystemExit("Build the portable client first: scripts/build-client.ps1")

    def files(names, prefix=""):
        return ((root / name, prefix + name) for name in sorted(set(names)))

    def built(folder):
        return ((path, "DNTSNE-ModSync/" + path.relative_to(bundle).as_posix())
                for path in artifact_files(bundle / folder))

    prefix = f"Loadout-ModSync-{version}"
    portable = dist / f"{prefix}-Windows-x64.zip"
    source = dist / f"{prefix}-Source.zip"
    server = dist / f"{prefix}-Server-Linux.zip"
    build = dist / f"{prefix}-Windows-EXE-Build.zip"
    write_zip(portable, [
        (exe, "DNTSNE-ModSync/DNTSNE-ModSync.exe"),
        *built("_internal"), *built("THIRD-PARTY-LICENSES"),
        *files(README + DOCS, "DNTSNE-ModSync/"),
    ])
    write_zip(source, files(README + DOCS + CLIENT + SERVER + TESTS +
                            (".gitattributes", ".gitignore", "scripts/package_release.py")))
    write_zip(server, files(README + DOCS + SERVER))
    write_zip(build, files(README + DOCS + CLIENT + ("pyproject.toml",)))
    artifacts = (portable, source, server, build)
    checksums = {}
    for path in artifacts:
        with path.open("rb") as stream:
            checksums[path.name] = hashlib.file_digest(stream, "sha256").hexdigest()
    (dist / f"SHA256SUMS-{version}.json").write_text(
        json.dumps(checksums, indent=2) + "\n", encoding="utf-8"
    )
    return artifacts


if __name__ == "__main__":
    print(*(str(path) for path in package()), sep="\n")
