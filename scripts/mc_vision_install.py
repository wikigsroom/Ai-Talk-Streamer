"""Install approved Qwen3-VL GGUF and native llama.cpp from a verified download cache.

No inference or service start. Downloads are separate from this local, pinned import.
"""
from pathlib import Path, PurePosixPath
import json,os,platform,socket,subprocess,uuid,zipfile
from mc_deployment import installed_source_identity,require,sha,read
from mc_offline_install import copy_verified,no_links
from native_operation import operation,atomic_json

ROOT=Path(__file__).resolve().parents[1]
TAG='b11960'
ZIP='llama-b11960-bin-win-cpu-x64.zip'
ZIP_SHA='73f962f82850d244db47eaacb9d913637027b82399124324298576d58c5f4287'
MODELS={
 'model':('Qwen3VL-4B-Instruct-Q4_K_M.gguf','models/vision/qwen3-vl-4b-q4_k_m.gguf',2497281664,'66358cb18bb6b3b1b6675aa412c7a88ef01d228f481184d13668e5201c730a0a'),
 'projector':('mmproj-Qwen3VL-4B-Instruct-F16.gguf','models/vision/mmproj-f16.gguf',836180256,'256f3a43bd4205ffef48d6b92715e1e70b5b0e9aef06522584967513a9985331'),
}
CUDA_ARCHIVES={
 'llama-b11960-bin-win-cuda-12.4-x64.zip':'8d9d819261de10cc2f03921b8b79c779c5c458e21edb60c170ee30a7d462d684',
 'cudart-llama-bin-win-cuda-12.4-x64.zip':'8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6',
}
VULKAN_ARCHIVES={'llama-b11960-bin-win-vulkan-x64.zip':'bac6914b5e83523eb008c6789eaa12669f93fbc196c3b9e8237b6672323b33e9'}


def install(root,cache):
 root=Path(root).resolve();cache=Path(cache).resolve()
 require(os.name=='nt' and platform.node().casefold()=='desktop-2qqpn1h','MC_NATIVE_RUNTIME_REQUIRES_REMOTE_3080')
 identity=installed_source_identity(root)
 archive=no_links(cache/ZIP,cache);require(archive.stat().st_size==24407745 and sha(archive)==ZIP_SHA,'MC_VISION_ARCHIVE_PIN')
 require(not (root/'configs/mc-vision.json').exists() and not (root/'runtimes/vision').exists(), 'MC_VISION_NEW_INSTALLATION_REQUIRED')
 with operation(root,'mc-vision-approved-file-install'):
  pins={};files={}
  for key,(name,target,size,checksum) in MODELS.items():
   pin={'bytes':size,'sha256':checksum};copy_verified(no_links(cache/name,cache),no_links(root/target,root),pin)
   pins[key]={'path':target,**pin}
  runtime=root/'runtimes/vision';runtime.mkdir(parents=True)
  with zipfile.ZipFile(archive) as z:
   require(0<len(z.infolist())<200 and sum(i.file_size for i in z.infolist())<512*1024**2,'MC_VISION_ARCHIVE_LIMIT')
   aliases=set()
   for info in z.infolist():
    name=info.filename;p=PurePosixPath(name)
    require(name and not p.is_absolute() and '..' not in p.parts and '\\' not in name and ':' not in name
            and not ((info.external_attr>>16)&0o170000)==0o120000 and name.casefold() not in aliases,'MC_VISION_ARCHIVE_PATH')
    aliases.add(name.casefold());target=no_links(runtime/name,root)
    if info.is_dir():target.mkdir(parents=True,exist_ok=True);continue
    target.parent.mkdir(parents=True,exist_ok=True)
    with z.open(info) as source,target.open('xb') as dest:
     while data:=source.read(1024*1024):dest.write(data)
    files[target.relative_to(root).as_posix()]={'bytes':target.stat().st_size,'sha256':sha(target)}
  executables=list(runtime.rglob('llama-server.exe'));require(len(executables)==1,'MC_VISION_SERVER_MISSING')
  executable=executables[0]
  result=subprocess.run([str(executable),'--version'],cwd=executable.parent,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30,creationflags=0x08000000)
  version=result.stdout+'\n'+result.stderr
  require(result.returncode==0 and '11960' in version and '8642541b' in version,'MC_VISION_BUILD_VERSION')
  pins['executable']={'path':executable.relative_to(root).as_posix(),**files[executable.relative_to(root).as_posix()]}
  # This is the build identity exposed by llama.cpp's pinned server release.
  lock={'schema_version':1,'runtime_id':'qwen3vl4b-q4km-llama-b11960-cpu-v1','base_url':'http://127.0.0.1:8019/',
        'model_alias':'mc-vision-qwen3-vl-4b','build_info':'b11960-8642541b2',**pins}
  atomic_json(root,root/'configs/mc-vision.json',lock)
  receipt={'schema_version':1,'ok':True,'source_snapshot_sha256':identity['snapshot_sha256'],
           'archive_sha256':ZIP_SHA,'model_revision':'1cd86afb9a95c410a6038ab3b40d8b578c892266','models':pins,
           'runtime_files':files,'native_version_output':version.strip(),'models_started':False,'downloads_performed':False,
           'user_approved_model_download':True,'public_broadcast_started':False}
  atomic_json(root,root/'.setup/mc-vision-install.json',receipt)
 return {'ok':True,'runtime_files':len(files),'model_bytes':sum(pin['bytes'] for key,pin in pins.items() if key!='executable'),
         'model_forward_run':False,'services_started':False}


