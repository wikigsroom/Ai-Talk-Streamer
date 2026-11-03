"""Reproduce the packaged MC core checks without installing or starting the app."""
from pathlib import Path
from datetime import datetime, timezone
import json
import os
import re
import subprocess
import time
import mc_deployment as mc

MANIFEST = 'configs/mc-source-checks.json'
SCOPE = 'NODE_BUSINESS_AND_PROTOCOL_FIXTURES_NOT_REAL_GAME_MODEL_OR_PROGRAMME'
PROBE = """import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';
import {DatabaseSync} from 'node:sqlite';
const require=createRequire(pathToFileURL(process.cwd()+'/backend/game/package.json'));
const pkg=JSON.parse(readFileSync('backend/game/package.json','utf8'));
const lock=JSON.parse(readFileSync('backend/game/package-lock.json','utf8'));
const dependencies=Object.fromEntries(Object.keys(pkg.dependencies).map(name=>[name,require(name+'/package.json').version]));
const db=new DatabaseSync(':memory:');db.close();
console.log(JSON.stringify({version:process.versions.node,platform:process.platform,arch:process.arch,sqlite:true,
dependencies,declared:pkg.dependencies,locked:lock.packages[''].dependencies}));"""


def suite_definition(root, source, suite):
    definition = mc.read(mc.inside(root, MANIFEST))
    mc.require(set(definition) == {'schema_version', 'id', 'node', 'suites'}
               and definition['schema_version'] == 1 and definition['id'] == 'mc-core-source-checks-v1'
               and definition['node'] == '24.22.1' and isinstance(definition['suites'], dict),
               'MC_SOURCE_CHECK_MANIFEST')
    row = definition['suites'].get(suite)
    mc.require(isinstance(row, dict) and set(row) == {'tests', 'support', 'scope'}
               and row['scope'] == SCOPE, 'MC_SOURCE_CHECK_SUITE')
    tests, support = row['tests'], row['support']
    mc.require(isinstance(tests, list) and 1 <= len(tests) <= 100 and isinstance(support, list)
               and len(support) <= 100, 'MC_SOURCE_CHECK_TEST_LIST')
    names = tests + support
    mc.require(all(isinstance(n, str) and n.startswith('tests/') and n.endswith('.mjs') for n in names)
               and len(names) == len(set(names)) and all(n.endswith('.test.mjs') for n in tests),
               'MC_SOURCE_CHECK_TEST_LIST')
    for name in [MANIFEST, *names]:
        path = mc.inside(root, name)
        mc.require(name in source['files'] and path.is_file() and mc.sha(path) == source['files'][name],
                   'MC_SOURCE_CHECK_TEST_NOT_BOUND')
    return row


def native_probe(root, node):
    path = mc.executable(root, str(node), 'node')
    environment = os.environ.copy()
    environment.pop('NODE_OPTIONS', None); environment.pop('NODE_PATH', None)
    flags = {'creationflags': 0x08000000} if os.name == 'nt' else {}
    process = subprocess.run([str(path), '--input-type=module', '-e', PROBE], cwd=root,
                             stdin=subprocess.DEVNULL, capture_output=True, env=environment, timeout=15, **flags)
    mc.require(process.returncode == 0, 'MC_SOURCE_CHECK_NODE_OR_DEPENDENCIES')
    try:
        value = json.loads(process.stdout.decode('utf-8'))
    except (ValueError, UnicodeError):
        raise mc.PreparationError('MC_SOURCE_CHECK_NODE_OR_DEPENDENCIES') from None
    mc.require(value.get('version') == '24.22.1' and value.get('platform') == 'win32'
               and value.get('arch') == 'x64' and value.get('sqlite') is True, 'MC_SOURCE_CHECK_NODE')
    expected = {'ajv': '8.20.0', 'ajv-formats': '3.0.1', 'jpeg-js': '0.4.4', 'ws': '8.22.0'}
    mc.require(value.get('dependencies') == value.get('declared') == value.get('locked') == expected,
               'MC_SOURCE_CHECK_DEPENDENCY_VERSION')
    return path, {'path': str(path), 'sha256': mc.sha(path), **value}, environment, flags


