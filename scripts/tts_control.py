"""Inspect, select or recover the approved local voice pair; no model downloads."""
from pathlib import Path
import argparse, json, urllib.request


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['status', 'select', 'recover'])
    p.add_argument('voice', nargs='?', choices=['O07', 'F07'], default='O07')
    a = p.parse_args()
    route = {'status': '/health', 'select': '/voice', 'recover': '/recover'}[a.action]
    body = None if a.action == 'status' else json.dumps({'voice_id': a.voice}).encode()
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request('http://127.0.0.1:9880'+route, data=body, headers={'Content-Type': 'application/json'})
    with op.open(request, timeout=10) as response:
        print(json.dumps(json.load(response), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
