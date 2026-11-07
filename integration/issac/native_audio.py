"""Scoped WASAPI session envelope for the verified game process, with expiry.

Only Windows per-application mixer gain is changed. Game files, master device
gain and foreign applications are untouched. A mixer receipt is not proof that
Livehime captured audible sound; the recording has a separate audio review.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import threading
import time
import uuid

from .common import AdmissionError,Audit,inside,native_only


class GUID(C.Structure):
    _fields_=[('data',C.c_ubyte*16)]
    def __init__(self,value):super().__init__((C.c_ubyte*16).from_buffer_copy(uuid.UUID(value).bytes_le))


def call(pointer,index,result,args,*values):
    table=C.cast(pointer,C.POINTER(C.POINTER(C.c_void_p))).contents
    fn=C.WINFUNCTYPE(result,C.c_void_p,*args)(table[index])
    code=fn(pointer,*values)
    if result is C.c_long and code<0:raise AdmissionError('WINDOWS_AUDIO_SESSION_CALL_FAILED')
    return code


def query(pointer,iid):
    result=C.c_void_p()
    call(pointer,0,C.c_long,[C.POINTER(GUID),C.POINTER(C.c_void_p)],C.byref(GUID(iid)),C.byref(result))
    return result


def release(pointer):
    if pointer:call(pointer,2,W.ULONG,[])


def sessions(pid):
    """Yield live ISimpleAudioVolume pointers only for this exact process ID."""
    native_only()
    ole=C.OleDLL('ole32')
    hr=ole.CoInitializeEx(None,0)
    if hr<0:raise AdmissionError('WINDOWS_AUDIO_COM_THREAD_FAILED')
    pointers=[]
    try:
        enumerator=C.c_void_p()
        ole.CoCreateInstance.argtypes=[C.POINTER(GUID),C.c_void_p,W.DWORD,C.POINTER(GUID),C.POINTER(C.c_void_p)]
        hr=ole.CoCreateInstance(C.byref(GUID('BCDE0395-E52F-467C-8E3D-C4579291692E')),None,23,
            C.byref(GUID('A95664D2-9614-4F35-A746-DE8DB63617E6')),C.byref(enumerator))
        if hr<0:raise AdmissionError('WINDOWS_AUDIO_DEVICE_ENUMERATION_FAILED')
        pointers.append(enumerator)
        device=C.c_void_p();call(enumerator,4,C.c_long,[C.c_int,C.c_int,C.POINTER(C.c_void_p)],0,0,C.byref(device));pointers.append(device)
        manager=C.c_void_p();call(device,3,C.c_long,[C.POINTER(GUID),W.DWORD,C.c_void_p,C.POINTER(C.c_void_p)],
            C.byref(GUID('77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F')),23,None,C.byref(manager));pointers.append(manager)
        collection=C.c_void_p();call(manager,5,C.c_long,[C.POINTER(C.c_void_p)],C.byref(collection));pointers.append(collection)
        count=C.c_int();call(collection,3,C.c_long,[C.POINTER(C.c_int)],C.byref(count))
        for index in range(min(count.value,512)):
            control=C.c_void_p();control2=volume=None
            try:
                call(collection,4,C.c_long,[C.c_int,C.POINTER(C.c_void_p)],index,C.byref(control))
                control2=query(control,'BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D')
                process=W.DWORD();call(control2,14,C.c_long,[C.POINTER(W.DWORD)],C.byref(process))
                if process.value!=pid:continue
                instance=C.c_void_p();call(control2,13,C.c_long,[C.POINTER(C.c_void_p)],C.byref(instance))
                try:identity=C.wstring_at(instance)
                finally:
                    ole.CoTaskMemFree.argtypes=[C.c_void_p];ole.CoTaskMemFree(instance)
                volume=query(control,'87CE5498-68D6-44E5-9215-6DA47EF883D8')
                yield identity,volume
            finally:release(volume);release(control2);release(control)
    finally:
        for pointer in reversed(pointers):release(pointer)
        ole.CoUninitialize()


class ScopedAudioEnvelope:
    def __init__(self,root,native):
        self.native=native;self.original={};self.pid_identity=None
        self.target=1.;self.current=1.;self.expiry=0;self.transition_ms=650
        self.lock=threading.RLock();self.stop=threading.Event();self.last_error=None;self.matched=0
        self.audit=Audit(inside(root,'state/issac-stream/game-audio.jsonl'))
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()

    def update(self,body):
        if set(body)!={'gain','ttl_ms','attack_ms','release_ms'}:raise AdmissionError('FIXED_GAME_AUDIO_ENVELOPE_REQUIRED')
        gain=body['gain']
        if type(gain) not in (int,float) or not 0<=gain<=1 or type(body['ttl_ms']) is not int or not 250<=body['ttl_ms']<=2500:
            raise AdmissionError('BOUNDED_GAME_AUDIO_ENVELOPE_REQUIRED')
        if any(type(body[k]) is not int or not 20<=body[k]<=3000 for k in ('attack_ms','release_ms')):
            raise AdmissionError('BOUNDED_GAME_AUDIO_TRANSITION_REQUIRED')
        self.native.verify_process()
        with self.lock:
            self.transition_ms=body['attack_ms'] if gain<self.current else body['release_ms']
            self.target=float(gain);self.expiry=time.monotonic()+body['ttl_ms']/1000
        return self.status()

    def apply(self,gain):
        process=self.native.process
        if not process:return
        self.native.verify_process()
        identity=(process.pid,process.create_time())
        if self.pid_identity!=identity:
            self.original={};self.pid_identity=identity
        matched=0
        for key,volume in sessions(process.pid):
            self.native.verify_process()
            if key not in self.original:
                value=C.c_float();call(volume,4,C.c_long,[C.POINTER(C.c_float)],C.byref(value));self.original[key]=value.value
            call(volume,3,C.c_long,[C.c_float,C.c_void_p],C.c_float(self.original[key]*gain),None)
            matched+=1
        self.matched=matched

    def run(self):
        previous=time.monotonic()
        while not self.stop.wait(.1):
            now=time.monotonic();dt=now-previous;previous=now
            with self.lock:
                target=self.target if now<self.expiry else 1.
                self.current+=max(-dt/(self.transition_ms/1000),min(dt/(self.transition_ms/1000),target-self.current))
                gain=self.current
            try:
                if self.original or now<self.expiry:self.apply(gain)
                self.last_error=None
            except Exception:self.last_error='VERIFIED_GAME_AUDIO_SESSION_UNAVAILABLE'

    def status(self):
        return {'target_gain':self.target if time.monotonic()<self.expiry else 1,'actual_envelope':self.current,
                'matched_game_sessions':self.matched,'expired':time.monotonic()>=self.expiry,
                'error':self.last_error,'official_capture_audibility_accepted':False}

    def close(self):
        self.stop.set();self.thread.join(5)
        if self.original:
            import psutil
            process=self.native.process
            if not process or not process.is_running():
                self.audit.append('own_audio_session_ended_before_restore')
                return
            try:self.apply(1.)
            except psutil.NoSuchProcess:
                self.audit.append('own_audio_session_ended_before_restore');return
            self.audit.append('own_session_gain_restored',sessions=len(self.original))
