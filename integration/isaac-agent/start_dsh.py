"""Launch the official native DSH CLI in an isolated profile; secrets are environment-only."""
from pathlib import Path
import json
import os
import subprocess
import sys
import secrets

ROOT=Path(__file__).resolve().parent

def private_config():
    return json.loads((ROOT/'private/model.json').read_text(encoding='utf8'))

def bridge_token():
    target=ROOT/'private/bridge-token.txt'
    if not target.exists(): target.write_text(secrets.token_hex(32),encoding='ascii')
    return target.read_text(encoding='ascii').strip()


def profile_dependencies(home, runtime, env):
    profile=home/'profiles/isaac'
    if not (profile/'package.json').is_file():
        # Initialize via the official CLI before linking dependencies: its
        # --from-default-profile operation replaces the profile directory.
        subprocess.run([runtime['node'],runtime['dsh_cli'],'--profile','isaac',
                        '--from-default-profile','sdk-minimal','--dump-config'],
                       cwd=ROOT/'dsh-host',env=env,check=True,stdout=subprocess.DEVNULL)
    target=(ROOT/'dsh-host/node_modules').resolve()
    link=profile/'node_modules'
    if os.path.lexists(link):
        if link.resolve()!=target:raise RuntimeError('Dedicated DSH profile has a different dependency directory; left untouched')
        return
    # Cordis resolves bare plugin names relative to the profile, not cwd.
    # Reuse exactly the locked host dependencies through a native NTFS junction.
    # No copies, global installs, virtualized environments or profile overwrites.
    quote=lambda value:"'"+str(value).replace("'","''")+"'"
    command='New-Item -ItemType Junction -Path '+quote(link)+' -Value '+quote(target)+' -ErrorAction Stop | Out-Null'
    subprocess.run([r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe',
                    '-NoProfile','-NonInteractive','-Command',command],check=True)

def prepare():
    runtime=json.loads((ROOT/'dsh-host/runtime.json').read_text(encoding='utf8'))
    model=private_config()
    home=ROOT/'.dsh-home';home.mkdir(exist_ok=True)
    logs=ROOT/'logs/dsh';logs.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ,DSH_HOME=str(home),ISAAC_LUNA_API_KEY=model['api_key'],ISAAC_BRIDGE_TOKEN=bridge_token(),
             PATH=str(Path(runtime['node']).parent)+os.pathsep+os.environ.get('PATH',''))
    profile_dependencies(home,runtime,env)
    disabled=['dsh-hmr','sdk-app-startup','sdk-jsonrpc-server','llm-deepseek','deepseek-llm-api-extensions','session-log-deepseek','plugin-package-inventory-deepseek',
              'persistent-bash','persistent-pwsh','tool-fs','tool-working-directory','terminal-bash','terminal-pwsh','pty']
    patch=[{'id':identity,'disabled':True} for identity in disabled]
    patch.append({'insert':[
        {'id':'llm-pi-ai','name':'@deepseek-ai/dsh-llm-pi-ai','config':{'providers':{'isaac-lan':{
            'apiKeyEnv':'ISAAC_LUNA_API_KEY','api':'openai-completions','baseURL':model['base_url'],
            'models':[{'id':model['model'],'input':['text'],'contextWindow':64000,'maxTokens':4096}],
            'streamIdleTimeoutMs':15000,'compat':{'maxTokensField':'max_tokens','supportsDeveloperRole':False}}}}},
        {'id':'isaac-strategy','name':'dsh-isaac-strategy',
         'config':{'endpoint':'http://127.0.0.1:9532','port':9533,'cwd':str(ROOT),'logs':str(logs).replace('\\','/')}}]})
    path=ROOT/'dsh-host/isaac.patch.json';path.write_text(json.dumps(patch,ensure_ascii=False,indent=2),encoding='utf8')
    args=[runtime['node'],runtime['dsh_cli'],'--profile','isaac']
    args+=['--patch',str(path)]
    return args,env

if __name__=='__main__':
    args,env=prepare()
    if '--dump-config' in sys.argv: args+=['--dump-config']
    raise SystemExit(subprocess.call(args,cwd=ROOT/'dsh-host',env=env))
