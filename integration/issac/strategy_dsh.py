"""Official pinned strategy DSH, isolated Home and numeric loopback inference."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess

from .common import AdmissionError, inside, local_url, native_only, read_json, write_json


def bridge_token(root):
    path=inside(root,'private/issac/bridge-token.txt')
    path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists():
        try:
            with path.open('x',encoding='ascii') as stream:
                stream.write(secrets.token_hex(32))
        except FileExistsError:
            pass
    value=path.read_text(encoding='ascii').strip()
    if len(value)!=64 or any(x not in '0123456789abcdef' for x in value):
        raise AdmissionError('LOCAL_GAME_TOKEN_INVALID')
    return value


def prepare(root):
    native_only()
    root=Path(root).resolve()
    config=read_json(inside(root,'configs/issac/runtime.json'))
    model=read_json(inside(root,config['model_gateway']['private_config']))
    local_url(model['base_url'])
    endpoint=local_url(config['model_gateway']['strategy_base_url'])
    if endpoint!='http://127.0.0.1:1235/strategy/v1':
        raise AdmissionError('PINNED_STRATEGY_GATEWAY_REQUIRED')
    if not isinstance(model.get('model'),str) or not model['model'].strip():
        raise AdmissionError('ACTUAL_LOCAL_MODEL_ID_REQUIRED')
    context=model.get('context_window',16384)
    if type(context) is not int or not 4096<=context<=32768:
        raise AdmissionError('LOCAL_MODEL_CONTEXT_WINDOW_INVALID')
    host=inside(root,'integration/isaac-agent/dsh-host')
    node=inside(root,config['native_paths']['node'])
    cli=inside(root,config['native_paths']['strategy_dsh_cli'])
    if not node.is_file() or not cli.is_file():
        raise AdmissionError('PINNED_NATIVE_DSH_NOT_PREPARED')
    package=read_json(host/'node_modules/@deepseek-ai/dsh/package.json')
    if package['version']!='0.2.2-rc.1':
        raise AdmissionError('STRATEGY_DSH_VERSION_MISMATCH')
    home=inside(root,'state/isaac-strategy/dsh-home')
    profile=home/'profiles/issac-strategy'
    logs=inside(root,'state/isaac-strategy/dsh-logs')
    home.mkdir(parents=True,exist_ok=True)
    logs.mkdir(parents=True,exist_ok=True)
    # Keep host Windows variables while dropping unrelated provider credentials.
    excluded=('OPENAI_','ANTHROPIC_','DEEPSEEK_','AZURE_','JEV_','BOCHA_')
    env={k:v for k,v in os.environ.items() if not k.upper().startswith(excluded)}
    env.update(DSH_HOME=str(home),ISAAC_PROJECT_ROOT=str(root),ISAAC_LOCAL_API_KEY='local-only',
               ISAAC_BRIDGE_TOKEN=bridge_token(root),DSH_TELEMETRY_DISABLED='1',
               DSH_DISABLE_TELEMETRY='1',PYTHONDONTWRITEBYTECODE='1',
               PATH=str(node.parent)+os.pathsep+env.get('PATH',''))
    if not (profile/'package.json').is_file():
        subprocess.run([str(node),str(cli),'--profile','issac-strategy','--from-default-profile',
                        'sdk-minimal','--dump-config'],cwd=host,env=env,check=True,
                       stdout=subprocess.DEVNULL,creationflags=0x08000000)
    dependencies=(host/'node_modules').resolve()
    link=profile/'node_modules'
    if os.path.lexists(link):
        if link.resolve()!=dependencies:
            raise AdmissionError('STRATEGY_PROFILE_DEPENDENCIES_DIFFER')
    else:
        quote=lambda x:"'"+str(x).replace("'","''")+"'"
        subprocess.run([r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe',
                        '-NoProfile','-NonInteractive','-Command',
                        'New-Item -ItemType Junction -Path '+quote(link)+' -Value '+quote(dependencies)+
                        ' -ErrorAction Stop | Out-Null'],check=True,creationflags=0x08000000)
    disabled=['dsh-hmr','sdk-app-startup','sdk-jsonrpc-server','llm-deepseek',
              'deepseek-llm-api-extensions','session-log-deepseek','plugin-package-inventory-deepseek',
              'persistent-bash','persistent-pwsh','tool-fs','tool-working-directory',
              'terminal-bash','terminal-pwsh','pty']
    patch=[{'id':name,'disabled':True} for name in disabled]
    patch.append({'insert':[
        {'id':'llm-pi-ai','name':'@deepseek-ai/dsh-llm-pi-ai','config':{'providers':{'isaac-local':{
            'apiKeyEnv':'ISAAC_LOCAL_API_KEY','api':'openai-completions','baseURL':endpoint,
            'models':[{'id':model['model'],'input':['text'],'contextWindow':context,'maxTokens':1600}],
            'streamIdleTimeoutMs':15000,'compat':{'maxTokensField':'max_tokens','supportsDeveloperRole':False}}}}},
        {'id':'isaac-strategy','name':'dsh-isaac-strategy','config':{
            'endpoint':'http://127.0.0.1:9532','port':9533,'cwd':str(root),'logs':str(logs),
            'provider':'isaac-local','model':model['model']}}
    ]})
    patch_path=home/'isaac.patch.json'
    write_json(patch_path,patch)
    write_json(home/'runtime-composition.json',{
        'dsh':'0.2.2-rc.1','provider':'isaac-local','model':model['model'],
        'model_endpoint_kind':'numeric_ipv4_loopback_gateway','cloud_fallback':False,
        'home_scope':'state/isaac-strategy/dsh-home','profile':'issac-strategy',
        'disabled_plugins':disabled,'runtime_accepted':False})
    return [str(node),str(cli),'--profile','issac-strategy','--patch',str(patch_path)],env,host


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,required=True)
    args=parser.parse_args()
    command,env,cwd=prepare(args.root)
    raise SystemExit(subprocess.call(command,cwd=cwd,env=env,creationflags=0x08000000))


if __name__=='__main__':
    main()
