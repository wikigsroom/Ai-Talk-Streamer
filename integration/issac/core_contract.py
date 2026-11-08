# Pure prompt validation without server dependencies.
from .common import AdmissionError,digest,file_hash,inside,read_json


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

