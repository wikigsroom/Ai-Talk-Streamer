"""Retained native LM Studio only; no download, cloud route or shared unload."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import time
import urllib.request

from .common import AdmissionError, Audit, file_hash, inside, local_url, read_json, write_json


class LocalModel:
    def __init__(self, root):
        self.root=Path(root).resolve()
        self.config=read_json(inside(root,'private/issac/model.json'))
        self.url=local_url(self.config['base_url'])
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.audit=Audit(inside(root,'state/isaac-strategy/local-model-events.jsonl'))

    def models(self):
        try:
            request=urllib.request.Request(self.url+'/models',headers=self.headers())
            with self.opener.open(request,timeout=4) as response:
                return json.load(response)['data']
        except Exception:
            raise AdmissionError('LOCAL_MODEL_SERVER_UNAVAILABLE') from None

    def headers(self):
        key=self.config.get('api_key','')
        return {'Content-Type':'application/json',**({'Authorization':'Bearer '+key} if key else {})}

    def command(self, *args, timeout=90):
        candidates=list(inside(self.root,'tools/lmstudio/bin').rglob('lms.exe'))
        if len(candidates)!=1:
            raise AdmissionError('ONE_PREPARED_NATIVE_LMS_CLI_REQUIRED')
        result=subprocess.run([str(candidates[0]),*args],cwd=self.root,timeout=timeout,
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=0x08000000)
        if result.returncode:
            raise AdmissionError('NATIVE_LMS_COMMAND_FAILED')
        return result.stdout

    def admit_retained_files(self):
        rows=self.config.get('retained_model_files')
        if not isinstance(rows,list) or not rows:
            raise AdmissionError('EXISTING_MODEL_FILE_PROVENANCE_REQUIRED')
        allowed=Path('C:/dev/lmstudio/models').resolve()
        for row in rows:
            path=Path(row['path']).resolve()
            if (not path.is_relative_to(allowed) or path.suffix.lower()!='.gguf'
                    or not path.is_file() or path.stat().st_size!=row['bytes']
                    or file_hash(path)!=row['sha256']):
                raise AdmissionError('RETAINED_LOCAL_MODEL_CHANGED')
        return {'files':len(rows),'new_model_download_bytes':0}

    def prepare(self):
        provenance=self.admit_retained_files()
        try:
            models=self.models()
        except AdmissionError:
            # Never stop another backend. CLI failure is a visible rejection.
            from urllib.parse import urlsplit
            endpoint=urlsplit(self.url)
            self.command('server','start','--port',str(endpoint.port),'--bind','127.0.0.1')
            models=self.models()
        expected=self.config['model']
        if not any(x.get('id')==expected for x in models):
            key=self.config.get('retained_model_key')
            fraction=self.config.get('gpu_offload')
            if (not isinstance(key,str) or not key.strip() or type(fraction) not in (float,int)
                    or not 0<=fraction<=.6):
                raise AdmissionError('BOUNDED_EXISTING_MODEL_LOAD_SETTINGS_REQUIRED')
            # Reserve the already selected media budget; no optimistic GPU
            # allocation based solely on the marketing name of this device.
            raw=subprocess.check_output(['nvidia-smi','--query-gpu=memory.free','--format=csv,noheader,nounits'],
                        timeout=10,text=True,creationflags=0x08000000)
            if int(raw.strip())<self.config.get('minimum_free_before_load_mib',30000):
                raise AdmissionError('EXISTING_GPU_TASKS_RETAINED_WAIT_FOR_CAPACITY')
            self.command('load',key,'--identifier',expected,'--context-length',str(self.config.get('context_window',16384)),
                         '--gpu',str(fraction),'--yes',timeout=180)
            models=self.models()
        if not any(x.get('id')==expected for x in models):
            raise AdmissionError('ACTUAL_LOCAL_MODEL_ID_NOT_LOADED')
        receipt={'backend':'native_LM_Studio','model':expected,'base_url':self.url,
                 'retained_files':provenance['files'],'cloud_fallback':False,'new_model_download_bytes':0,
                 'model_qualified':False,'at_unix':time.time()}
        write_json(inside(self.root,'state/isaac-strategy/local-backend.json'),receipt)
        self.audit.append('retained_model_prepared',model=expected)
        return receipt

    def complete(self, body, *, timeout=43):
        payload={'model':self.config['model'],'stream':False,**body}
        request=urllib.request.Request(self.url+'/chat/completions',data=json.dumps(payload,ensure_ascii=False).encode(),headers=self.headers())
        with self.opener.open(request,timeout=timeout) as response:
            result=json.load(response)
        if result.get('model')!=self.config['model']:
            # Some local engines return the underlying GGUF name. Its exact
            # accepted mapping must be recorded in private configuration.
            if not result.get('model') or result.get('model')!=self.config.get('response_model_id'):
                raise AdmissionError('UNEXPECTED_MODEL_RESPONSE_ID')
        return result
