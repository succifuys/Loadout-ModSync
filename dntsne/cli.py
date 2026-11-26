import argparse
import json
import sys
import time
from pathlib import Path
from .common import SyncError
from .game import find_games, launch, require_compatibility, check_original_jar, default_mods
from .network import Network
from .state import default_home, setup_log
from .sync import Sync


def main(argv=None):
    p=argparse.ArgumentParser(description='Loadout ModSync')
    p.add_argument('command',choices=('discover','status','check','update','launch','clean-cache','uninstall'))
    p.add_argument('--server',help='ModSync URL, e.g. http://pz-host:8787')
    p.add_argument('--game',type=Path)
    p.add_argument('--mods',type=Path)
    p.add_argument('--home',type=Path,default=default_home())
    p.add_argument('--consent-conflicts',action='store_true',help='Consent to backing up and replacing EACH reported conflicting file')
    p.add_argument('--confirm-uninstall',action='store_true')
    p.add_argument('--rate-limit',type=int,default=0,help='Bytes/sec, 0 = unlimited')
    p.add_argument('--full-verification',action='store_true',help='Hash every local file instead of using verified metadata')
    args=p.parse_args(argv)
    try:
        if args.command=='discover':
            print(json.dumps([str(x) for x in find_games()],ensure_ascii=False))
            return 0
        if not args.server and args.command not in ('clean-cache','uninstall'):
            raise SyncError('Specify the ModSync URL with --server')
        net=Network(args.server or 'http://127.0.0.1:8787',rate_limit=args.rate_limit)
        if args.command=='status':
            print(json.dumps(net.status(),ensure_ascii=False))
            return 0
        games=find_games()
        game=args.game or (games[0] if games else None)
        if not game:
            raise SyncError('Select --game')
        engine=Sync(net,args.mods or default_mods(),args.home)
        setup_log(args.home)
        if args.command=='clean-cache':
            engine.clean_cache()
            return 0
        if args.command=='uninstall':
            if not args.confirm_uninstall:
                raise SyncError('Use --confirm-uninstall after reviewing ownership registry')
            engine.uninstall()
            return 0
        status=net.status()
        if status['state']!='ready':
            raise SyncError('Game server: '+status['state'])
        if status.get('pz_version'):
            require_compatibility(game,status['pz_version'])
        plan=engine.check(full_check=args.full_verification)
        require_compatibility(game,plan.manifest.pz_version)
        print(json.dumps(dict(revision=plan.manifest.revision,folders=len(plan.manifest.folders),files=len(plan.manifest.files),download_files=len(plan.changed),download_bytes=plan.download_size,obsolete_files=plan.removed,conflicts=plan.conflicts),ensure_ascii=False,indent=2))
        if args.command=='update':
            import logging
            log=logging.getLogger('dntsne.cli')
            current=None
            last=0.0
            transferred=0
            def phase(name,done,total):
                nonlocal current,last
                now=time.monotonic()
                if name!=current or now-last>=20 or (total and done==total):
                    log.info('%s (%s/%s)',name,done,total)
                    current,last=name,now
            def transfer(_path,_offset,_size,delta):
                nonlocal current,last,transferred
                transferred+=max(0,delta)
                now=time.monotonic()
                if current!='Downloading' or now-last>=20:
                    log.info('Downloading (%s MiB received)',round(transferred/1048576))
                    current,last='Downloading',now
            engine.update(plan,progress=transfer,consent_conflicts=args.consent_conflicts,phase_progress=phase)
            log.info('Update finished; %s MiB received',round(transferred/1048576))
        elif args.command=='launch':
            if plan.changed or plan.removed or plan.conflicts or engine.registry()['revision']!=plan.manifest.revision:
                raise SyncError('Update the managed installation before launching')
            check_original_jar(game)
            launch(game,engine.mods)
        return 0
    except (SyncError,OSError) as e:
        print(str(e),file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())

