"""One packet may reuse work; later hazards and contexts must stay live."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from isaac_jev import decision,navigation
from isaac_jev.models import GameState,Vec2
from isaac_jev.observation_cache import observation_memo,observation_scope
from isaac_jev.tuning import PolicyProfile


class ObservationCache(unittest.TestCase):
    def state(self):
        state=GameState.from_message(json.loads((ROOT/'tests/fixtures/stage6-timed-spike-corridor.json').read_text('utf8')))
        return replace(state,layout=replace(state.layout,
            grid_events=tuple(replace(event,active=True) for event in state.layout.grid_events),
            danger_grid_indices=frozenset(event.grid_index for event in state.layout.grid_events)))

    def test_multiple_targets_share_one_bfs_but_not_another_observation(self):
        state=self.state();targets=range(state.layout.grid_width*state.layout.grid_height)
        expected=[navigation.path_distance(state,Vec2(),i) for i in targets]
        with patch.object(navigation,'_route_distances',wraps=navigation._route_distances) as bfs:
            with observation_scope():
                actual=[navigation.path_distance(state,Vec2(),i) for i in targets]
                self.assertEqual(expected,actual);self.assertEqual(bfs.call_count,1)
            with observation_scope():navigation.path_distance(state,Vec2(),73)
            self.assertEqual(bfs.call_count,2)

    def test_same_frame_changed_hazard_and_timed_admission_do_not_share(self):
        state=self.state()
        open_state=replace(state,layout=replace(state.layout,danger_grid_indices=frozenset(),blocked=frozenset()))
        cases=[(state,False),(state,True),(open_state,False)]
        expected=[navigation.path_distance(s,Vec2(),73,allow_timed=timed) for s,timed in cases]
        with observation_scope():
            actual=[navigation.path_distance(s,Vec2(),73,allow_timed=timed) for s,timed in cases]
        self.assertEqual(actual,expected);self.assertNotEqual(expected[0],expected[2])

    def test_candidates_match_uncached_and_profiles_and_replacements_stay_separate(self):
        state=self.state();other=replace(state,coins=state.coins+1)
        profiles=[None,PolicyProfile(),PolicyProfile(enemy_safe_distance=150)]
        cases=[(s,p) for s in (state,other) for p in profiles]
        expected=[decision.build_candidate_set(s,p).as_dict() for s,p in cases]
        with patch.object(decision,'_build_candidate_set',wraps=decision._build_candidate_set) as build:
            with observation_scope():
                for _ in range(2):
                    self.assertEqual([decision.build_candidate_set(s,p).as_dict() for s,p in cases],expected)
            self.assertEqual(build.call_count,len(cases))

    def test_exception_nested_scope_and_other_thread_cannot_leak_entries(self):
        owner=object();calls=[]
        def compute():calls.append(1);return len(calls)
        def get():return observation_memo('test',(owner,),(),compute)
        with observation_scope():
            self.assertEqual(get(),1)
            try:
                with observation_scope():
                    self.assertEqual(get(),2);raise RuntimeError('packet rejected')
            except RuntimeError:pass
            self.assertEqual(get(),1)
            with ThreadPoolExecutor(max_workers=1) as pool:self.assertEqual(pool.submit(get).result(),3)
        self.assertEqual(get(),4)


if __name__=='__main__':unittest.main()
