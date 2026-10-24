"""Apply the pinned live connector patch, preserving and verifying originals."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def patch(root, runtime, source_root=None):
    source_root = source_root or root
    package = runtime / 'node_modules/deepseek-harness-humanity'
    metadata = json.loads((package / 'package.json').read_text(encoding='utf-8'))
    if metadata.get('version') != '0.1.17':
        raise RuntimeError('Only the reviewed Humanity 0.1.17 base is supported')
    lib = package / 'lib'
    backup = root / '.setup/dsh-humanity-originals/0.1.17'
    operations = {
        'index.js': [
            ("import { Config } from './config.js';", "import { Config } from './config.js';\nimport { createStreamConnector } from './stream-connector.mjs';"),
            ('    const state = {};', "    const state = {};\n    if (process.env.STREAM_LIVE_MODE === '1') ctx.provide('streamHumanity', createStreamConnector(ctx, state));"),
            ('    const onChanged = (next) => {', "    const onChanged = (next) => {\n        if (process.env.STREAM_LIVE_MODE === '1' && (next.modules.evolution.enabled || next.modules.dream.enabled || next.modules.memory.advanced.work || next.modules.memory.advanced.session || next.modules.memory.advanced.decay || next.modules.memory.advanced.vector)) throw new Error('STREAM_HUMANITY_CONFIG_FORBIDDEN');"),
        ],
        'tools-seam.js': [
            ('export function installToolsSeam(ctx, log, onReady, onGone) {', "export function installToolsSeam(ctx, log, onReady, onGone) {\n    if (process.env.STREAM_LIVE_MODE === '1') return;"),
        ],
        'data-plane.js': [
            ('return { writable: true, namespaces };', "return { writable: process.env.STREAM_LIVE_MODE !== '1', namespaces };"),
            ('        async replace(ns, section, expectedRevision) {', "        async replace(ns, section, expectedRevision) {\n            if (process.env.STREAM_LIVE_MODE === '1') throw new DataPlaneRejected('Read-only: use Stream Bridge management');"),
            ('        async update(ns, patch, expectedRevision) {', "        async update(ns, patch, expectedRevision) {\n            if (process.env.STREAM_LIVE_MODE === '1') throw new DataPlaneRejected('Read-only: use Stream Bridge management');"),
        ],
        'memory/inject.js': [
            ('`主动调用 ${MEMORY_REMEMBER_TOOL} 记下来，不要为此再问一次，也不要记录寒暄、一次性内容或整段对话原文。`', "`通过 stream_memory_propose 提交有原文来源的候选，不自行激活；不记录寒暄、一次性内容或整段原文。`"),
            ('`先调用 ${MEMORY_RECALL_TOOL} 检索再回答；检索没有的就是没有——明说尚未定过，`', "`先调用 stream_memory_recall 在本次授权分区检索再回答；检索没有的就是没有——明说尚未定过，`"),
            ('text: (context) => renderSectionText(context, { deps, latestMessage, isMainAgent, log }),', "text: (context) => process.env.STREAM_LIVE_MODE === '1' && !ctx.get('streamHumanity')?.injectionEnabled ? MEMORY_GUIDANCE : renderSectionText(context, { deps, latestMessage, isMainAgent, log }),"),
        ],
    }
    receipts = []
    for name, replacements in operations.items():
        target = lib / name
        original = backup / name
        original.parent.mkdir(parents=True, exist_ok=True)
        if not original.exists():
            shutil.copy2(target, original)
        text = original.read_text(encoding='utf-8')
        for before, after in replacements:
            if text.count(before) != 1:
                raise RuntimeError('Patch anchor changed: ' + name)
            text = text.replace(before, after, 1)
        target.write_text(text, encoding='utf-8')
        receipts.append(dict(file=name, original_sha256=sha(original), patched_sha256=sha(target)))
    connector = source_root / 'backend/dsh-bridge/humanity-port.mjs'
    shutil.copy2(connector, lib / 'stream-connector.mjs')
    result = dict(base_version='0.1.17', connector_version='stream-humanity-v1', connector_sha256=sha(connector), files=receipts)
    destination = root / '.setup/dsh-humanity-patch.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, required=True)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--source-root', type=Path)
    args = parser.parse_args()
    root, runtime = args.project_root.resolve(), args.runtime.resolve()
    if not runtime.is_relative_to(root):
        raise SystemExit('Runtime must remain inside the project')
    source_root = args.source_root.resolve() if args.source_root else root
    if not source_root.is_relative_to(root):
        raise SystemExit('Sources must remain inside the project')
    print(json.dumps(patch(root, runtime, source_root), ensure_ascii=False))
