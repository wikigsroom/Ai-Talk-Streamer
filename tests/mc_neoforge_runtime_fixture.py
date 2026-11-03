"""Tiny native-file doubles. No fixture JAR, DLL, model or executable is run."""
from pathlib import Path
import hashlib
import json
import zipfile

import mc_neoforge as neo

ROOT = Path(__file__).resolve().parents[1]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False) + '\n', encoding='utf-8')


def rebuild_receipt(root):
    root = Path(root)
    resources = root / 'game-adapters/minecraft/neoforge/src/main/resources'
    sources = {p.relative_to(root).as_posix(): neo.sha(p)
               for top in ['game-adapters/minecraft/neoforge/src/main/java',
                           'game-adapters/minecraft/neoforge/src/main/resources', neo.BRIDGE_CORE]
               for p in (root / top).rglob('*') if p.is_file()}
    sources.update({name: neo.sha(root / name) for name in [neo.BRIDGE_LOCK, neo.BRIDGE_SCHEMA, 'scripts/mc_neoforge.py']})
    entries = neo.read(root / neo.BRIDGE_LOCK)['dependencies']
    jar = root / neo.CONTROLLER_JAR
    jar.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(jar, 'w') as archive:
        for name in ['dev/aitalkstreamer/mc/neoforge/NativeClient.class',
                     'dev/aitalkstreamer/mc/neoforge/NativeBridge.class',
                     'dev/aitalkstreamer/mc/core/BridgeCore.class']:
            archive.writestr(name, b'EXPLICIT FIXTURE BYTECODE, NEVER LOADED')
        for p in resources.rglob('*'):
            if p.is_file():
                archive.write(p, p.relative_to(resources).as_posix())
        archive.write(root / neo.BRIDGE_SCHEMA, 'mc-contracts/game.schema.json')
        metadata = []
        for entry in entries:
            embedded = 'META-INF/jarjar/' + entry['file']
            archive.write(root / neo.HOME / 'dependencies' / entry['file'], embedded)
            metadata.append({'identifier': {'group': entry['group'], 'artifact': entry['artifact']},
                'version': {'range': '[' + entry['version'] + ']', 'artifactVersion': entry['version']},
                'path': embedded, 'isObfuscated': False})
        archive.writestr('META-INF/jarjar/metadata.json', json.dumps({'jars': metadata}))
    write_json(root / neo.BUILD_RECEIPT, {'ok':True, 'jar':neo.CONTROLLER_JAR,
        'sha256':neo.sha(jar), 'bytes':jar.stat().st_size, 'sources':sources,
        'compiled_against':'actual_supplied_neoforge_21.1.248_mojmap_libraries',
        'automatic_input_authorized':False,
        'dependencies':{(Path(neo.HOME) / 'dependencies' / pin['file']).as_posix():pin['sha256'] for pin in entries}})


def install(root):
    root = Path(root)
    source = root.parent / 'supplied-pack-fixture'
    instance = source / '.minecraft/versions/MC-Friends-S1-r001'
    pins = []
    def put(name, data):
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        pins.append({'path':name, 'bytes':len(data), 'sha256':neo.sha(path)})
    for i in range(319):
        put('.minecraft/versions/MC-Friends-S1-r001/mods/fixture-' + str(i) + '.jar', str(i).encode())
    put('.minecraft/versions/1.21.1/1.21.1.json', json.dumps({'assetIndex':{'id':'17'}}).encode())
    put('.minecraft/versions/MC-Friends-S1-r001/MC-Friends-S1-r001.json', b'{}')
    put('.minecraft/versions/MC-Friends-S1-r001/MC-Friends-S1-r001.jar', b'FIXTURE GAME, NEVER RUN')
    put('.minecraft/versions/MC-Friends-S1-r001/MC-Friends-S1-r001-natives/test.dll', b'FIXTURE DLL, NEVER LOADED')
    put('.minecraft/versions/MC-Friends-S1-r001/runtime/java21/bin/java.exe', b'FIXTURE JAVA, NEVER RUN')
    module = instance / 'runtime/java21/lib/modules'
    module.parent.mkdir(parents=True, exist_ok=True)
    module.write_bytes(b'FIXTURE JRE MODULES')
    data = b'EXPLICIT FIXTURE ASSET'
    asset_hash = hashlib.sha1(data).hexdigest()
    put('.minecraft/assets/indexes/17.json', json.dumps({'objects':{'fixture/test':{'hash':asset_hash,'size':len(data)}}}).encode())
    asset = source / ('.minecraft/assets/objects/' + asset_hash[:2] + '/' + asset_hash)
    asset.parent.mkdir(parents=True, exist_ok=True)
    asset.write_bytes(data)
    lock = json.loads((ROOT / neo.LOCK).read_text(encoding='utf-8'))
    lock['files'] = pins
    write_json(root / neo.LOCK, lock)
    for name, data in {
        'game-adapters/minecraft/neoforge/src/main/java/dev/aitalkstreamer/mc/neoforge/NativeClient.java':b'// fixture source, never compiled',
        neo.BRIDGE_CORE + '/BridgeCore.java':b'// fixture shared core, never compiled',
        'game-adapters/minecraft/neoforge/src/main/resources/META-INF/neoforge.mods.toml':(ROOT / 'game-adapters/minecraft/neoforge/src/main/resources/META-INF/neoforge.mods.toml').read_bytes(),
        neo.BRIDGE_SCHEMA:b'{"$schema":"https://json-schema.org/draft/2020-12/schema"}',
        'scripts/mc_neoforge.py':(ROOT / 'scripts/mc_neoforge.py').read_bytes()
    }.items():
        target = root / name
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    bridge = json.loads((ROOT / neo.BRIDGE_LOCK).read_text(encoding='utf-8'))
    for pin in bridge['dependencies']:
        data = ('FIXTURE DEPENDENCY, NEVER EXECUTED: ' + pin['artifact']).encode()
        pin.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        p = root / neo.HOME / 'dependencies' / pin['file']
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    write_json(root / neo.BRIDGE_LOCK, bridge)
    record = neo.prepare(root, source)
    write_json(Path(record['work']) / 'config/ai-talk-streamer-bridge.json',
               {'enabled':True, 'endpoint':'ws://127.0.0.1:3092/api/dsh/game/bridge'})
    rebuild_receipt(root)
    return source
