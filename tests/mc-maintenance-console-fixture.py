"""Owned real A/B/JVM installation for browser tests; no Minecraft or models."""
from contextlib import closing
from pathlib import Path
import hashlib
import http.client
import json
import os
import queue
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
import test_mc_maintenance_native as native

native.NativeCoordinatorTest.setUpClass()
fixture=native.NativeCoordinatorTest(methodName='runTest')
fixture.setUp()
process=None
try:
    installation=fixture.root/'installation'; installation.mkdir()
    names=['.gitignore','configs/deployment-profiles/mc-native-3080-neoforge-v1.json','configs/deployment-targets.json',
           'configs/deployment-target.json','configs/releases/current.json','configs/layouts/mc-landscape-v1.json',
           'configs/releases/rtx3080-k02-runtime-lock.json','configs/mc-neoforge-client.lock.json', 'configs/mc-neoforge-bridge.lock.json',
           'game-adapters/minecraft/fabric/gradle.properties','scripts/deployment_target.py','scripts/mc_deployment.py',
           'scripts/mc_maintenance.py','scripts/mc_maintenance_core.py','scripts/mc_maintenance_dependencies.py',
           'scripts/mc_maintenance_jobs.py','scripts/mc_maintenance_console.py','web/mc-maintenance.html',
           'web/mc-maintenance.js','web/mc-maintenance.css','web/mc-control.css']
    for name in names:
        target=installation/name; target.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(ROOT/name,target)
    # Optional instrumentation lives only in this owned temporary source clone.
    # It never edits installed production sources or changes the exception path.
    if os.environ.get('MC_MAINTENANCE_TEST_DIAGNOSTIC')=='1':
        target=installation/'scripts/mc_maintenance_console.py'
        text=target.read_text(encoding='utf-8')
        text=text.replace('except Exception as error:\n                    code =',
                          'except Exception as error:\n                    import traceback; traceback.print_exc()\n                    code =')
        target.write_text(text,encoding='utf-8')
        if os.environ.get('MC_MAINTENANCE_TEST_STDIN_NULL')=='1':
            target=installation/'scripts/mc_deployment.py'
            text=target.read_text(encoding='utf-8').replace('timeout=timeout, stderr=subprocess.STDOUT, **flags)',
                   'timeout=timeout, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **flags)')
            target.write_text(text,encoding='utf-8')
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0)); port=probe.getsockname()[1]
    (installation/'configs/mc-maintenance-console.json').write_text(json.dumps({'schema_version':1,'host':'127.0.0.1','port':port}),encoding='utf-8')
    for arguments in [['init','-b','mc'],['add','.'],['-c','user.name=Maintenance browser test','-c','user.email=maintenance@example.invalid',
                      '-c','commit.gpgsign=false','commit','-m','Owned temporary browser fixture']]:
        subprocess.run(['git',*arguments],cwd=installation,capture_output=True,check=True,timeout=15)
    database=installation/'state/female-a-3080-k02/game/game.sqlite3'; database.parent.mkdir(parents=True)
    with closing(sqlite3.connect(fixture.database)) as source,closing(sqlite3.connect(database)) as target:
        source.backup(target)
    (installation/'configs/mc-maintenance.private.json').write_text(json.dumps(fixture.runtime_config),encoding='utf-8')
    ready=queue.Queue()
    with (fixture.root/'console-stderr.log').open('wb') as error_log:
        process=subprocess.Popen([sys.executable,'-X','utf8','-B','scripts/mc_maintenance.py','serve','--journal',str(fixture.journal)],
                                 cwd=installation,stdout=subprocess.PIPE,stderr=error_log)
        def read_ready():
            for line in process.stdout:
                if line.startswith(b'{'):
                    ready.put(json.loads(line)); return
        reader=threading.Thread(target=read_ready,daemon=True); reader.start()
        value=ready.get(timeout=20); reader.join(timeout=1)
        if not value.get('maintenance_console_listening'): raise RuntimeError(json.dumps(value))
        print(json.dumps({'ready':True,'base':'http://127.0.0.1:'+str(port),'console_pid':process.pid,
                          'installation':str(installation),'journal':str(fixture.journal),'real_minecraft':False,'real_inference':False}),flush=True)
        sys.stdin.buffer.readline()
        if process.poll() is None:
            connection=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
            try:
                connection.request('POST','/api/mc-maintenance/stop',body=b'{}',headers={'Content-Type':'application/json'})
                response=connection.getresponse(); response.read()
                assert response.status==202
            except ConnectionError:
                if process.poll() is None: raise
            finally: connection.close()
        process.wait(timeout=45)
        assert process.returncode==0
        with closing(sqlite3.connect(fixture.journal/'mc-control.sqlite3')) as db:
            counts={table:db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in ['tasks','journal_retention_runs','journal_retired_tasks']}
        with closing(sqlite3.connect(database.parent/'maintenance/console/jobs.sqlite3')) as db:
            jobs=[{'request_id':row[0],'action':row[1],'state':row[2],'outcome':row[3],'code':row[4]} for row in db.execute('SELECT request_id,action,state,outcome,code FROM jobs ORDER BY seq')]
        if any(job['state']=='failed' for job in jobs):
            evidence_root=Path(os.environ['MC_MAINTENANCE_BROWSER_PROOF']).parent
            destination=evidence_root/(Path(os.environ['MC_MAINTENANCE_BROWSER_PROOF']).stem+'-failed-fixture')
            if not destination.exists(): shutil.copytree(fixture.root,destination)
        evidence=Path(os.environ['MC_MAINTENANCE_BROWSER_PROOF'])
        evidence.write_text(json.dumps({'actual_public_cli':True,'console_exit_code':process.returncode,'all_owned_services_closed':True,
                            'actual_native_b_counts':counts,'jobs':jobs,'real_minecraft':False,'real_inference':False},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
finally:
    if process is not None:
        if process.poll() is None:
            # Emergency cleanup is restricted to this exact owned child. A forced
            # stop is a test failure, never reported as graceful acceptance.
            process.kill(); process.wait(timeout=10)
        if process.stdout: process.stdout.close()
    fixture.doCleanups()
