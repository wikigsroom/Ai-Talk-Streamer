from pathlib import Path
import configparser,json,secrets
ROOT=Path(__file__).resolve().parents[1];folder=ROOT/'tools/obs/config/obs-studio'
target=folder/'plugin_config/obs-websocket/config.json';target.parent.mkdir(parents=True,exist_ok=True)
settings=json.loads(target.read_text(encoding='utf-8')) if target.exists() else {}
settings.update(first_load=False,server_enabled=True,server_port=4457,alerts_enabled=False,auth_required=True)
if not settings.get('server_password'):settings['server_password']=secrets.token_urlsafe(24)
target.write_text(json.dumps(settings,indent=2),encoding='utf-8')
global_ini=folder/'global.ini';config=configparser.ConfigParser();config.optionxform=str
if global_ini.exists():config.read(global_ini,encoding='utf-8-sig')
for section in ('General','Basic','BasicWindow'):
    if section not in config:config[section]={}
config['General'].update(FirstRun='true',EnableAutoUpdates='false')
config['Basic'].update(Profile='Avatar Local',ProfileDir='Avatar_Local',SceneCollection='Avatar Local',SceneCollectionFile='Avatar_Local')
config['BasicWindow'].update(PreviewEnabled='true')
with global_ini.open('w',encoding='utf-8') as file:config.write(file,space_around_delimiters=False)
# OBS 31 stores first-run state in user.ini; true means the first run is complete.
user_ini=folder/'user.ini';user_config=configparser.ConfigParser();user_config.optionxform=str
if user_ini.exists():user_config.read(user_ini,encoding='utf-8-sig')
for section in ('General','Basic','BasicWindow'):
    if section not in user_config:user_config[section]={}
user_config['General']['FirstRun']='true'
user_config['Basic'].update(config['Basic'])
user_config['BasicWindow']['PreviewEnabled']='true'
with user_ini.open('w',encoding='utf-8') as file:user_config.write(file,space_around_delimiters=False)
print(json.dumps({'ok':True,'obs_websocket_port':4457,'authentication':True,'scene':'Avatar Local'}))
