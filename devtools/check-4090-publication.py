"""Verify staged SHA objects and the unauthenticated production case URLs."""
import argparse
import concurrent.futures
import datetime
import hashlib
import json
import urllib.request

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('publisher', REPO / 'devtools/publish-4090-case.py')
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--kind', choices=['preview', 'production'], default='production')
    args = parser.parse_args()
    work = publisher.WORK
    plan = json.loads((work / 'plan.json').read_text(encoding='utf-8'))
    receipt = json.loads((work / (args.kind + '-status.json')).read_text(encoding='utf-8'))
    assert receipt['readyState'] == 'READY'
    files = publisher.filetree(publisher.api('GET', '/v6/deployments/' + receipt['id'] + '/files'))
    actual = {row['file']: row['sha'] for row in files}
    expected = {row['file']: row['sha'] for row in plan['files']}
    assert actual == expected, 'Deployment source references differ from the staged plan'
    if args.kind == 'production':
        project = publisher.api('GET', '/v9/projects/' + publisher.PROJECT)
        assert project['targets']['production']['id'] == receipt['id']
        assert '4090.sid.mom' in receipt['alias']
    base = 'https://4090.sid.mom' if args.kind == 'production' else 'https://' + receipt['url']

    def check(row):
        url = base + '/' + row['file'] + '?verify=' + row['sha'][:12]
        request = urllib.request.Request(url, headers={'User-Agent': 'Ai-Talk-Streamer-Verification/1.0', 'Cache-Control': 'no-cache'})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=25) as response:
            body = response.read()
            assert response.status == 200
            digest = hashlib.sha256(body).hexdigest()
            assert digest == row['sha256'], 'Public byte mismatch: ' + row['file']
            return {'file': row['file'], 'http_status': response.status, 'bytes': len(body), 'sha256': digest}

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        verified = list(pool.map(check, plan['new_files']))
    result = {
        'ok': True,
        'verified_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'deployment_id': receipt['id'],
        'project': publisher.PROJECT,
        'public_url': plan['public_url'],
        'source_count': len(actual),
        'preserved_source_files': plan['preserved_source_files'],
        'base_production_id': plan['base_production_id'],
        'unauthenticated_http_files': verified,
        'scope': 'Public static case and existing source preservation; no model or broadcast starts',
    }
    (work / (args.kind + '-verification.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in result.items() if key != 'unauthenticated_http_files'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
