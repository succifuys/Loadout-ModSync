# Loadout ModSync 0.1.3 | Validation reliability pass

## Windows test setup
- Server: PZ 42.22.2, 266 mod folders, 149,447 files.
- The old client started scanning at 23:56:57 JST and first logged its install plan at 00:10:28. The dedicated local profile did not have the mods installed. A first download of approximately 4 GiB is expected; it is not evidence of the separate SteamCMD delta bug.
- A cold benchmark on the same saved live manifest, on the same Windows PC, with a temporary empty profile: planning 1.88 s; preflight validation 2.03 s; 151 progress notifications. These timings do not include parsing the manifest, opening the UI, network transfer, staging, installation or final integrity checks.

## Changes
- Inventory the top-level mod folders per pass. Skip repeated filesystem calls under absent folders. Recheck a fresh inventory under lock and use strict per-target checks before replacing files.
- Show distinct progress for preflight, download-cache inventory, preinstall recheck, staging, installation and final verification. Report bytes received rather than using the install size as a transfer total.
- Check game compatibility before the long scan and again against the pinned manifest.
- Walk only existing path components and reject symlinks/junctions. Preserve per-file SHA-256 verification, conflict consent, revision pinning and transaction rollback.
- Deduplicate bundle candidates before checking the local cache. Reuse a verified cache file and hash new bundle data on arrival. Keep staging and post-install verification separate.
- Keep the old portable client as a rollback option. Both versions share the same dedicated profile, so do not run both at once.

## Release validation
- Run the Windows Python suite and both the packaged self-test and the hidden GUI smoke test.
- Verify first sync, no-change sync, one changed Workshop file, restoration after an interrupted transaction and preservation of a newly added personal file.
- In the one-mod scenario, measure local files checked separately from bytes downloaded. Do not count a new server revision alone as a file transfer.
- The production game server and Workshop configuration were not changed by this client release. Do not update, restart or delete anything on production as part of the test.
