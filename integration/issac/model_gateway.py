"""One local model endpoint, with strategy priority and bounded narrator work."""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
import json
from pathlib import Path
import time
import uuid

from aiohttp import ClientSession, ClientTimeout, web

from .common import AdmissionError, Audit, FileLease, digest, file_hash, inside, local_url, read_json


def strategy_prompt_proof(root,body):
    required={'isaac_get_state','isaac_get_decision','isaac_lookup','isaac_submit_plan','isaac_wiki_query'}
    tools=body.get('tools',[])
    if not isinstance(tools,list):raise AdmissionError('EXACT_FIVE_STRATEGY_TOOLS_REQUIRED')
    names=[x['function'].get('name') for x in tools if isinstance(x,dict) and isinstance(x.get('function'),dict)]
    if len(names)!=5 or set(names)!=required:raise AdmissionError('EXACT_FIVE_STRATEGY_TOOLS_REQUIRED')
    sections=[]
    for message in body['messages']:
        if not isinstance(message,dict) or message.get('role') not in {'system','developer'}:continue
        content=message.get('content','')
        if isinstance(content,str):sections.append(content)
        elif isinstance(content,list):sections.extend(p.get('text','') for p in content if isinstance(p,dict) and p.get('type')=='text')
    text='\n'.join(sections).replace('\r\n','\n').replace('\r','\n')
    lock=read_json(inside(root,'configs/issac/sources.lock.json'))
    pins={row['path']:row['sha256'] for row in lock['wiki_skill']['critical_files']}
    sources=[]
    for name in ('SKILL.md','references/run-evaluation.md'):
        path=inside(root,'knowledge/issac-wiki/'+name)
        if file_hash(path)!=pins.get(name) or path.read_text('utf-8') not in text:
            raise AdmissionError('ACTUAL_COMPLETE_WIKI_PROMPT_REQUIRED')
        sources.append({'name':name,'sha256':pins[name]})
    instructions=inside(root,'integration/isaac-agent/dsh-host/isaac-plugin/instructions.md').read_text('utf-8')
    if instructions not in text or '攻略查询强制 rep' not in text:
        raise AdmissionError('ACTUAL_STRATEGY_POLICY_AND_INSTRUCTIONS_REQUIRED')
    return {'actual_system_sections_sha256':digest(sections),'complete_wiki_sources':sources,
            'tools':sorted(required),'complete_sources_seen_in_actual_request':True}


@dataclass(order=True)
class Job:
    priority: int
    order: int
    kind: str = field(compare=False)
    request: object = field(compare=False)
    body: dict = field(compare=False)
    done: object = field(compare=False)
    deadline: float = field(compare=False)
    identity: str = field(default_factory=lambda: uuid.uuid4().hex, compare=False)
    response: object = field(default=None, compare=False)


def core_prompt_proof(root, body):
    """Verify Naimei directly sees the pinned local skill and game tools."""
    lock=read_json(inside(root,'configs/issac/sources.lock.json'))
    pins={row['path']:row['sha256'] for row in lock['wiki_skill']['critical_files']}
    sections=[]
    for message in body.get('messages',[]):
        if not isinstance(message,dict) or message.get('role') not in {'system','developer'}:continue
        content=message.get('content','')
        if isinstance(content,str):sections.append(content)
        elif isinstance(content,list):sections.extend(part.get('text','') for part in content
            if isinstance(part,dict) and part.get('type')=='text' and isinstance(part.get('text'),str))
    normalize=lambda value:value.replace('\r\n','\n').replace('\r','\n')
    system=normalize('\n'.join(sections))
    required={'isaac_get_state','isaac_get_decision','isaac_lookup','isaac_submit_plan','isaac_wiki_query'}
    names={row['function'].get('name') for row in body.get('tools',[])
           if isinstance(row,dict) and isinstance(row.get('function'),dict)}
    if not required<=names:raise AdmissionError('NAIMEI_CORE_GAME_TOOLS_MISSING')
    for relative in ('SKILL.md','references/run-evaluation.md'):
        resource=inside(root,'knowledge/issac-wiki/'+relative)
        if file_hash(resource)!=pins[relative] or pins[relative] not in system:
            raise AdmissionError('NAIMEI_CORE_PINNED_WIKI_MISSING')
        if normalize(resource.read_text(encoding='utf-8-sig')) not in system:
            raise AdmissionError('NAIMEI_CORE_WIKI_CONTENT_MISSING')
    instructions=inside(root,'configs/issac/core-persona-gameplay.md').read_text(encoding='utf-8')
    if normalize(instructions) not in system:raise AdmissionError('NAIMEI_CORE_GAMEPLAY_PROMPT_MISSING')
    return {'actor_id':'naimei','strategic_owner':'naimei_core_dsh','prompt_sha256':digest(system),
            'requested_edition':'rep','tools':sorted(names),'direct_skill_and_game_tools':True}


