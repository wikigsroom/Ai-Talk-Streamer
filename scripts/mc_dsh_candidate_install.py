"""Install the pinned DSH candidate beside the preserved native runtime on 3080."""
from pathlib import Path
import hashlib,json,os,platform,shutil,subprocess

COMMIT='a518f79e77e168aa5158dacc58e0c25d562a42b8'
UPSTREAM_SHA='d48e439adf0dee521bd9ba60a7a82388af52a696ab4ea531ae80cca154dcd596'
COMPAT_SHA='5fb73990b63d4c350abda14729d388dbbd84b2327958dbd4cd0d302332b612e7'

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def install(root,stage):
 root=Path(root).resolve();stage=Path(stage).resolve()
 assert os.name=='nt' and platform.node()=='DESKTOP-2QQPN1H','REMOTE_3080_REQUIRED'
 assert sha(stage/('dsh-mc-agent-'+COMMIT+'.zip'))==UPSTREAM_SHA
 assert sha(stage/'MC-Friends-Mineflayer-r001-Windows-x64.zip')==COMPAT_SHA
 assert json.loads((stage/'deps088-result.json').read_text(encoding='utf8'))['ok']
 receipt=root/'.setup/mc-candidate-088-installed.json'
 assert not receipt.exists(),'CANDIDATE_ALREADY_INSTALLED_REVIEW_RECEIPT'
 for source,dest in [('compat','mc-compat-088'),('candidate','mc-candidate-088'),('extras','mc-extras-088')]:
  target=root/'tools'/dest;assert not target.exists(),'CANDIDATE_TARGET_EXISTS'
  shutil.move(str(stage/source),str(target))
 candidate=root/'tools/mc-candidate-088';compat=root/'tools/mc-compat-088';extras=root/'tools/mc-extras-088'
 patches=[]
 def patch(file,before,after):
  old=file.read_text(encoding='utf8');assert old.count(before)==1,'PINNED_PATCH_ANCHOR'
  file.write_text(old.replace(before,after),encoding='utf8',newline='\n')
  patches.append({'file':file.relative_to(root).as_posix(),'original_sha256':hashlib.sha256(old.encode()).hexdigest(),'patched_sha256':sha(file)})
 patch(candidate/'src/connection.mjs',"import { ensureDepGuard, isLandmineError, describeDepGuard } from './dep-guard.mjs'", "import { createRequire } from 'node:module'\nimport { ensureDepGuard, isLandmineError, describeDepGuard } from './dep-guard.mjs'")
 patch(candidate/'src/connection.mjs','const b = mineflayer.createBot({',"const factory = process.env.STREAM_MC_COMPAT_CLIENT ? createRequire(import.meta.url)(process.env.STREAM_MC_COMPAT_CLIENT).createBot : mineflayer.createBot\n    const b = factory({")
 patch(candidate/'index.js','const registry = new McRegistry(ctx, config)',"const registry = new McRegistry(ctx, config)\n  ctx.provide('streamMcCandidateRuntime088', { registry })")
 modules=candidate/'node_modules';modules.mkdir()
 for name,target in [('mineflayer',compat/'node_modules/mineflayer'),('vec3',compat/'node_modules/vec3'),('@deepseek-ai',root/'tools/dsh/node_modules/@deepseek-ai'),('sharp',extras/'node_modules/sharp')]:
  result=subprocess.run(['cmd.exe','/c','mklink','/J',str(modules/name),str(target)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=0x08000000)
  assert result.returncode==0,('JUNCTION_FAILED',name,result.stderr.decode(errors='replace'))
 files={}
 for folder in [candidate,compat]:
  for base,dirs,names in os.walk(folder,followlinks=False):
   dirs[:]=[name for name in dirs if not (Path(base)/name).is_symlink() and not (folder==candidate and name=='node_modules')]
   for name in names:
    p=Path(base)/name;files[p.relative_to(root).as_posix()]=sha(p)
 for p in [extras/'package.json',extras/'package-lock.json']:
  files[p.relative_to(root).as_posix()]=sha(p)
 value={'schema_version':1,'candidate':'dsh-mc-agent','commit':COMMIT,'upstream_archive_sha256':UPSTREAM_SHA,'compat_archive_sha256':COMPAT_SHA,
  'patches':patches,'files':files,'fixed_protocol_tree_updated_by_npm':False,'automatic_input_authorized':False}
 receipt.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
 history=root/'.setup/mc-candidate-088-history';history.mkdir()
 native=root/'configs/mc-game.json';shutil.copyfile(native,history/'mc-game.native-087.json')
 cfg=json.loads(native.read_text(encoding='utf8'));cfg['enabled']=False;cfg['planner']['enabled']=False;cfg['planner']['autostart']=False
 native.write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf8')
 cfg=json.loads((root/'configs/mc-dsh-candidate.example.json').read_text(encoding='utf8'));cfg['enabled']=True
 (root/'configs/mc-dsh-candidate.private.json').write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf8')
 return {'installed':True,'commit':COMMIT,'verified_files':len(files),'patches':patches,'native_game_configuration_backup':str(history/'mc-game.native-087.json')}
