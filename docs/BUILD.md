# Build Loadout on Windows

[English README](../README.md) · [Русский](../ReadMe-RU.md) · [日本語](../ReadMe-JP.md)

Use **Windows x64** and **x64 Python 3.12 or newer**. Run these from the root of the extracted source or the Windows EXE build kit, in PowerShell. The scripts make a `.venv` and install the pinned dependencies. If you already have a venv with those dependencies, pass its Python path with `-Python`.

### One file, no `_internal` next to it

```powershell
.\scripts\build-exe.ps1
```

The result is `dist\Loadout-ModSync.exe`. It extracts its runtime into Windows' temporary folder when it starts, not into the mods folder. If you distribute it, ship `dist\THIRD-PARTY-LICENSES` and `THIRD-PARTY-NOTICES.md` with it too.

### Portable ZIP and the release set

Use the **full source checkout**, not the build kit:

```powershell
.\scripts\build-client.ps1
.\.venv\Scripts\python.exe scripts/package_release.py
```

The folder build produces `dist\0.1.3\DNTSNE-ModSync\DNTSNE-ModSync.exe`. Keep its `_internal` folder next to it. The packager makes four ZIPs in `dist`: `Windows-x64` (ready-to-run folder build), `Source` (everything), `Server-Linux` (server tools, no game), and `Windows-EXE-Build` (client source and build scripts, not an EXE). It also writes `SHA256SUMS-0.1.3.json`. The standalone EXE from the first section is a separate build. Nothing is uploaded automatically.

Both build scripts run the packaged `--self-test`. To run the source tests from a full checkout:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-server.lock pytest httpx
.\.venv\Scripts\python.exe -m pytest
```

If PowerShell blocks a downloaded ZIP's scripts, inspect the files first. Unblock the trusted ZIP in its Properties and extract it again; don't turn off your system-wide execution policy.
