"""Configurable cloud text channel for this local avatar installation."""
import os
import json
import re
import time
from utils.logger import logger

def llm_response(message, avatar_session, datainfo=None):
    from openai import OpenAI
    datainfo = datainfo or {}
    base = os.getenv('AVATAR_LLM_BASE_URL', '').strip()
    key = os.getenv('AVATAR_LLM_API_KEY', '').strip()
    model = os.getenv('AVATAR_LLM_MODEL', '').strip()
    protocol = os.getenv('AVATAR_LLM_PROTOCOL', 'chat_completions').strip()
    if not all((base,key,model)):
        logger.error('Cloud LLM is not configured. Fill configs/channel.env; echo text remains available.')
        return
    if protocol not in ('chat_completions','responses'):
        logger.error('Unsupported AVATAR_LLM_PROTOCOL: %s',protocol)
        return
    client = OpenAI(base_url=base,api_key=key,timeout=60,max_retries=1)
    messages = [{'role':'system','content':os.getenv('AVATAR_SYSTEM_PROMPT','你是一位直播助手，请用简短自然的中文口语回复。')},
                {'role':'user','content':message}]
    started = time.perf_counter()
    pending = ''
    try:
        if protocol == 'responses':
            stream = client.responses.create(model=model,input=messages,stream=True)
            def text_chunks():
                for event in stream:
                    if event.type == 'response.output_text.delta':
                        yield event.delta
                    elif event.type in ('error','response.failed'):
                        raise RuntimeError('LLM response failed; see channel provider diagnostics')
        else:
            stream = client.chat.completions.create(model=model,messages=messages,stream=True)
            def text_chunks():
                for chunk in stream:
                    if chunk.choices:
                        yield chunk.choices[0].delta.content or ''
        first = True
        for text in text_chunks():
            if 'generation' in datainfo and datainfo['generation']!=getattr(avatar_session,'_studio_generation',None):
                break
            if text and first:
                logger.info('Cloud LLM first text %.3fs', time.perf_counter()-started)
                first = False
            pending += text
            while True:
                boundary = re.search(r'[。！？!?；;\n]',pending)
                if boundary is None and len(pending)>80:
                    boundary = re.search(r'[，,：:]',pending)
                if boundary is None:
                    break
                sentence,pending = pending[:boundary.end()].strip(),pending[boundary.end():]
                if sentence:
                    avatar_session.send_msg(json.dumps({'status':'reply','text':sentence}))
                    avatar_session.put_msg_txt(sentence,datainfo)
        if pending.strip() and ('generation' not in datainfo or datainfo['generation']==getattr(avatar_session,'_studio_generation',None)):
            avatar_session.send_msg(json.dumps({'status':'reply','text':pending.strip()}))
            avatar_session.put_msg_txt(pending.strip(),datainfo)
    except Exception as exc:
        avatar_session.send_msg(json.dumps({'status':'error','text':'云端回复失败，请核对渠道地址、模型和密钥。'+(' HTTP '+str(exc.status_code) if getattr(exc,'status_code',None) else '')}))
        logger.exception('Configured cloud LLM request failed')
    finally:
        client.close()