def install_accelerated(root,cache,backend):
 """Select the same pinned model with a reviewed native GPU runtime, while stopped."""
 root=Path(root).resolve();cache=Path(cache).resolve()
 require(os.name=='nt' and platform.node().casefold()=='desktop-2qqpn1h','MC_NATIVE_RUNTIME_REQUIRES_REMOTE_3080')
 identity=installed_source_identity(root)
 require(backend in ('cuda124','vulkan'),'MC_VISION_BACKEND')
 archive_pins=CUDA_ARCHIVES if backend=='cuda124' else VULKAN_ARCHIVES
 with operation(root,'mc-vision-approved-'+backend+'-install'):
  with socket.socket() as probe:require(probe.connect_ex(('127.0.0.1',8019))!=0,'MC_VISION_STOP_BEFORE_INSTALL')
  import psutil
  anchor=str(root/'scripts/mc_vision_service.py').casefold()
  for process in psutil.process_iter(['cmdline']):
   try:require(anchor not in [str(a).replace('/','\\').casefold() for a in process.info['cmdline'] or []],'MC_VISION_STOP_BEFORE_INSTALL')
   except (psutil.NoSuchProcess,psutil.AccessDenied):continue
  runtime=no_links(root/'runtimes/vision'/backend,root)
  require(not runtime.exists(),'MC_VISION_GPU_RUNTIME_EXISTS')
  archives=[]
  for name,checksum in archive_pins.items():
   path=no_links(cache/name,cache)
   require(0<path.stat().st_size<1024**3 and sha(path)==checksum,'MC_VISION_ARCHIVE_PIN')
   archives.append(path)
  pins={}
  for key,(name,target,size,checksum) in MODELS.items():
   path=no_links(root/target,root);pin={'bytes':size,'sha256':checksum}
   if path.exists():require(path.stat().st_size==size and sha(path)==checksum,'MC_VISION_MODEL_PIN')
   else:copy_verified(no_links(cache/name,cache),path,pin)
   pins[key]={'path':target,**pin}
  runtime.mkdir(parents=True);files={};aliases={}
  for archive in archives:
   with zipfile.ZipFile(archive) as package:
    require(0<len(package.infolist())<200 and sum(i.file_size for i in package.infolist())<2*1024**3,'MC_VISION_ARCHIVE_LIMIT')
    for entry in package.infolist():
     name=entry.filename;p=PurePosixPath(name)
     require(name and not p.is_absolute() and '..' not in p.parts and '\\' not in name and ':' not in name
             and not ((entry.external_attr>>16)&0o170000)==0o120000,'MC_VISION_ARCHIVE_PATH')
     require(name.casefold() not in aliases or aliases[name.casefold()]==name,'MC_VISION_ARCHIVE_PATH')
     aliases[name.casefold()]=name;target=no_links(runtime/name,root)
     if entry.is_dir():target.mkdir(parents=True,exist_ok=True);continue
     target.parent.mkdir(parents=True,exist_ok=True)
     if target.exists():
      import hashlib
      value=hashlib.sha256()
      with package.open(entry) as stream:
       while data:=stream.read(1024*1024):value.update(data)
      require(target.stat().st_size==entry.file_size and sha(target)==value.hexdigest(),'MC_VISION_ARCHIVE_COLLISION')
     else:
      with package.open(entry) as source,target.open('xb') as dest:
       while data:=source.read(1024*1024):dest.write(data)
     files[target.relative_to(root).as_posix()]={'bytes':target.stat().st_size,'sha256':sha(target)}
  servers=list(runtime.rglob('llama-server.exe'));require(len(servers)==1,'MC_VISION_SERVER_MISSING');executable=servers[0]
  dll_dirs=sorted({str(path.parent) for path in runtime.rglob('*.dll')})
  environment={**os.environ,'PATH':os.pathsep.join(dll_dirs+[os.environ.get('PATH','')])}
  native=subprocess.run([str(executable),'--version'],cwd=executable.parent,env=environment,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30,creationflags=0x08000000)
  version=native.stdout+'\n'+native.stderr
  require(native.returncode==0 and '11960' in version and '8642541b2' in version,'MC_VISION_BUILD_VERSION')
  pins['executable']={'path':executable.relative_to(root).as_posix(),**files[executable.relative_to(root).as_posix()]}
  lock={'schema_version':1,'runtime_id':'qwen3vl4b-q4km-llama-b11960-'+backend+'-v1','base_url':'http://127.0.0.1:8019/',
        'model_alias':'mc-vision-qwen3-vl-4b','build_info':'b11960-8642541b2',**pins}
  history=root/'.setup/mc-vision-history'/uuid.uuid4().hex
  for relative in ['configs/mc-vision.json','.setup/mc-vision-install.json']:
   path=no_links(root/relative,root)
   if path.exists():
    history.mkdir(parents=True,exist_ok=True);atomic_json(root,history/path.name,read(path))
  receipt={'schema_version':1,'ok':True,'source_snapshot_sha256':identity['snapshot_sha256'],'backend':backend,
           'archives':{p.name:archive_pins[p.name] for p in archives},'model_revision':'1cd86afb9a95c410a6038ab3b40d8b578c892266',
           'models':pins,'runtime_files':files,'native_version_output':version.strip(),'models_started':False,
           'downloads_performed':False,'user_approved_model_download':True,'public_broadcast_started':False}
  atomic_json(root,root/'.setup/mc-vision-install.json',receipt)
  atomic_json(root,root/'configs/mc-vision.json',lock)
 return {'ok':True,'backend':backend,'runtime_files':len(files),'model_forward_run':False,'services_started':False}


if __name__=='__main__':
 import argparse
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--cache',type=Path,required=True)
 parser.add_argument('--backend',choices=['cpu','cuda124','vulkan'],default='cpu');args=parser.parse_args()
 print(json.dumps(install(ROOT,args.cache) if args.backend=='cpu' else install_accelerated(ROOT,args.cache,args.backend),ensure_ascii=False))
