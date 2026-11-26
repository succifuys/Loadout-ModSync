# Install ModSync on a PZ server

[English README](../README.md) · [Русский](SERVER-SETUP.md) · [日本語](SERVER-SETUP-JP.md)

This example is for **Linux, Docker Engine with Compose, systemd, and host Python 3.10+**. It needs a PZ image with WorkshopManager, `/scripts/config/main.py`, `/scripts/server-base-variables.sh` and `/scripts/init-server.sh`. The installer does not install the game. The observer and download service run on the same host as PZ. Use the full checkout or the **Server-Linux** ZIP.

### 1. Back up, then set up a test server

Save and stop the game normally before backing up the world, INI and existing Compose files. Use a separate host, or a test container and copied world with distinct ports and paths. Never point two containers at the same save. The defaults assume container `pz-server`, game UDP port `16261`, and INI `/srv/servers/pz/data/Server/DNTSNE.ini`. The observer checks the live game, not just whether Docker says the container is up. On a shared host, these fixed service/container names must not collide with anything you already use.

### 2. Install the local download service

Review the Workshop bind mount in `deploy/compose.modsync.yaml`. It needs the same host Workshop directory that PZ uses. If your game root or container name differs, set `--root` and `--container` on the `ExecStart` line of `deploy/dntsne-monitor.service` before installing. That root must contain `data` and `workshop`; the port and INI filename above are fixed in the current observer. Use a compatible layout or adapt the observer on your test setup first. From the extracted project root:

```sh
sudo sh scripts/install-server.sh --approved
```

This installs the service in `/opt/dntsne-modsync`, with downloads off and port `8787` listening only on loopback. It doesn't touch the PZ project. If installation fails after copying files, check the Docker/systemd error and correct it in the installed copy. The installer won't overwrite an existing installation.

### 3. Connect the test game to the same files

1. Copy `deploy/compose.pz.override.example.yaml` into your game Compose project as `compose.modsync.override.yaml`. Match its service name and host paths to your setup. The Workshop root must be mounted read/write inside PZ at `/root/.local/share/Steam/steamapps/workshop`. Create that host directory's `.dntsne-local-mods` subdirectory before starting PZ. It must be on the same filesystem as Workshop; the game gets a read-only view of that prepared folder.
2. Extract the stock `/scripts/init-server.sh` from your exact PZ image, for example with `docker cp` from a temporary stopped container made with `docker create`. Do not edit the image. From the ModSync source root, make a separate launcher file:

   ```sh
   python3 deploy/patch-pz-init.py /path/to/original-init-server.sh /path/to/dntsne-init.sh
   ```

   Use the actual output path in the override. The example mounts this file even if you aren't using a Java agent. If the patcher doesn't recognize your image's script, stop and adapt or choose another image. The Java agent example is commented out; only enable it if your pack needs it. Make sure the mounted entrypoint is executable on Linux (`sudo chmod +x /opt/dntsne-modsync/deploy/pz-entrypoint.sh`).
3. Keep the normal `WORKSHOP_ITEMS`, `MODS` and `MAP` startup settings. The first holds numeric Workshop IDs. The second holds Mod IDs. Render the merged configuration from your game directory:

   ```sh
   docker compose -f compose.yaml -f compose.modsync.override.yaml config --quiet
   ```

   Adjust filenames to match your setup. Use those same files to start the **test** PZ service. In its generated INI, check that `WorkshopItems=` is empty while `Mods=` and `Map=` still have the right values.

### 4. Turn on downloads

Check permission to distribute each mod. Then create a private `/opt/dntsne-modsync/.env` (mode 600) with these two entries. Replace the example address with the server's **Tailscale IPv4**:

```dotenv
DNTSNE_BIND_IP=100.64.0.1
DNTSNE_LICENSES_APPROVED=1
```

```sh
sudo chmod 600 /opt/dntsne-modsync/.env
sudo docker compose --env-file /opt/dntsne-modsync/.env \
  -f /opt/dntsne-modsync/deploy/compose.modsync.yaml up -d --build
```

Only allow your players to reach the API over Tailscale. Don't publish it or RCON to the internet. Give players two separate things: the ModSync URL (for example `http://100.64.0.1:8787`) and the PZ game address and port.

### 5. Verify and roll back if needed

From another machine on the tailnet, run `curl -fsS http://100.64.0.1:8787/api/v1/status` with your real address. Look for `"state":"ready"`, `pz_version` and `revision`. If it isn't ready, see `sudo journalctl -u dntsne-monitor -n 80 --no-pager` and the ModSync Compose logs. Don't treat an HTTP 200 or Docker's healthy flag as proof that downloads are ready.

Test a first download, an unchanged sync with no downloads, then a one-mod update with a test PZ restart. Join the test game after each change. SteamCMD updates Workshop during startup; don't change those files under a running game. Wait for `ready` before telling players to sync again.

To stop the download service, run `sudo sh scripts/uninstall-server.sh --approved` from the source root. It preserves files and does not stop PZ. To revert the PZ integration itself, stop the test PZ normally, remove the override and restore its original configuration. Don't overwrite a new world save with an old one by accident.
