"""Child-only Windows profile layout and actual known-folder verification."""
from __future__ import annotations

import argparse
import ctypes
import json
from pathlib import Path
import subprocess

from .common import AdmissionError,inside,native_only


def configure(environment,profile):
    profile=Path(profile).resolve();profile.mkdir(parents=True,exist_ok=True)
    environment['USERPROFILE']=str(profile)
    for key,suffix in [('APPDATA','AppData/Roaming'),('LOCALAPPDATA','AppData/Local'),
                       ('TEMP','AppData/Local/Temp'),('TMP','AppData/Local/Temp')]:
        path=profile/suffix;path.mkdir(parents=True,exist_ok=True);environment[key]=str(path)
    (profile/'Documents').mkdir(exist_ok=True)
    return environment


def observe(profile):
    native_only();profile=Path(profile).resolve();rows=[]
    for identifier,suffix in ((26,'AppData/Roaming'),(28,'AppData/Local')):
        buffer=ctypes.create_unicode_buffer(32768)
        code=ctypes.windll.shell32.SHGetFolderPathW(None,identifier,None,0,buffer)
        actual=Path(buffer.value).resolve() if buffer.value else None
        expected=profile/suffix
        if code or actual!=expected or not expected.is_dir():
            raise AdmissionError('ISOLATED_WINDOWS_KNOWN_FOLDER_NOT_OBSERVED')
        rows.append({'csidl':identifier,'path':str(actual),'exists':True})
    return {'verified':True,'fresh_child_known_folders':rows,'registry_changes':0}


def verify_in_child(root,environment,profile):
    executable=inside(root,'runtime/isaac-native/Scripts/python.exe')
    result=subprocess.run([str(executable),'-X','utf8','-B','-m','integration.issac.windows_profile',
        '--profile',str(profile)],cwd=root,env=environment,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        timeout=20,stdin=subprocess.DEVNULL,creationflags=0x08000000)
    if result.returncode:raise AdmissionError('ISOLATED_WINDOWS_PROFILE_PROBE_FAILED')
    value=json.loads(result.stdout.decode('utf-8-sig'))
    if value.get('verified') is not True:raise AdmissionError('ISOLATED_WINDOWS_PROFILE_NOT_VERIFIED')
    return value


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--profile',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(observe(args.profile),ensure_ascii=False))
