"""Owned native LM Studio, retained local weights and observable preparation."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.request
from urllib.parse import urlsplit

from .common import AdmissionError, Audit, digest, file_hash, inside, local_url, read_json, write_json
from .resources import MEDIA_RESERVE_MIB, MIB, available_for_initialization, estimate_fits, parse_estimate, snapshot


class LocalModel:
    def __init__(self, root):
        self.root=Path(root).resolve()
        self.config=read_json(inside(root,'private/issac/model.json'))
        self.url=local_url(self.config['base_url'])
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.audit=Audit(inside(root,'state/isaac-strategy/local-model-events.jsonl'))
        self.candidate=read_json(inside(root,'.setup/candidate.json'))['id']
        self.registration=inside(root,'.setup/issac-lmstudio-owner.json')
        self.profile=inside(root,'state/isaac-strategy/lmstudio-profile')
        self.home=inside(root,'tools/lmstudio/home')
        self.application=inside(root,'tools/lmstudio/app/LM Studio.exe')
        self.cli=inside(root,'tools/lmstudio/bin/lms.exe')
        self.sequence=0
        self.verified_application_signature=None
        self.last_profile_proof=None

    def progress(self,stage,**values):
        self.sequence+=1
        row={'stage':stage,'candidate_id':self.candidate,'sequence':self.sequence,'at_unix':time.time(),**values}
        write_json(inside(self.root,'state/isaac-strategy/model-preparation.json'),row)
        self.audit.append('preparation_progress',**row)
        print(json.dumps(row,ensure_ascii=False),flush=True)

    def models(self):
        try:
            request=urllib.request.Request(self.url+'/models',headers=self.headers())
            with self.opener.open(request,timeout=4) as response:
                data=json.load(response)['data']
            if not isinstance(data,list):raise ValueError('models')
            return data
        except Exception:
            raise AdmissionError('LOCAL_MODEL_SERVER_UNAVAILABLE') from None

    def headers(self):
        key=self.config.get('api_key','')
        return {'Content-Type':'application/json',**({'Authorization':'Bearer '+key} if key else {})}

    def environment(self):
        from .preparation import runtime_environment
        from .windows_profile import configure
        env=runtime_environment(self.root,'model')
        self.profile.mkdir(parents=True,exist_ok=True)
        self.home.mkdir(parents=True,exist_ok=True)
        pointer=self.profile/'.lmstudio-home-pointer'
        if pointer.exists() and Path(pointer.read_text('utf8').strip()).resolve()!=self.home:
            raise AdmissionError('ISOLATED_LMSTUDIO_HOME_POINTER_CONFLICT')
        pointer.write_text(str(self.home),'utf8')
        # These values belong only to the child process. No real user profile,
        # global home pointer, registry entry or credential store is changed.
        configure(env,self.profile)
        # Pin discovery to the API metadata published by this isolated GUI.
        # The prepared CLI supports this override; it must not scan/adopt a
        # different user's GUI if startup is still in progress.
        env.update(NO_COLOR='1',FORCE_COLOR='0',
                   LMS_API_SERVER_INFO_PATH=str(self.home/'.internal/http-server.json'))
        return env

    def command(self,*args,timeout=120):
        if not self.cli.is_file():raise AdmissionError('PREPARED_NATIVE_LMS_CLI_REQUIRED')
        result=subprocess.run([str(self.cli),*args],cwd=self.root,env=self.environment(),timeout=timeout,
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,stdin=subprocess.DEVNULL,creationflags=0x08000000)
        output=result.stdout.decode('utf-8-sig',errors='replace')
        self.audit.append('native_cli_result',command=list(args[:2]),exit_code=result.returncode,
                          private_stdout=output[-4000:],private_stderr=result.stderr.decode('utf8',errors='replace')[-4000:])
        if result.returncode:raise AdmissionError('NATIVE_LMS_COMMAND_FAILED')
        return output

    def model_directory(self):
        retained=Path('C:/dev/lmstudio/models').resolve()
        target=self.home/'models'
        if target.exists():
            if target.resolve()!=retained:raise AdmissionError('ISOLATED_LMS_MODEL_DIRECTORY_CONFLICT')
            return
        result=subprocess.run([r'C:\Windows\System32\cmd.exe','/d','/c','mklink','/J',str(target),str(retained)],
             capture_output=True,timeout=10,creationflags=0x08000000)
        if result.returncode or target.resolve()!=retained:
            raise AdmissionError('EXISTING_MODEL_DIRECTORY_JUNCTION_NOT_CREATED')

    def app_owner(self):
        import psutil
        row=read_json(self.registration);process=psutil.Process(row['pid'])
        stat=self.application.stat()
        signature=(stat.st_size,stat.st_mtime_ns,stat.st_ino,row['executable_sha256'])
        if signature!=self.verified_application_signature:
            if file_hash(self.application)!=row['executable_sha256']:
                raise AdmissionError('OWNED_LMSTUDIO_EXECUTABLE_CHANGED')
            self.verified_application_signature=signature
        if (process.create_time()!=row['created_at'] or Path(process.exe()).resolve()!=self.application
                or row.get('profile')!=str(self.profile) or row.get('installation')!=str(self.root)):
            raise AdmissionError('OWNED_LMSTUDIO_IDENTITY_REQUIRED')
        return process,row

    def start_application(self):
        import psutil
        try:
            process,row=self.app_owner()
            return row
        except (OSError,ValueError,psutil.NoSuchProcess):pass
        foreign=[]
        for p in psutil.process_iter(['name','exe']):
            try:
                if (p.info['name'] or '').lower()=='lm studio.exe':foreign.append(p.pid)
            except (psutil.NoSuchProcess,psutil.AccessDenied):pass
        if foreign:raise AdmissionError('EXISTING_LMSTUDIO_CLIENT_PRESERVED_NO_SINGLE_INSTANCE_ADOPTION')
        if not self.application.is_file():raise AdmissionError('COPIED_NATIVE_LMSTUDIO_APPLICATION_REQUIRED')
        self.model_directory()
        env=self.environment();data=self.profile/'electron-user-data';data.mkdir(exist_ok=True)
        from .windows_profile import verify_in_child
        known_folders=verify_in_child(self.root,env,self.profile)
        started=time.time()
        handle=subprocess.Popen([str(self.application),'--user-data-dir='+str(data)],cwd=self.application.parent,env=env,
                stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=0x08000000)
        time.sleep(3)
        if handle.poll() is not None:raise AdmissionError('OWNED_LMSTUDIO_APPLICATION_EXITED')
        process=psutil.Process(handle.pid)
        row={'pid':process.pid,'created_at':process.create_time(),'executable':str(self.application),
             'executable_sha256':file_hash(self.application),'profile':str(self.profile),'installation':str(self.root),
             'known_folder_proof':known_folders,
             'launched_unix':started,'profile_requested_only':True,'runtime_profile_verified':False}
        write_json(self.registration,row)
        self.audit.append('owned_native_application_launched',pid=process.pid,profile_requested_only=True)
        return row

    def application_api(self):
        """Observe the real internal API, independently of a live launcher PID."""
        import psutil
        process,_=self.app_owner()
        ids={p.pid for p in [process,*process.children(recursive=True)]}
        path=self.home/'.internal/http-server.json'
        try:info=read_json(path)
        except (OSError,ValueError):return None
        if not isinstance(info,dict):raise AdmissionError('ISOLATED_APPLICATION_API_METADATA_INVALID')
        port=info.get('port');pid=info.get('pid')
        if type(port) is not int or not 1<=port<=65535:return None
        if pid is not None and (type(pid) is not int or pid not in ids):
            if type(pid) is int and not psutil.pid_exists(pid):return None
            raise AdmissionError('ISOLATED_APPLICATION_API_METADATA_OWNER_CHANGED')
        listeners=[x for x in psutil.net_connections(kind='tcp')
                   if x.status==psutil.CONN_LISTEN and x.laddr.port==port]
        if not listeners:return None
        if any(x.pid not in ids or x.laddr.ip not in {'127.0.0.1','::1'} for x in listeners):
            raise AdmissionError('ISOLATED_APPLICATION_API_LISTENER_NOT_OWNED_OR_NOT_LOOPBACK')
        return {'owner_pid':process.pid,'port':port,'listener_pids':sorted({x.pid for x in listeners}),
                'metadata_sha256':file_hash(path),'loopback_only':True,'at_unix':time.time()}

    def wait_application_api(self,timeout=120):
        deadline=time.monotonic()+timeout;last_progress=0
        while time.monotonic()<deadline:
            observed=self.application_api()
            if observed is not None:
                self.audit.append('isolated_application_api_observed',**observed)
                return observed
            if time.monotonic()-last_progress>=10:
                self.progress('waiting_for_actual_application_api',remaining_seconds=max(0,deadline-time.monotonic()))
                last_progress=time.monotonic()
            time.sleep(1)
        raise AdmissionError('ISOLATED_APPLICATION_API_READY_DEADLINE')

    def verify_server_owner(self):
        import psutil
        process,row=self.app_owner()
        owned=[process,*process.children(recursive=True)]
        ids={p.pid for p in owned}
        port=urlsplit(self.url).port
        listeners=[x for x in psutil.net_connections(kind='tcp') if x.status==psutil.CONN_LISTEN
                   and x.laddr.port==port and x.laddr.ip in {'127.0.0.1','0.0.0.0','::','::1'}]
        if not listeners or any(x.pid not in ids or x.laddr.ip!='127.0.0.1' for x in listeners):
            raise AdmissionError('LOCAL_MODEL_PORT_NOT_OWNED_OR_NOT_LOOPBACK')
        if (self.last_profile_proof and self.last_profile_proof['owner_pid']==process.pid
                and time.time()-self.last_profile_proof['at_unix']<10):return self.last_profile_proof
        environment=process.environ()
        if environment.get('USERPROFILE')!=str(self.profile) or '--user-data-dir='+str(self.profile/'electron-user-data') not in process.cmdline():
            raise AdmissionError('LOCAL_MODEL_PROFILE_ARGUMENTS_NOT_OBSERVED')
        observed=[];foreign=[]
        for p in owned:
            try:
                for f in p.open_files():
                    path=Path(f.path).resolve()
                    if path.is_relative_to(self.profile) or path.is_relative_to(self.home):observed.append(str(path))
                    elif ('.lmstudio' in path.as_posix().lower() or '/lm studio/' in path.as_posix().lower()) and not path.is_relative_to(Path('C:/dev/lmstudio/models')):
                        foreign.append(str(path))
            except (psutil.NoSuchProcess,psutil.AccessDenied):continue
        # The copied GUI overrides Chromium's requested user-data-dir with its
        # actual Windows roaming folder. An empty requested directory or log is
        # insufficient: require a real open profile file in that roaming root.
        runtime_root=self.profile/'AppData/Roaming/LM Studio'
        runtime_files=[p for p in runtime_root.rglob('*') if p.is_file()]
        actual_profile_handles=[p for p in observed if Path(p).resolve().is_relative_to(runtime_root)]
        if foreign or not runtime_files or not actual_profile_handles:
            raise AdmissionError('ISOLATED_LMSTUDIO_RUNTIME_PROFILE_NOT_CONFIRMED')
        proof={'owner_pid':process.pid,'listener_pids':sorted({x.pid for x in listeners}),'loopback_only':True,
               'profile_runtime_files':len(runtime_files),'observed_profile_open_files':observed[:30],
               'actual_roaming_profile':str(runtime_root),'actual_roaming_profile_open_files':actual_profile_handles[:30],
               'foreign_profile_files':foreign,'at_unix':time.time()}
        row.update(profile_requested_only=False,runtime_profile_verified=True,profile_proof=proof)
        write_json(self.registration,row)
        self.last_profile_proof=proof
        return proof

    def admit_retained_files(self):
        rows=self.config.get('retained_model_files')
        if not isinstance(rows,list) or not rows:raise AdmissionError('EXISTING_MODEL_FILE_PROVENANCE_REQUIRED')
        allowed=Path('C:/dev/lmstudio/models').resolve()
        destination=inside(self.root,'state/isaac-strategy/model-file-verification.json')
        cache=read_json(destination) if destination.is_file() else {}
        verified=[]
        for index,row in enumerate(rows):
            path=Path(row['path']).resolve();before=path.stat()
            signature={'bytes':before.st_size,'mtime_ns':before.st_mtime_ns,'ctime_ns':before.st_ctime_ns,'file_id':before.st_ino}
            if (not path.is_relative_to(allowed) or path.suffix.lower()!='.gguf' or not path.is_file()
                    or before.st_size!=row['bytes'] or not re.fullmatch('[0-9a-f]{64}',row['sha256'])):
                raise AdmissionError('RETAINED_LOCAL_MODEL_CHANGED')
            cached=next((x for x in cache.get('files',[]) if x.get('path')==str(path)),{})
            reused=(cache.get('candidate_id')==self.candidate and cached.get('signature')==signature
                    and cached.get('sha256')==row['sha256'])
            if not reused:
                self.progress('hashing_retained_weights',file_number=index+1,files=len(rows),bytes_done=0,bytes_total=before.st_size)
                sha=hashlib.sha256();done=0;start=time.monotonic();last=start
                with path.open('rb') as stream:
                    while block:=stream.read(8*MIB):
                        sha.update(block);done+=len(block)
                        if time.monotonic()-start>1800:raise AdmissionError('RETAINED_WEIGHT_HASH_DEADLINE')
                        if time.monotonic()-last>=10:
                            self.progress('hashing_retained_weights',file_number=index+1,files=len(rows),bytes_done=done,bytes_total=before.st_size)
                            last=time.monotonic()
                after=path.stat()
                if (sha.hexdigest()!=row['sha256'] or signature!={'bytes':after.st_size,'mtime_ns':after.st_mtime_ns,
                        'ctime_ns':after.st_ctime_ns,'file_id':after.st_ino}):raise AdmissionError('RETAINED_LOCAL_MODEL_CHANGED')
            verified.append({'path':str(path),'sha256':row['sha256'],'signature':signature,'full_hash_reused_in_same_candidate':reused})
            write_json(destination,{'candidate_id':self.candidate,'files':verified,'verified_at_unix':time.time()})
        return {'files':len(rows),'new_model_download_bytes':0,'verification_receipt_sha256':file_hash(destination)}

    def prepare(self,*,capacity_wait_seconds=0):
        if type(capacity_wait_seconds) is not int or not 0<=capacity_wait_seconds<=3600:
            raise AdmissionError('BOUNDED_CAPACITY_WAIT_REQUIRED')
        self.progress('observing_existing_capacity')
        observed=snapshot()
        try:models=self.models()
        except AdmissionError:models=None
        if models is not None:self.verify_server_owner()
        expected=self.config['model']
        already_loaded=models is not None and any(x.get('id')==expected for x in models)
        deadline=time.monotonic()+capacity_wait_seconds;last_progress=0
        while not already_loaded and not available_for_initialization(observed,MEDIA_RESERVE_MIB+4096):
            remaining=deadline-time.monotonic()
            if time.monotonic()-last_progress>=10 or remaining<=0:
                self.progress('waiting_for_existing_gpu_tasks',observed=observed,
                              capacity_wait_seconds=capacity_wait_seconds,remaining_seconds=max(0,remaining))
                last_progress=time.monotonic()
            if remaining<=0:raise AdmissionError('EXISTING_GPU_TASKS_RETAINED_WAIT_FOR_CAPACITY')
            time.sleep(min(2,remaining));observed=snapshot()
        provenance=self.admit_retained_files()
        if models is None:
            self.progress('starting_isolated_native_application')
            self.start_application()
            self.wait_application_api()
            self.progress('starting_loopback_server')
            self.command('server','start','--port',str(urlsplit(self.url).port),'--bind','127.0.0.1',timeout=180)
            models=self.models()
        profile=self.verify_server_owner()
        plan=None
        if not any(x.get('id')==expected for x in models):
            key=self.config.get('retained_model_key');fraction=self.config.get('gpu_offload')
            context=self.config.get('context_window',16384)
            if (not isinstance(key,str) or not key.strip() or type(fraction) not in (float,int)
                    or not 0<=fraction<=.6 or type(context) is not int or context<4096):
                raise AdmissionError('BOUNDED_EXISTING_MODEL_LOAD_SETTINGS_REQUIRED')
            help_text=self.command('load','--help')
            if '--estimate-only' not in help_text:raise AdmissionError('PREPARED_LMS_RESOURCE_ESTIMATOR_NOT_SUPPORTED')
            observed=snapshot();plans=[]
            for ratio in sorted({round(fraction,3),round(fraction*.75,3),round(fraction*.5,3)},reverse=True):
                self.progress('estimating_model_resources',gpu_offload=ratio,context_window=context)
                arguments=['load',key,'--context-length',str(context),'--gpu',str(ratio),'--yes']
                estimate=parse_estimate(self.command(*arguments,'--estimate-only',timeout=180))
                fits=estimate_fits(estimate,observed)
                plans.append({'gpu_offload':ratio,'estimate':estimate,'fits':fits})
                if fits:plan=plans[-1];break
            write_json(inside(self.root,'state/isaac-strategy/model-resource-plan.json'),
                {'candidate_id':self.candidate,'observed':observed,'media_reserve_mib':MEDIA_RESERVE_MIB,'plans':plans,'selected':plan})
            if plan is None:raise AdmissionError('RETAINED_MODEL_AND_MEDIA_DO_NOT_FIT_MEASURED_CAPACITY')
            if not estimate_fits(plan['estimate'],snapshot()):raise AdmissionError('CAPACITY_CHANGED_BEFORE_MODEL_LOAD')
            self.progress('loading_retained_model',gpu_offload=plan['gpu_offload'],context_window=context)
            self.command('load',key,'--identifier',expected,'--context-length',str(context),
                '--gpu',str(plan['gpu_offload']),'--yes',timeout=900)
            models=self.models()
        if not any(x.get('id')==expected for x in models):raise AdmissionError('ACTUAL_LOCAL_MODEL_ID_NOT_LOADED')
        profile=self.verify_server_owner()
        receipt={'backend':'native_LM_Studio','candidate_id':self.candidate,'model':expected,'base_url':self.url,
                 'retained_files':provenance['files'],'file_verification':provenance,'profile_proof':profile,
                 'resource_plan':plan,'cloud_fallback':False,'new_model_download_bytes':0,
                 'model_qualified':False,'at_unix':time.time()}
        write_json(inside(self.root,'state/isaac-strategy/local-backend.json'),receipt)
        self.progress('retained_model_prepared_not_qualified')
        return receipt

    def complete(self,body,*,timeout=43):
        self.verify_server_owner()
        payload={**body,'model':self.config['model'],'stream':False}
        request=urllib.request.Request(self.url+'/chat/completions',data=json.dumps(payload,ensure_ascii=False).encode(),headers=self.headers())
        with self.opener.open(request,timeout=timeout) as response:result=json.load(response)
        if result.get('model')!=self.config['model']:
            if not result.get('model') or result.get('model')!=self.config.get('response_model_id'):
                raise AdmissionError('UNEXPECTED_MODEL_RESPONSE_ID')
        if not result.get('choices'):raise AdmissionError('ACTUAL_LOCAL_MODEL_CHOICES_REQUIRED')
        return result
