"""Safety regressions for core authority, actual prompts and scoped source freeze."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from integration.issac.common import AdmissionError,write_json
from integration.issac.delivery import recording_seconds,recording_gate
from integration.issac.core_contract import core_prompt_proof
from scripts.freeze_issac_candidate import preserved_blobs


class DeliveryTests(unittest.TestCase):
    def test_120_requires_the_exact_user_amendment_and_never_authorizes_public_streaming(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            write_json(root/'configs/issac/runtime.json',{'programme':{'required_official_recording_seconds':120}})
            amendment={'amendment_id':'NM-ISSAC-EXECUTION-120S-20261109-v1','branch':'issac',
                       'required_official_recording_seconds':120,'public_broadcast_authorized':False}
            write_json(root/'configs/issac/live120.json',amendment)
            self.assertEqual(recording_seconds(root),120);self.assertEqual(recording_gate(root),'official_recording_120')
            amendment['public_broadcast_authorized']=True
            write_json(root/'configs/issac/live120.json',amendment)
            with self.assertRaises(AdmissionError):recording_seconds(root)


class CorePromptTests(unittest.TestCase):
    def test_only_actual_complete_pinned_skill_and_core_instructions_qualify(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);pieces=[];pins=[]
            for name in ('SKILL.md','references/run-evaluation.md'):
                data=('本地参考 '+name+'\r\n版本 rep\r\n').encode()
                path=root/'knowledge/issac-wiki'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
                sha=hashlib.sha256(data).hexdigest();pins.append({'path':name,'sha256':sha})
                pieces.extend([sha,data.decode().replace('\r\n','\n')])
            write_json(root/'configs/issac/sources.lock.json',{'wiki_skill':{'critical_files':pins}})
            instructions=root/'configs/issac/core-persona-gameplay.md';instructions.write_text('奶妹本人作决定\n','utf8')
            pieces.append(instructions.read_text('utf8'))
            names=['isaac_get_state','isaac_get_decision','isaac_lookup','isaac_submit_plan','isaac_wiki_query']
            body={'tools':[{'function':{'name':name}} for name in names],
                  'messages':[{'role':'system','content':[{'type':'text','text':'\n'.join(pieces)}]}]}
            self.assertEqual(core_prompt_proof(root,body)['actor_id'],'naimei')
            body['messages'][0]['content'][0]['text']='\n'.join(pieces[:1])
            with self.assertRaises(AdmissionError):core_prompt_proof(root,body)


class PreservedSourceTests(unittest.TestCase):
    def test_only_the_exact_unstaged_historical_csv_is_packaged_from_head(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);name='docs/issac/实施任务与验收清单20261107.csv'
            sha='10e9199849894b36f9204e9dacf7e3d7cd1c31ef70a35c6b7087aef8f34adc65'
            write_json(root/'configs/issac/live120.json',{'amendment_id':'NM-ISSAC-EXECUTION-120S-20261109-v1',
                'preserved_unrelated_worktree_changes':[{'path':name,'worktree_sha256':sha,'candidate_content':'HEAD_blob_only'}]})
            def git(*args):return (' M '+name+'\0').encode() if args[0]=='status' else b'committed historical csv\n'
            with patch('scripts.freeze_issac_candidate.file_hash',return_value=sha):
                blobs,receipts=preserved_blobs(root,git)
                self.assertEqual(blobs[name],b'committed historical csv\n')
                self.assertFalse(receipts[0]['worktree_modified_by_freeze'])
                def dirty(*args):return (' M '+name+'\0 M backend/core.mjs\0').encode()
                with self.assertRaises(AdmissionError):preserved_blobs(root,dirty)
            with patch('scripts.freeze_issac_candidate.file_hash',return_value='changed'):
                with self.assertRaises(AdmissionError):preserved_blobs(root,git)


if __name__=='__main__':unittest.main()
