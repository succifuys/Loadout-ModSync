import sys

if __name__=='__main__':
    if '--self-test' in sys.argv:
        try:
            from dntsne.selftest import main
            result=main()
        except Exception:
            import traceback
            from pathlib import Path
            # Explicit opt-in path for support diagnostics; never silently overwrite game data.
            if '--report' in sys.argv:
                report=Path(sys.argv[sys.argv.index('--report')+1])
                with report.open('x',encoding='utf-8') as file:
                    file.write(traceback.format_exc())
            result=1
        raise SystemExit(result)
    elif '--cli' in sys.argv:
        from dntsne.cli import main
        index=sys.argv.index('--cli')
        raise SystemExit(main(sys.argv[index+1:]))
    elif '--gui-smoke-report' in sys.argv:
        from dntsne.gui import run
        run(smoke_report=sys.argv[sys.argv.index('--gui-smoke-report')+1])
    else:
        from dntsne.gui import run
        run()

