# Loadout ModSync

[СЛОНЯРАМ!!!](ReadMe-RU.md) · [日本語](ReadMe-JP.md)

Если вы не слоняры, я запрещаю вам читать.

Loadout is a Windows launcher and a mod download service for Project Zomboid dedicated servers. SteamCMD gets the mods from Workshop. Loadout gives you the files **the server is actually using**, even if Workshop got another update ten minutes ago. (For God's sake, please stop hotfixing one misaligned pixel in every Viewpoint add-on.)

The first sync downloads the whole pack. After that, you only get what's missing or changed. One new texture shouldn't mean downloading Sam Altman's entire VRAM chip photo album again.

This is **0.1.3**. Tested on Windows with a **Build 42.22.2** server. Other builds? Try them on a test server first.

## I just want to play

1. Get the Windows x64 build from your admin or **Releases**, if it's up there. If you got `Loadout-ModSync.exe`, just run it. If you got the old ZIP with `DNTSNE-ModSync.exe`, unzip the whole thing and leave `_internal` next to it.
2. Start Steam, close the game and join your admin's **Tailscale** network. You need the same game build as the server.
3. In **Settings**, paste the ModSync URL into **Tailscale server URL**. If the launcher can't find PZ, set **Game folder**. In Steam: **Properties → Installed Files → Browse**. Leave **Mod folder** alone. Steam Workshop already has enough going on.
4. Hit **Save → Synchronize** and wait. Leave some extra disk space for temporary files.
5. Click **Launch Project Zomboid** and join from the game's menu. Use the **game address and port**, not the ModSync URL. For vanilla or your usual Workshop mods, just launch from Steam.

**Won't work?** Check the game version, the URL and Tailscale first. If your friends can't sync either, don't reinstall half your PC; ask the admin. If the game still complains after syncing, close it and try **Settings → Full verification (reads every file)** before deleting anything. Use **Open log file** if you need to show someone the error. Keep passwords and private addresses out of public issues.

## I run the server

Use **Server-Linux** for this. It's the mod service, not a copy of the game. You need an existing PZ server in a compatible Docker image, plus Linux, Docker Compose and systemd.

1. Back up the world, INI and Compose files. Try this on a copy. Your friends did not spend three weeks building a wall so you could test on production.
2. Check the paths in `deploy/compose.modsync.yaml` and run `sudo sh scripts/install-server.sh --approved`. This installs the ModSync service. **It doesn't set up or restart PZ.**
3. Adapt `deploy/compose.pz.override.example.yaml` for your PZ server. Keep `WORKSHOP_ITEMS` in the startup settings for SteamCMD. After startup, check that the generated game INI has an empty `WorkshopItems=` line and still has the right `Mods=` and `Map=`.
4. Check that you're allowed to share the mods, then enable downloads and set your Tailscale IP in the ModSync settings. Follow the [server setup guide](docs/SERVER-SETUP.md) for the exact commands. When `/api/v1/status` says `ready`, give players the download URL. Keep the API off the public internet.

To update the pack, stop PZ normally and let SteamCMD update the mods on the next startup. Wait for `ready`, then tell players to hit **Synchronize**. Don't update the Workshop folder while PZ is running.

## I want to build it

Unzip **Windows-EXE-Build**, open PowerShell there and run `.\build-exe.ps1`. You'll need 64-bit Python 3.12 or newer. The result is `dist/Loadout-ModSync.exe`. No `_internal` next to it, and no launcher files dumped into your mods folder.

**Next up:** let a separate machine serve the downloads. For now, ModSync runs alongside PZ on the same host.
