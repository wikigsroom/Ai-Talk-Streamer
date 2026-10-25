"""Check the current normative documentation and standalone examples; no runtime acceptance claim."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import re
import sqlite3


ROOT = Path(__file__).resolve().parents[1]


def main():
    docs = [ROOT / 'docs/DSH_HUMANITY.md', *sorted((ROOT / 'docs/dsh-humanity').glob('*.md'))]
    examples = sorted((ROOT / 'docs/dsh-humanity/examples').iterdir())
    checks = []

    def check(condition, description):
        if not condition:
            raise AssertionError(description)
        checks.append(description)

    check(len(docs) == 10 and len(examples) == 5, 'ten documents and five standalone examples')
    inline_count = 0
    for path in docs:
        text = path.read_text(encoding='utf-8-sig')
        check(len(re.findall(r'^```', text, flags=re.M)) % 2 == 0,
              'balanced fences: ' + path.name)
        for block in re.findall(r'```json\s*\n(.*?)\n```', text, flags=re.S):
            json.loads(block)
            inline_count += 1
    check(inline_count >= 5, 'embedded JSON examples parse')
    for path in examples:
        if path.suffix == '.json':
            json.loads(path.read_text(encoding='utf-8-sig'))
    checks.append('all standalone JSON artifacts parse')
    policy = json.loads((ROOT / 'docs/dsh-humanity/examples/bridge-policy.example.json').read_text(encoding='utf-8'))
    check(policy['maintenance']['model_timeout_ms'] < policy['maintenance']['lease_timeout_ms'],
          'model timeout remains below the maintenance lease')
    check(policy['maintenance']['post_broadcast_quiet_ms'] == 120000
          and policy['maintenance']['timezone'] == 'Asia/Taipei', 'quiet window and schedule timezone')
    check(policy['maintenance']['daily_local_time'] == '03:30'
          and policy['maintenance']['weekly_local_time'] == '04:10', 'daily and weekly schedule defaults')
    normative = docs[0].read_text(encoding='utf-8-sig')
    check(len(set(re.findall(r'\| (R\d{2}) \|', normative))) == 16, 'sixteen normative constraints')
    acceptance = (ROOT / 'docs/dsh-humanity/OPERATIONS_TESTING.md').read_text(encoding='utf-8-sig')
    check(len(set(re.findall(r'\| (A\d{2}) \|', acceptance))) == 40, 'forty acceptance definitions')
    check(all(re.search(r'\bS'+str(i)+r'\b', acceptance) for i in range(1, 6)), 'five real-channel scenario definitions')
    with sqlite3.connect(':memory:') as db:
        db.executescript((ROOT / 'docs/dsh-humanity/examples/state-schema.sql').read_text(encoding='utf-8'))
        tables = db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone()[0]
        check(tables == 21, 'SQLite base schema initializes with twenty-one application tables')
        check(db.execute('PRAGMA foreign_key_check').fetchall() == [], 'base schema foreign keys')
        check(db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'base schema integrity')
    result = {'checked_at': datetime.now(timezone.utc).isoformat(),
              'scope': 'Current normative documents, embedded/standalone JSON and SQLite example initialization only; runtime evidence is separate',
              'result': 'passed', 'document_count': len(docs), 'example_count': len(examples),
              'sqlite_version': sqlite3.sqlite_version, 'sqlite_tables': tables,
              'embedded_json_count': inline_count, 'normative_constraints': 16,
              'acceptance_definitions': 40, 'real_channel_scenario_definitions': 5,
              'runtime_tests_executed_by_this_validator': False, 'checks': checks,
              'artifact_hash_format': 'SHA-256 of UTF-8 text normalized to LF',
              'artifacts': [{'path': path.relative_to(ROOT).as_posix(),
                             'sha256': hashlib.sha256(path.read_text(encoding='utf-8-sig').replace('\r\n', '\n').encode()).hexdigest()}
                            for path in docs + examples]}
    (ROOT / 'docs/evidence/dsh-humanity-doc-validation.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'passed': True, 'checks': len(checks), 'documents': len(docs), 'runtime_acceptance': False}))


if __name__ == '__main__':
    main()
