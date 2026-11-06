"""Vendor reviewed, pinned DSH extension sources; never execute upstream installers."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

SOURCES = [
    ('soul-md', 'Scorp1o117/dsh-soul-md', '0de8445b4941315da18138d5b5f1fc19fa5cc7d2'),
    ('fish-memory', 'Yuuyuko-uu/dsh-fish-memory', 'a070ebf096f3472c107982b5741994cabdcc18f7'),
    ('feiyu-mood', 'Yuuyuko-uu/dsh-feiyu-mood', '2f52a367e2ea673c7e73a4a8c718721665d10081'),
    ('speak-up', 'Yuuyuko-uu/dsh-speak-up', 'e3bc6362208c693bb833ecf463ec6a20df4b6419'),
    ('memewiki-thawline', 'thawline/dsh-memewiki', 'bf3155ad93dedfdbe37798680e79b5386503e38d'),
    ('humanizer-chinese', 'jiji262/humanizer-chinese', '1d6c08e10fbfe0e1b36ac784834451c6aae0a92c'),
    ('memewiki-liujelly', 'Liujelly/dsh-memewiki', '1d3f8266468823fe85290a016eadf3b8d1262de3'),
]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstream', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    destination = root / 'extensions/naimei-dsh/vendor'
    entries = []
    for alias, repository, revision in SOURCES:
        source = args.upstream / repository.replace('/', '--')
        actual = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
        if actual != revision:
            raise SystemExit(f'{repository}: revision mismatch')
        tracked = subprocess.check_output(['git', '-C', str(source), 'ls-files', '-z']).decode().split('\0')
        target = destination / alias
        target.mkdir(parents=True, exist_ok=True)
        # A nested upstream Git rule can override our byte-preservation rule.
        # Repository checkout settings are not extension runtime dependencies.
        (target / '.gitattributes').unlink(missing_ok=True)
        # Keep attribution and upstream runtime sources; omit CI, tests and examples.
        kept = []
        for relative in filter(None, tracked):
            parts = Path(relative).parts
            if parts[0] in {'.github', 'tests', 'test', 'examples', 'docs', 'screenshots'}:
                continue
            if relative in {'AGENTS.md', 'CLAUDE.md', 'package-lock.json', '.gitignore', '.gitattributes'}:
                continue
            if not (source / relative).is_file():
                continue
            output = target / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / relative, output)
            kept.append(relative)
        patches = {}
        # Expose reviewed pure algorithms and queue scheduler, rather than mounting
        # native session scanning, self-updaters, memory writers or HTTP control APIs.
        if alias == 'feiyu-mood':
            patches['lib/index.js'] = '\n// Naimei bridge adapter: public integration seam; no native session scanning.\nexport const streamAdapter = { blankState, parseDelta, applyDelta, decay, moodLabel, displayDims, judge };\n'
        if alias == 'fish-memory':
            patches['lib/index.js'] = '\n// Naimei privacy boundary: release derived text caches when the bridge is disposed.\nexport const streamAdapter = { clearCaches() { for (const cache of [切词缓存, 切词缓存2, 词面缓存, 记忆词集缓存, 扩词集缓存, 说话尺]) cache.clear(); } };\n'
        if alias == 'speak-up':
            patches['lib/host.js'] = '\n// Naimei bridge adapter: followup is supplied by the authoritative speech queue.\nexport const streamAdapter = { createScheduler: 造执行体 };\n'
        if alias == 'memewiki-liujelly':
            output = target / 'lib/index.js'
            original = output.read_text('utf-8')
            before = 'if (!entry && settings.online && q.length <= 20)'
            if original.count(before) != 1:
                raise SystemExit('MEMEWIKI_OFFLINE_PATCH_ANCHOR')
            output.write_bytes(original.replace(before, "if (!entry && settings.online && process.env.STREAM_LIVE_MODE !== '1' && q.length <= 20)").encode('utf-8'))
            patches['lib/index.js'] = '\n// Naimei live mode forbids online fallback even if an old settings file enables it.\n'
        if repository.startswith('Yuuyuko-uu/'):
            if alias in {'fish-memory', 'feiyu-mood'}:
                output = target / 'lib/index.js'
                original = output.read_text('utf-8')
                before = 'function diag(msg) {'
                if original.count(before) != 1:
                    raise SystemExit(f'{alias}: diagnostic patch anchor changed')
                output.write_bytes(original.replace(before, before + "\n  if (process.env.STREAM_LIVE_MODE === '1') return // No raw dialogue diagnostic files in live mode.").encode('utf-8'))
            readme = target / 'README.md'
            note = (f'> 本集成副本派生自 https://github.com/{repository} ，原作者 **Yuuyuko-uu**。'
                    '完整保留原许可与署名；修改为导出直播桥接接口/缓存清理（如适用）、关闭直播原文诊断日志和本归属声明。'
                    '直播身份、单写者、记忆分区和播报队列由上层适配器约束。\n\n')
            readme.write_bytes(note.encode('utf-8') + readme.read_bytes())
            patches['README.md'] = ''
        for relative, suffix in patches.items():
            output = target / relative
            output.write_bytes(output.read_bytes() + suffix.encode('utf-8'))
        package = json.loads((target / 'package.json').read_text('utf-8')) if (target / 'package.json').exists() else {}
        files = {name: hashlib.sha256((target / name).read_bytes()).hexdigest() for name in sorted(kept)}
        entries.append({'id': alias, 'repository': f'https://github.com/{repository}', 'commit': revision,
                        'version': package.get('version', '1.0.0'), 'directory': f'vendor/{alias}',
                        'license': package.get('license', 'MIT'), 'modified_files': list(patches), 'files': files})
    manifest = {'schema_version': 1, 'contract': 'naimei-dsh-extensions-v1', 'sources': entries}
    (destination.parent / 'sources.lock.json').write_bytes((json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    print(json.dumps({'sources': len(entries), 'files': sum(len(row['files']) for row in entries)}, ensure_ascii=False))

if __name__ == '__main__':
    main()
