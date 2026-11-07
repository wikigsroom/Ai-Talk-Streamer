"""Progression checks must distinguish intermediate endings from Satan."""
import sys
import unittest
from unittest.mock import Mock, patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from satan_supervisor import check_progress_guard, ending_disposition, read_with_retry


class SatanSupervisorTests(unittest.TestCase):
    def test_one_observation_timeout_does_not_disable_live_control(self):
        operation=Mock(side_effect=[TimeoutError('temporary'), {'frame':123}])
        with patch('satan_supervisor.time.sleep'), patch('satan_supervisor.autopilot') as control:
            self.assertEqual(read_with_retry(operation), {'frame':123})
            control.assert_not_called()
        self.assertEqual(operation.call_count,2)

    def test_permanent_observation_failure_is_bounded(self):
        operation=Mock(side_effect=TimeoutError('still unavailable'))
        with patch('satan_supervisor.time.sleep'):
            with self.assertRaises(TimeoutError): read_with_retry(operation)
        self.assertEqual(operation.call_count,3)

    def test_a_real_guard_failure_is_never_retried(self):
        operation=Mock(side_effect=RuntimeError('wrong slot'))
        with self.assertRaises(RuntimeError): read_with_retry(operation)
        operation.assert_called_once()

    def progress(self,**updates):
        return dict(slot=3,readonly=False,womb_unlocked=True,mom_heart_kills=0,satan_kills=0,**updates)

    def test_wrong_slot_and_readonly_fail_closed(self):
        for field,value in [('slot',1),('slot',2),('readonly',True),('readonly',None)]:
            progress=self.progress(); progress[field]=value
            with self.assertRaises(RuntimeError): check_progress_guard(progress)

    def test_mom_and_heart_endings_continue_but_cannot_complete_goal(self):
        for stage in (6,8):
            result={'result':'victory','start_seed':123,'stage':stage,'stage_type':0}
            self.assertEqual(ending_disposition(self.progress(),result,{'start_seed':123}),'new_run')

    def test_satan_requires_native_counter_and_correct_floor(self):
        result={'result':'victory','start_seed':123,'stage':10,'stage_type':0}
        with self.assertRaises(RuntimeError): ending_disposition(self.progress(),result,{'start_seed':123})
        progress=self.progress(); progress['satan_kills']=1
        self.assertEqual(ending_disposition(progress,result,{'start_seed':123}),'complete')
        with self.assertRaises(RuntimeError): ending_disposition(progress,dict(result,stage_type=1),{'start_seed':123})

    def test_old_seed_result_cannot_restart_or_complete_current_run(self):
        self.assertEqual(ending_disposition(self.progress(),{'result':'victory','start_seed':122,'stage':6},{'start_seed':123}),'wait')

    def test_stale_raw_and_stale_result_cannot_restart_a_new_live_run(self):
        result={'result':'victory','start_seed':399144564,'stage':6,'stage_type':0}
        raw={'start_seed':399144564}
        self.assertEqual(ending_disposition(self.progress(),result,raw,live_seed=799112684),'wait')
        self.assertEqual(ending_disposition(self.progress(),result,raw,live_seed=399144564),'new_run')


if __name__=='__main__': unittest.main()
