"""The model request must actually carry the complete pinned evidence/tools."""
from pathlib import Path
import unittest
from integration.issac.common import AdmissionError
from integration.issac.model_gateway import strategy_prompt_proof

ROOT=Path(__file__).resolve().parents[1]


class ActualPromptTests(unittest.TestCase):
    def request(self):
        sources=[ROOT/'integration/isaac-agent/dsh-host/isaac-plugin/instructions.md',
                 ROOT/'knowledge/issac-wiki/SKILL.md',ROOT/'knowledge/issac-wiki/references/run-evaluation.md']
        text='攻略查询强制 rep\n'+'\n'.join(p.read_text('utf8') for p in sources)
        names=['isaac_get_state','isaac_get_decision','isaac_lookup','isaac_submit_plan','isaac_wiki_query']
        return {'messages':[{'role':'system','content':text}],
                'tools':[{'type':'function','function':{'name':name}} for name in names]}

    def test_complete_source_and_exact_tools_are_recognized(self):
        proof=strategy_prompt_proof(ROOT,self.request())
        self.assertTrue(proof['complete_sources_seen_in_actual_request'])
        self.assertEqual(len(proof['complete_wiki_sources']),2)

    def test_truncated_skill_is_rejected_even_with_the_same_tool_names(self):
        body=self.request();skill=(ROOT/'knowledge/issac-wiki/SKILL.md').read_text('utf8')
        body['messages'][0]['content']=body['messages'][0]['content'].replace(skill,skill[:500])
        with self.assertRaisesRegex(AdmissionError,'ACTUAL_COMPLETE_WIKI_PROMPT_REQUIRED'):
            strategy_prompt_proof(ROOT,body)

    def test_extra_tool_cannot_expand_the_strategy_privileges(self):
        body=self.request();body['tools'].append({'type':'function','function':{'name':'run_shell'}})
        with self.assertRaisesRegex(AdmissionError,'EXACT_FIVE_STRATEGY_TOOLS_REQUIRED'):
            strategy_prompt_proof(ROOT,body)

    def test_user_message_is_not_a_system_prompt_receipt(self):
        body=self.request();body['messages'][0]['role']='user'
        with self.assertRaisesRegex(AdmissionError,'ACTUAL_COMPLETE_WIKI_PROMPT_REQUIRED'):
            strategy_prompt_proof(ROOT,body)


if __name__=='__main__':unittest.main()
