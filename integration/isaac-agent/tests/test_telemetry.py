import json
import tempfile
import unittest
from pathlib import Path

from isaac_jev.models import Action, Entity, GameState, RoomLayout, Vec2
from isaac_jev.telemetry import EpisodeRecorder


def state(hp, enemies=(), projectiles=(), mode="combat", frame=1, transition="idle"):
    return GameState(
        frame=frame,
        room_clear=False,
        player=Entity(0, 1, Vec2(), Vec2(), hp),
        enemies=tuple(enemies),
        projectiles=tuple(projectiles),
        layout=RoomLayout(room_index=4),
        transition_phase=transition,
    )


class TelemetryTests(unittest.TestCase):
    def test_hp_transition_writes_one_death_event(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "episodes.jsonl"
            recorder = EpisodeRecorder(path)
            recorder.record(state(6), Action("hold_and_fire", Vec2(), Vec2(1, 0), mode="combat"))
            event = recorder.record(state(0, frame=2), Action("hold_and_fire", Vec2(), Vec2(1, 0), mode="combat"))
            self.assertIsNotNone(event)
            recorder.record(state(0, frame=3), Action("hold_and_fire", Vec2(), Vec2(1, 0), mode="combat"))
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 1)
            self.assertEqual(recorder.status()["episodes_recorded"], 1)

    def test_projectile_proximity_is_classified(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = EpisodeRecorder(Path(directory) / "episodes.jsonl")
            recorder.record(state(6, projectiles=(Entity(3, 9, Vec2(20, 0), Vec2(), 0),), frame=1))
            event = recorder.record(state(0, projectiles=(Entity(3, 9, Vec2(20, 0), Vec2(), 0),), frame=2))
            self.assertEqual(event["cause"], "projectile_hit")

    def test_navigation_stall_is_classified_without_nearby_entities(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = EpisodeRecorder(Path(directory) / "episodes.jsonl")
            action = Action("enter_door_2", Vec2(1, 0), Vec2(), mode="navigate")
            for frame in range(1, 15):
                recorder.record(state(6 if frame < 14 else 0, frame=frame, transition="walking_to_door"), action, diagnostics={"repeated_action_count": 20})
            self.assertEqual(recorder.status()["last_death"]["cause"], "navigation_stuck")

    def test_malformed_existing_log_is_tolerated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "episodes.jsonl"
            path.write_text("not json\n{}\n", encoding="utf-8")
            recorder = EpisodeRecorder(path)
            self.assertEqual(recorder.status()["episodes_recorded"], 0)