def tap_summary(text):
    result = {}
    for key in ['tests', 'pass', 'fail', 'cancelled', 'skipped', 'todo']:
        values = re.findall(r'^# ' + key + r' (\d+)\s*$', text, re.M)
        mc.require(len(values) == 1, 'MC_SOURCE_CHECK_TAP_INCOMPLETE')
        result[key] = int(values[0])
    mc.require(result['tests'] > 0 and result['tests'] == sum(result[k] for k in ['pass', 'fail', 'cancelled', 'skipped']),
               'MC_SOURCE_CHECK_TAP_INCOMPLETE')
    return result


def run(root, *, node, output, suite='core'):
    root = Path(root).resolve()
    mc.require(isinstance(output, str) and output.startswith('outputs/') and output.count('/') >= 2,
               'MC_SOURCE_CHECK_OUTPUT')
    folder = mc.inside(root, output)
    mc.require(not folder.exists(), 'MC_SOURCE_CHECK_OUTPUT_EXISTS')
    source = mc.source_identity(root)
    definition = suite_definition(root, source, suite)
    executable, runtime, environment, flags = native_probe(root, node)
    mc.require(mc.source_identity(root) == source, 'MC_SOURCE_CHECK_SOURCE_CHANGED')
    folder.mkdir(parents=True, exist_ok=False)
    # Keep the runner's report, log and child native temp in this new folder.
    temp = folder / 'native-temp'; temp.mkdir()
    environment.update(TEMP=str(temp), TMP=str(temp), MC_TEST_NODE=str(executable))
    argv = [str(executable), '--test', '--test-reporter=tap', '--test-concurrency=1',
            '--test-timeout=60000', *definition['tests']]
    def write(name, value):
        with (folder / name).open('x', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2); stream.write('\n')
    write('inputs.json', {'argv': argv, 'cwd': str(root), 'suite': suite, 'source': source,
                          'runtime': runtime, 'scope': SCOPE, 'started_at': datetime.now(timezone.utc).isoformat()})
    report = {'ok': False, 'scope': SCOPE, 'suite': suite, 'output': output, 'tests': None,
              'services_started': False, 'models_loaded': False, 'real_minecraft': False,
              'official_client_started': False, 'public_broadcast_started': False,
              'native_dsh_booted': False, 'native_environment_prepared': False,
              'source_snapshot_sha256': source['snapshot_sha256'], 'source_files': len(source['files'])}
    started = time.monotonic()
    try:
        with (folder / 'test-output.tap').open('xb') as log:
            process = subprocess.run(argv, cwd=root, stdin=subprocess.DEVNULL, stdout=log,
                                     stderr=subprocess.STDOUT, env=environment, **flags)
        report['node_exit_code'] = process.returncode
        report['source_unchanged'] = mc.source_identity(root) == source
        mc.require(report['source_unchanged'], 'MC_SOURCE_CHECK_SOURCE_CHANGED')
        report['tests'] = tap_summary((folder / 'test-output.tap').read_text(encoding='utf-8-sig'))
        report['ok'] = (process.returncode == 0 and report['tests']['pass'] == report['tests']['tests']
                        and all(report['tests'][key] == 0 for key in ['fail', 'cancelled', 'skipped', 'todo']))
        report['code'] = 'PASS' if report['ok'] else 'MC_SOURCE_CHECK_TESTS_FAILED'
    except (mc.PreparationError, OSError, ValueError, subprocess.SubprocessError) as error:
        report['code'] = str(error) if isinstance(error, mc.PreparationError) else 'MC_SOURCE_CHECK_EXECUTION_FAILED'
    finally:
        report['elapsed_seconds'] = round(time.monotonic() - started, 3)
        report['completed_at'] = datetime.now(timezone.utc).isoformat()
        write('report.json', report)
    return report
