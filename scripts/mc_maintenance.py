"""Native offline MC maintenance; no game, model, DSH or broadcast service starts."""
from pathlib import Path
import argparse
import json
import sqlite3
import subprocess
import sys

import mc_deployment as mc
from mc_maintenance_dependencies import MaintenanceError, application_fence, capture
from mc_maintenance_core import MaintenanceCoordinator, NativeRuntime

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['dependencies', 'status', 'preview', 'apply', 'reconcile', 'serve'])
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--journal', type=Path, help='Absolute existing journal directory for this installation')
    parser.add_argument('--runtime', type=Path, help='Reviewed native Java/classpath configuration; defaults to the private installation file')
    parser.add_argument('--plan', help='Reviewed coordinator plan filename, not a path')
    parser.add_argument('--sha256', help='Exact coordinator plan file SHA256 returned by preview')
    args = parser.parse_args()
    if args.action in {'apply', 'reconcile'}:
        if not args.plan or not args.sha256:
            parser.error('apply/reconcile require --plan and --sha256')
    elif args.plan is not None or args.sha256 is not None:
        parser.error('--plan and --sha256 are only valid with apply/reconcile')
    if args.action != 'dependencies' and args.journal is None:
        parser.error('status/preview/apply/reconcile/serve require --journal')
    try:
        root = args.root.resolve()
        _, _, _, profile = mc.load_profile(root)
        source = mc.source_identity(root)
        database = root / profile['inference']['state_path'] / 'game/game.sqlite3'
        if args.action == 'dependencies':
            with application_fence(database) as db:
                value = capture(db)
        else:
            runtime = NativeRuntime(args.runtime or root / 'configs/mc-maintenance.private.json')
            binding = {'root': str(root), 'profile_sha256': mc.sha(root / mc.PROFILE),
                       'source_snapshot_sha256': source['snapshot_sha256'], 'state_path': profile['inference']['state_path']}
            coordinator = MaintenanceCoordinator(database, args.journal, runtime, binding)
            if args.action == 'serve':
                from mc_maintenance_console import serve
                def verify_installation():
                    try:
                        current = mc.source_identity(root)
                        if current['snapshot_sha256'] != source['snapshot_sha256'] or mc.sha(root / mc.PROFILE) != binding['profile_sha256']:
                            raise MaintenanceError('MC_MAINTENANCE_INSTALLATION_CHANGED')
                    except subprocess.TimeoutExpired as error:
                        raise MaintenanceError('MC_MAINTENANCE_SOURCE_PROBE_TIMEOUT') from error
                    except (mc.PreparationError, OSError, subprocess.SubprocessError) as error:
                        raise MaintenanceError('MC_MAINTENANCE_INSTALLATION_INVALID') from error
                    runtime.verify()
                serve(root, coordinator, verify_installation)
                return 0
            if args.action in {'apply', 'reconcile'}:
                value = getattr(coordinator, args.action)(args.plan, args.sha256)
            else:
                value = getattr(coordinator, args.action)()
        print(json.dumps({'ok': True, **value, 'services_started': False, 'models_loaded': False,
                          'automatic_input_authorized': False}, ensure_ascii=False, indent=2))
        return 0
    except (MaintenanceError, mc.PreparationError, OSError, ValueError, KeyError, TypeError,
            sqlite3.Error, subprocess.SubprocessError) as error:
        code = error.code if isinstance(error, MaintenanceError) else str(error) if isinstance(error, mc.PreparationError) else 'MC_MAINTENANCE_UNAVAILABLE'
        print(json.dumps({'ok': False, 'code': code, 'outcome': getattr(error, 'outcome', 'not_dispatched'),
                          'services_started': False, 'models_loaded': False, 'automatic_input_authorized': False}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    sys.exit(main())
