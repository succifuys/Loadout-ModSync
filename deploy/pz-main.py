#!/usr/bin/env python3
"""DNTSNE extension of meshi-team's scripts/config/main.py (see THIRD-PARTY-NOTICES.md).

The WorkshopManager still downloads/updates via Steam on container startup.
With DNTSNE_LOCAL_MODS=1, the configured game loads real hard-linked local mod folders
and advertises an empty WorkshopItems list to connecting clients.

DO NOT deploy to a live world without testing local Java mods and maps first.
"""

import json
import os
import re
from pathlib import Path

from server_manager import ProjectZomboidServerManager
from utils import load_custom_variables, log_section, setup_logger
from workshop_manager import ProjectZomboidWorkshopManager

MANAGED_FILENAME = ".dntsne-local-mod-links.json"


def enabled(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in ("1", "true", "yes", "on")


def _workshop_content_root(variables: dict) -> Path:
    base = Path(str(variables.get("STEAM_WORKSHOP_DEFAULT_DIR") or "/root/.local/share/Steam/steamapps/workshop"))
    appid = str(variables.get("ZOMBOID_GAME_APP_ID") or "108600")
    if not appid.isdigit():
        raise RuntimeError("Invalid ZOMBOID_GAME_APP_ID")
    # Supports both the Steam Workshop root and its already-expanded content root.
    if base.name == appid and base.parent.name == "content":
        return base
    if base.name == "content":
        return base / appid
    return base / "content" / appid


def _managed_state(cache_dir: Path):
    file = cache_dir / MANAGED_FILENAME
    if not file.exists():
        return file, {}
    saved = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(saved, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in saved.items()):
        raise RuntimeError(f"Invalid managed link index: {file}")
    return file, saved


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _remove_managed_links(cache_dir: Path, workshop_root: Path, logger) -> None:
    state_path, previous = _managed_state(cache_dir)
    if not previous:
        return
    destination = cache_dir / "mods"
    for name, original in previous.items():
        link = destination / name
        if link.is_symlink():
            if not _is_within(link, workshop_root):
                raise RuntimeError(f"Refusing to remove external symlink: {link}")
            # Do not remove a symlink that someone has repointed manually.
            if str(link.readlink()) == original:
                link.unlink()
    state_path.unlink(missing_ok=True)
    logger.info("[DNTSNE] Removed previously managed local symlinks (Workshop mode)")


def _link_local_mods(variables: dict, installed_ids, logger) -> None:
    from dntsne_local_mods import prepare
    cache_dir = Path(str(variables.get("CACHE_DIR") or os.getenv("CACHE_DIR") or "/root/Zomboid"))
    content = _workshop_content_root(variables)
    workshop = content.parent.parent
    active = [x.strip() for x in (os.getenv("MODS") or "").split(";") if x.strip()]
    requested = [x.strip() for x in (os.getenv("WORKSHOP_ITEMS") or "").split(";") if x.strip()]
    if set(requested) != set(map(str, installed_ids)):
        raise RuntimeError("WorkshopManager selection differs from requested packages")
    result = prepare(workshop, requested, active)
    index = cache_dir / ".dntsne-local-mods.json"
    temp = index.with_suffix(".tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    temp.replace(index)
    logger.info("[DNTSNE] Real local folders prepared: %d; shared files: %d", len(result["folders"]), len(result["files"]))


def _force_empty_workshop_items(variables: dict) -> None:
    """Verify output and correct an INI writer that skips empty values."""
    cache_dir = Path(str(variables.get("CACHE_DIR") or os.getenv("CACHE_DIR") or "/root/Zomboid"))
    server_name = str(variables.get("SERVER_NAME") or os.getenv("SERVER_NAME") or "servertest").replace(" ", "-")
    ini = cache_dir / "Server" / (server_name + ".ini")
    if not ini.exists():
        raise RuntimeError(f"INI not found; cannot guarantee empty WorkshopItems: {ini}")
    text = ini.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    matching = [i for i, line in enumerate(lines) if line.startswith("WorkshopItems=")]
    if len(matching) != 1:
        raise RuntimeError(f"Expected exactly one WorkshopItems= in {ini}, found {len(matching)}")
    idx = matching[0]
    ending = "\r\n" if lines[idx].endswith("\r\n") else "\n"
    lines[idx] = "WorkshopItems=" + ending
    if lines != text.splitlines(keepends=True):
        tmp = ini.with_suffix(".dntsne.tmp")
        tmp.write_text("".join(lines), encoding="utf-8")
        tmp.replace(ini)
    verify = ini.read_text(encoding="utf-8")
    if not any(line == "WorkshopItems=" for line in verify.splitlines()):
        raise RuntimeError(f"Failed to clear WorkshopItems in {ini}")


def main() -> None:
    logger = setup_logger()
    variables = load_custom_variables()
    server_folder = variables.get("SERVER_DIR")
    steam_workshop_folder = variables.get("STEAM_WORKSHOP_DEFAULT_DIR")

    log_section(logger, "Workshop management")
    wk_manager = ProjectZomboidWorkshopManager(server_folder, steam_workshop_folder)
    wk_manager.process_workshop_items()

    variables["WORKSHOP_ITEMS"] = ";".join(str(x) for x in wk_manager.server_workshop_items)
    variables["MAP"] = wk_manager.get_maps_string()
    if os.getenv("MAP"):
        variables["MAP"] = os.getenv("MAP")
    if wk_manager.active_mods:
        variables["MODS"] = wk_manager.get_mods_string()

    log_section(logger, "Server configuration")
    local_mode = enabled("DNTSNE_LOCAL_MODS")
    cache_dir = Path(str(variables.get("CACHE_DIR") or os.getenv("CACHE_DIR") or "/root/Zomboid"))
    workshop_root = _workshop_content_root(variables)
    if local_mode:
        _link_local_mods(variables, wk_manager.server_workshop_items, logger)
        variables["WORKSHOP_ITEMS"] = ""
        logger.info("[DNTSNE] Local mode enabled: WorkshopItems will be empty in server INI")
    else:
        _remove_managed_links(cache_dir, workshop_root, logger)
        logger.info("[DNTSNE] Standard Workshop mode enabled")

    server_manager = ProjectZomboidServerManager(variables)
    server_manager.apply_configuration()
    if local_mode:
        _force_empty_workshop_items(variables)


if __name__ == "__main__":
    main()