class ModelGateway:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.config = read_json(inside(self.root, 'private/issac/model.json'))
        self.endpoint = local_url(self.config['base_url'])
        if not isinstance(self.config.get('model'), str) or not self.config['model'].strip():
            raise AdmissionError('ACTUAL_LOCAL_MODEL_ID_REQUIRED')
        self.queue = asyncio.PriorityQueue(maxsize=12)
        self.counter = 0
        self.active = None
        self.execution = None
        self.http = None
        self.worker = None
        self.lease = None
        self.closing = False
        self.audit = Audit(inside(self.root, 'state/issac-stream/local-model-events.jsonl'))
        self.stats = {'completed':0,'failed':0,'expired':0,'preempted':0,'strategy':0,'narrator':0,'core':0}
        from .local_model import LocalModel
        self.backend_owner=LocalModel(root)

    async def completion(self, request):
        kind = request.match_info['kind']
        if kind not in {'strategy','narrator','core'}:
            raise web.HTTPNotFound()
        try:
            body = await request.json()
            if (not isinstance(body,dict) or body.get('model')!=self.config['model']
                    or not isinstance(body.get('messages'),list) or len(body['messages'])>64
                    or any(key in body for key in ('base_url','url','api_key','callback','webhook'))):
                raise AdmissionError('INVALID_LOCAL_MODEL_REQUEST')
            bound=1600 if kind=='strategy' else 768 if kind=='core' else 240
            requested=body.get('max_tokens', body.get('max_completion_tokens', bound))
            if type(requested) is not int or requested<=0:
                raise AdmissionError('INVALID_LOCAL_MODEL_TOKEN_LIMIT')
            body.pop('max_completion_tokens',None)
            body['max_tokens']=min(bound,requested)
            if kind=='strategy':
                proof=strategy_prompt_proof(self.root,body)
                self.audit.append('actual_complete_strategy_request',**proof)
            elif kind=='core':
                proof=core_prompt_proof(self.root,body)
                self.audit.append('actual_naimei_core_request',**proof)
        except (ValueError,TypeError) as error:
            self.audit.append('request_rejected',request_class=kind,
                              code=str(error) if isinstance(error,AdmissionError) else 'INVALID_LOCAL_MODEL_REQUEST')
            return web.json_response({'error':{'code':'INVALID_LOCAL_MODEL_REQUEST'}},status=400)
        if self.queue.full():
            return web.json_response({'error':{'code':'LOCAL_MODEL_QUEUE_FULL'}},status=429)
        self.counter+=1
        loop=asyncio.get_running_loop()
        job=Job(0 if kind in {'strategy','core'} else 10,self.counter,kind,request,body,loop.create_future(),
                loop.time()+(43 if kind=='strategy' else 18))
        self.queue.put_nowait(job)
        self.stats[kind]+=1
        self.audit.append('queued',request_id=job.identity,request_class=kind,queue_depth=self.queue.qsize())
        # A waiting strategy cancels low-priority text generation. The connection
        # is aborted, rather than returning a clean partial sentence as success.
        if kind in {'strategy','core'} and self.active and self.active.kind=='narrator' and self.execution:
            self.stats['preempted']+=1
            self.audit.append('narrator_preempted',request_id=self.active.identity,by=job.identity)
            self.execution.cancel()
        try:
            return await asyncio.wait_for(asyncio.shield(job.done),timeout=max(.1,job.deadline-loop.time()))
        except asyncio.TimeoutError:
            self.stats['expired']+=1
            job.done.cancel()
            if self.active is job and self.execution:
                self.execution.cancel()
            raise web.HTTPGatewayTimeout(text='LOCAL_MODEL_DEADLINE_EXCEEDED') from None
        except asyncio.CancelledError:
            job.done.cancel()
            if self.active is job and self.execution:
                self.execution.cancel()
            raise

    async def execute(self, job):
        start=time.monotonic()
        await asyncio.to_thread(self.backend_owner.verify_server_owner)
        remaining=job.deadline-asyncio.get_running_loop().time()
        if remaining<=0 or job.done.cancelled():
            raise asyncio.TimeoutError()
        if job.request.transport is None or job.request.transport.is_closing():
            raise ConnectionError('downstream closed')
        headers={'Content-Type':'application/json'}
        if self.config.get('api_key'):
            headers['Authorization']='Bearer '+self.config['api_key']
        # The configured endpoint is numeric IPv4 loopback. Redirects and
        # environment proxies are never followed, including for model discovery.
        async with self.http.post(self.endpoint+'/chat/completions',json=job.body,headers=headers,
                                  timeout=ClientTimeout(total=remaining),allow_redirects=False) as upstream:
            if upstream.status!=200:
                raise AdmissionError('LOCAL_MODEL_UPSTREAM_FAILED')
            content_type=upstream.headers.get('Content-Type','')
            if job.body.get('stream'):
                if 'text/event-stream' not in content_type:
                    raise AdmissionError('LOCAL_MODEL_STREAM_PROTOCOL_MISMATCH')
                response=web.StreamResponse(headers={'Content-Type':'text/event-stream','Cache-Control':'no-store'})
                job.response=response
                await response.prepare(job.request)
                count=0
                finished=False
                pending=b''
                async for data in upstream.content.iter_any():
                    count+=len(data)
                    if count>8*1024*1024:
                        raise AdmissionError('LOCAL_MODEL_OUTPUT_TOO_LARGE')
                    pending+=data
                    while b'\n' in pending:
                        line,pending=pending.split(b'\n',1)
                        if line.startswith(b'data:'):
                            value=line[5:].strip()
                            if value and value!=b'[DONE]':
                                event=json.loads(value)
                                if event.get('error'):
                                    raise AdmissionError('LOCAL_MODEL_STREAM_ERROR')
                                for choice in event.get('choices',[]):
                                    if choice.get('finish_reason') in {'stop','tool_calls'}:
                                        finished=True
                    await response.write(data)
                if not finished:
                    raise AdmissionError('LOCAL_MODEL_INCOMPLETE_GENERATION')
                await response.write_eof()
                result=response
            else:
                data=await upstream.content.read(4*1024*1024+1)
                if len(data)>4*1024*1024:
                    raise AdmissionError('LOCAL_MODEL_OUTPUT_TOO_LARGE')
                value=json.loads(data)
                if not value.get('choices') or any(x.get('finish_reason') not in {'stop','tool_calls'} for x in value['choices']):
                    raise AdmissionError('LOCAL_MODEL_INCOMPLETE_GENERATION')
                result=web.json_response(value)
        self.audit.append('completed',request_id=job.identity,request_class=job.kind,
                          elapsed_ms=round((time.monotonic()-start)*1000,2),model=self.config['model'])
        return result

    async def work(self):
        while True:
            job=await self.queue.get()
            if job.done.cancelled():
                self.queue.task_done()
                continue
            self.active=job
            self.execution=asyncio.create_task(self.execute(job))
            try:
                result=await self.execution
                self.stats['completed']+=1
                if not job.done.done():
                    job.done.set_result(result)
            except (Exception,asyncio.CancelledError) as error:
                self.stats['failed']+=1
                self.audit.append('failed',request_id=job.identity,request_class=job.kind,error_code=type(error).__name__)
                if job.response is not None and job.request.transport is not None:
                    job.request.transport.abort()
                if not job.done.done():
                    job.done.set_result(web.json_response({'error':{'code':'LOCAL_MODEL_REQUEST_CANCELLED_OR_FAILED'}},status=503))
            finally:
                self.active=None
                self.execution=None
                self.queue.task_done()
            if self.closing:
                return

    async def models(self, _request):
        return web.json_response({'object':'list','data':[{'id':self.config['model'],'object':'model','owned_by':'local'}]})

    async def health(self, _request):
        return web.json_response({'ready':self.http is not None,'model':self.config['model'],
            'endpoint_kind':'numeric_ipv4_loopback','cloud_fallback':False,
            'active':self.active.kind if self.active else None,'queued':self.queue.qsize(),**self.stats})

    async def start(self, _app):
        self.lease=FileLease(inside(self.root,'state/issac-stream/model-gateway.lock')).acquire()
        self.http=ClientSession(trust_env=False)
        self.worker=asyncio.create_task(self.work())

    async def close(self, _app):
        self.closing=True
        if self.execution:
            self.execution.cancel()
        if self.worker:
            self.worker.cancel()
            await asyncio.gather(self.worker,return_exceptions=True)
        while not self.queue.empty():
            job=self.queue.get_nowait()
            if not job.done.done():
                job.done.set_result(web.json_response({'error':{'code':'LOCAL_GATEWAY_STOPPED'}},status=503))
            self.queue.task_done()
        if self.http:
            await self.http.close()
        if self.lease:
            self.lease.close()

    def application(self):
        app=web.Application(client_max_size=512*1024)
        app.router.add_post('/{kind}/v1/chat/completions',self.completion)
        app.router.add_get('/{kind}/v1/models',self.models)
        app.router.add_get('/health',self.health)
        app.on_startup.append(self.start)
        app.on_cleanup.append(self.close)
        from .shutdown import aiohttp_shutdown
        aiohttp_shutdown(app,self.root)
        return app


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,required=True)
    args=parser.parse_args()
    from .shutdown import run_web
    run_web(ModelGateway(args.root).application(),args.root,host='127.0.0.1',port=1235)


if __name__=='__main__':
    main()
