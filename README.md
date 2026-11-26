# Loadout ModSync

[СЛОНЯРАМ!!!](ReadMe-RU.md) · [日本語](ReadMe-JP.md)

Если вы не слоняры, я запрещаю вам читать.

**Keep your Project Zomboid mods in sync with the server.**

[Download for Windows x64](https://github.com/succifuys/Loadout-ModSync/releases/download/v0.1.3/Loadout-ModSync.exe) | [Release notes](https://github.com/succifuys/Loadout-ModSync/releases/tag/v0.1.3) | [Server setup](docs/SERVER-SETUP-EN.md)

Loadout is a Windows launcher and a companion service for Project Zomboid dedicated servers. SteamCMD still gets the mods from Workshop. Players get the files **the server is using**, even if Workshop has a newer version.

The first sync downloads the whole pack. Later syncs only download missing or changed files. One changed texture doesn't mean downloading the whole pack again.

**Tested with:** Windows x64 and Project Zomboid Build 42.22.2. For other game builds, try it on a test server first.

## I just want to play

1. Download [`Loadout-ModSync.exe`](https://github.com/succifuys/Loadout-ModSync/releases/download/v0.1.3/Loadout-ModSync.exe) and run it. No installer, Python or separate `_internal` folder required. If your admin gave you the older portable ZIP instead, extract it in full and leave `_internal` next to `DNTSNE-ModSync.exe`.
2. Start Steam, close the game and join your admin's **Tailscale** network. You need the same game build as the server.
3. In **Settings**, paste the ModSync URL into **Tailscale server URL**. If the launcher can't find PZ, set **Game folder**. In Steam: **Properties → Installed Files → Browse**. Leave **Mod folder** alone. Steam Workshop already has enough going on.
4. Hit **Save → Synchronize** and wait. Leave some extra disk space for temporary files.
5. Click **Launch Project Zomboid** and join from the game's menu. Use the **game address and port**, not the ModSync URL. For vanilla or your usual Workshop mods, just launch from Steam.

**Won't work?** Check the game version, the URL and Tailscale first. If your friends can't sync either, don't reinstall half your PC; ask the admin. If the game still complains after syncing, close it and try **Settings → Full verification (reads every file)** before deleting anything. Use **Open log file** if you need to show someone the error. Keep passwords and private addresses out of public issues.

## I run the server

Clone the repo or use the source archive from [Releases](https://github.com/succifuys/Loadout-ModSync/releases/tag/v0.1.3). It's the mod service, not a copy of the game. You need an existing PZ server in a compatible Docker image, plus Linux, Docker Compose and systemd.

1. Back up the world, INI and Compose files. Try this on a copy. Your friends did not spend three weeks building a wall so you could test on production.
2. Check the paths in `deploy/compose.modsync.yaml` and run `sudo sh scripts/install-server.sh --approved`. This installs the ModSync service. **It doesn't set up or restart PZ.**
3. Adapt `deploy/compose.pz.override.example.yaml` for your PZ server. Keep `WORKSHOP_ITEMS` in the startup settings for SteamCMD. After startup, check that the generated game INI has an empty `WorkshopItems=` line and still has the right `Mods=` and `Map=`.
4. Check that you're allowed to share the mods, then enable downloads and set your Tailscale IP in the ModSync settings. Follow the [server setup guide](docs/SERVER-SETUP-EN.md) for the exact commands. When `/api/v1/status` says `ready`, give players a URL like `http://100.64.0.1:8787` with your server's real Tailscale IP. Keep the API off the public internet.

To update the pack, stop PZ normally and let SteamCMD update the mods on the next startup. Wait for `ready`, then tell players to hit **Synchronize**. Don't update the Workshop folder while PZ is running.

## I want to build it

Get the source from GitHub. Open PowerShell in that folder and run `.\scripts\build-exe.ps1`. You'll need x64 Python 3.12 or newer. Out comes `dist/Loadout-ModSync.exe`. No `_internal` next to it, and no launcher files dumped into your mods folder. For the folder ZIP and checksums, see the [build guide](docs/BUILD.md).

**Next up:** let a separate machine serve the downloads. For now, ModSync runs alongside PZ on the same host.

[Code, dependencies, and mod redistribution](docs/LICENSES.md)
