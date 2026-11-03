"""MC source, native preparation and guarded application lifecycle commands."""
from pathlib import Path
import argparse
import json
import sys
import subprocess
import zipfile
import zlib
import mc_deployment as mc

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['describe', 'preflight', 'prepare', 'status', 'client-prepare', 'client-status', 'neoforge-status', 'console', 'application-start', 'application-stop', 'application-status', 'operation-status', 'supervision-status', 'export-source', 'install-source', 'verify-source', 'check-source'])
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--refresh', action='store_true', help='Recheck and archive an existing preparation record')
    parser.add_argument('--archive', type=Path, help='Source ZIP destination for export, or input for install')
    parser.add_argument('--sha256', help='Expected source ZIP SHA256 from the reviewed export/release')
    parser.add_argument('--node', type=Path, help='Existing native Node 24.22.1 executable for check-source')
    parser.add_argument('--output', help='New project-relative outputs/.../... folder for check-source evidence')
    parser.add_argument('--timeout', type=float, help='Managed-service readiness deadline in seconds (1–1800), application-start only')
    parser.add_argument('--journal', type=Path, help='Existing game journal for optional history maintenance in console')
    parser.add_argument('--runtime', type=Path, help='Reviewed native maintenance runtime configuration, console with --journal only')
    args = parser.parse_args()
    if (args.journal is not None or args.runtime is not None) and args.action != 'console':
        parser.error('--journal and --runtime are only valid with console')
    if args.runtime is not None and args.journal is None:
        parser.error('--runtime requires --journal')
    if args.timeout is not None and args.action != 'application-start':
        parser.error('--timeout is only valid with application-start')
    if args.refresh and args.action != 'prepare':
        parser.error('--refresh is only valid with prepare')
    if args.action == 'check-source':
        if args.node is None or args.output is None:
            parser.error('check-source requires --node and --output')
    elif args.node is not None or args.output is not None:
        parser.error('--node and --output are only valid with check-source')
    if args.action in {'export-source', 'install-source'}:
        if args.archive is None or (args.action == 'install-source' and args.sha256 is None):
            parser.error('Source export requires --archive; source install also requires --sha256')
    elif args.archive is not None or args.sha256 is not None:
        parser.error('--archive and --sha256 are only valid with source package actions')
    if args.action == 'export-source' and args.sha256 is not None:
        parser.error('--sha256 is only valid with install-source')
    root = args.root.resolve()
    try:
        if args.action == 'neoforge-status':
            from mc_neoforge import runtime_status
            value = runtime_status(root)
        elif args.action in {'client-prepare', 'client-status'}:
            from mc_client import ClientError, base_result, prepare, status
            try:
                value = prepare(root) if args.action == 'client-prepare' else status(root)
            except ClientError as error:
                value = {**base_result(), 'ok':False, 'code':str(error)}
        elif args.action == 'console':
            from mc_application_console import serve
            from mc_maintenance_dependencies import MaintenanceError
            try:
                serve(root, journal=args.journal, runtime_config=args.runtime)
                return 0
            except MaintenanceError as error:
                value = {'ok':False, 'code':error.code, 'outcome':error.outcome,
                         'services_started':False, 'models_loaded':False}
        elif args.action.startswith('application-'):
            from mc_application import Application
            app = Application(root)
            if args.action == 'application-start':
                value = app.start(timeout=args.timeout if args.timeout is not None else 1800)
            elif args.action == 'application-stop':
                value = app.stop()
            else:
                value = app.status()
        elif args.action == 'verify-source':
            source = mc.source_identity(root)
            value = {'ok':True, 'scope':'PUBLIC_SOURCE_FILES_ONLY_NOT_NATIVE_READINESS',
                     'source_kind':source['kind'], 'source_files':len(source['files']),
                     'source_snapshot_sha256':source['snapshot_sha256'],
                     'test_source_files':sum(name.startswith('tests/') for name in source['files']),
                     'services_started':False, 'models_loaded':False, 'native_environment_prepared':False}
        elif args.action == 'check-source':
            from mc_source_checks import run
            value = run(root, node=args.node, output=args.output)
        elif args.action == 'operation-status':
            from native_operation import status
            value = status(root)
        elif args.action == 'supervision-status':
            from native_supervision import status
            value = status(root)
        elif args.action == 'export-source':
            value = mc.export_source(root, args.archive)
        elif args.action == 'install-source':
            value = mc.install_source(args.archive, root, args.sha256)
        elif args.action == 'describe':
            value = mc.load_profile(root)[3]
        elif args.action == 'preflight':
            value, _ = mc.preflight(root)
        elif args.action == 'prepare':
            value = mc.prepare(root, refresh=args.refresh)
        else:
            _, selected = mc.base_guard().contract(root)
            value = {'ok':True, **mc.validate_prepared(root, selected),
                     'scope':'PREPARATION_RECORD_VALID_NOT_LIVE_SERVICE_STATUS'}
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0 if value.get('ok', True) else 1
    except (mc.PreparationError, OSError, ValueError, KeyError, TypeError, RuntimeError, zipfile.BadZipFile,
            zlib.error, EOFError, subprocess.SubprocessError) as error:
        code = str(error) if isinstance(error, mc.PreparationError) else 'MC_NATIVE_CONFIGURATION_UNAVAILABLE'
        print(json.dumps({'ok':False, 'code':code, 'services_started':False, 'models_loaded':False}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    sys.exit(main())
