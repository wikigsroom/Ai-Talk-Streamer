"""Upload verified assets, then publish a final GitHub Release using a repository token."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('Unexpected authenticated redirect; credentials not forwarded')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True); parser.add_argument('--version', required=True)
    parser.add_argument('--directory', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repo): raise ValueError('Invalid repository')
    if not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', args.version): raise ValueError('Final version required')
    token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if not token: raise RuntimeError('A repository-scoped GitHub token is required in GH_TOKEN')
    folder = Path(args.directory)
    manifest = json.loads((folder/'release-manifest.json').read_text(encoding='utf8'))
    if manifest['version'] != args.version or manifest['release_type'] != 'final': raise ValueError('Release manifest mismatch')
    expected = {row['name']: row['sha256'] for row in manifest['assets']}
    expected['release-manifest.json'] = hashlib.sha256((folder/'release-manifest.json').read_bytes()).hexdigest()
    sums = {}
    for line in (folder/'SHA256SUMS.txt').read_text(encoding='ascii').splitlines():
        value, name = line.split('  ', 1); sums[name] = value
    if expected != sums: raise ValueError('Checksum list does not match the manifest')
    expected['SHA256SUMS.txt'] = hashlib.sha256((folder/'SHA256SUMS.txt').read_bytes()).hexdigest()
    for name, value in expected.items():
        if Path(name).name != name or hashlib.sha256((folder/name).read_bytes()).hexdigest() != value:
            raise ValueError('Asset verification failed: '+name)
    opener = urllib.request.build_opener(NoRedirect)
    base = 'https://api.github.com/repos/'+args.repo

    def call(url, method='GET', value=None, raw=None, content_type='application/json'):
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != 'https' or parsed.hostname not in {'api.github.com', 'uploads.github.com'}:
            raise ValueError('Unexpected GitHub destination')
        data = raw if raw is not None else None if value is None else json.dumps(value).encode()
        request = urllib.request.Request(url, data=data, method=method, headers={
            'Authorization': 'Bearer '+token, 'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'agent-gameplay-isaac-release',
            'Content-Type': content_type})
        try:
            with opener.open(request, timeout=60) as response:
                return json.loads(response.read() or b'{}')
        except urllib.error.HTTPError as error:
            # Never echo request headers or provider response bodies.
            raise RuntimeError('GitHub '+method+' failed with HTTP '+str(error.code)) from None

    tag = call(base+'/git/ref/tags/'+args.version)['object']
    for _ in range(4):
        if tag['type'] != 'tag': break
        tag = call(base+'/git/tags/'+tag['sha'])['object']
    if tag['type'] != 'commit' or tag['sha'] != manifest['source_commit']:
        raise ValueError('Remote tag does not match the packaged source commit')
    releases = call(base+'/releases?per_page=100')
    release = next((r for r in releases if r['tag_name'] == args.version), None)
    if release and not release['draft']:
        raise RuntimeError('A published release already exists; it was left unchanged')
    body = (folder/'RELEASE_NOTES.md').read_text(encoding='utf8')
    body += '\n\nSource commit: `'+manifest['source_commit']+'`. See `release-manifest.json` and `SHA256SUMS.txt`.\n'
    fields = {'tag_name': args.version, 'target_commitish': manifest['source_commit'],
              'name': args.version+' · Native Windows Local Control + DSH Strategy',
              'body': body, 'draft': True, 'prerelease': False, 'make_latest': 'false'}
    release = call(base+'/releases', 'POST', fields) if release is None else call(base+'/releases/'+str(release['id']), 'PATCH', fields)
    rid = str(release['id'])
    existing = {a['name']: a for a in call(base+'/releases/'+rid+'/assets?per_page=100')}
    upload = release['upload_url'].split('{')[0]
    for name, value in expected.items():
        asset = existing.get(name)
        if asset and asset.get('digest') == 'sha256:'+value: continue
        if asset: call(base+'/releases/assets/'+str(asset['id']), 'DELETE')
        data = (folder/name).read_bytes()
        asset = call(upload+'?'+urllib.parse.urlencode({'name': name}), 'POST', raw=data,
                     content_type='application/octet-stream')
        if asset.get('size') != len(data) or asset.get('state') != 'uploaded':
            raise RuntimeError('GitHub asset acknowledgement mismatch: '+name)
        if asset.get('digest') and asset['digest'] != 'sha256:'+value:
            raise RuntimeError('GitHub asset digest mismatch: '+name)
    uploaded = {a['name']: a for a in call(base+'/releases/'+rid+'/assets?per_page=100')}
    if set(uploaded) != set(expected): raise RuntimeError('Incomplete or unexpected release assets; draft retained')
    for name, value in expected.items():
        if uploaded[name].get('digest') and uploaded[name]['digest'] != 'sha256:'+value:
            raise RuntimeError('Release asset hash changed; draft retained')
    release = call(base+'/releases/'+rid, 'PATCH', {'draft': False, 'prerelease': False, 'make_latest': 'true'})
    if release['draft'] or release['prerelease'] or not release.get('published_at'):
        raise RuntimeError('Final publication was not acknowledged')
    print(json.dumps({'published': True, 'url': release['html_url'], 'version': release['tag_name'],
                      'draft': release['draft'], 'prerelease': release['prerelease'], 'assets': len(expected)}))


if __name__ == '__main__': main()
