"""Privately configure the selected model; the key is read without terminal echo."""
from pathlib import Path
import argparse
import getpass
import json
import subprocess
from urllib.parse import urlparse
ROOT=Path(__file__).resolve().parent

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--base-url',required=True,help='OpenAI-compatible base URL including /v1 when needed');parser.add_argument('--model',default='gpt-6-luna');args=parser.parse_args()
    url=urlparse(args.base_url)
    if url.scheme not in {'http','https'} or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise SystemExit('Expected a base URL without embedded credentials')
    key=getpass.getpass('模型 API 密钥（输入不显示）：').strip()
    if not key:raise SystemExit('Empty key was not saved')
    folder=ROOT/'private';folder.mkdir(exist_ok=True)
    user=subprocess.check_output(['whoami'],text=True).strip()
    subprocess.run(['icacls',str(folder),'/inheritance:r','/grant:r',user+':(OI)(CI)F','SYSTEM:(OI)(CI)F'],check=True,stdout=subprocess.DEVNULL)
    (folder/'model.json').write_text(json.dumps({'base_url':args.base_url.rstrip('/'),'api_key':key,'model':args.model},indent=2),encoding='utf8')
    from start_dsh import bridge_token
    bridge_token()
    print('私有模型配置已保存；请重启 DSH 宿主生效。')

if __name__=='__main__':main()
