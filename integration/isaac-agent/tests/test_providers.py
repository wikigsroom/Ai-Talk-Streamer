import io
import json
import socket
import tempfile
import unittest
import urllib.error
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from isaac_jev.decision import build_candidate_set
from isaac_jev.models import Entity, GameState, Vec2
from isaac_jev.providers import (
    DecisionProviderConfig,
    JevProvider,
    ProviderConfigError,
    ProviderConfigStore,
    ProviderSettings,
    ProviderQuestion,
    BochaProvider,
    create_provider,
    default_provider_settings,
    parse_provider_config,
)


def make_state():
    return GameState(
        frame=10,
        room_clear=False,
        player=Entity(0, 1, Vec2(), Vec2(), 6),
        enemies=(Entity(1, 10, Vec2(180, 0), Vec2(), 5),),
        projectiles=(),
    )


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.body).encode("utf-8")


class ProviderConfigTests(unittest.TestCase):
    def test_default_project_config_is_created_on_first_load(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config" / "decision_provider.json"
            with patch("isaac_jev.providers.DEFAULT_CONFIG_PATH", path):
                config = ProviderConfigStore(path, environ={}).load()
            self.assertTrue(path.exists())
            self.assertEqual(config.selected_provider, "local")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["selected_provider"], "local")



    def test_config_persists_api_key_as_plaintext(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "decision_provider.json"
            store = ProviderConfigStore(path, environ={})
            config = parse_provider_config({
                "selected_provider": "jev",
                "providers": {"jev": {"api_key": "local-secret", "url": "https://jev.bocha.cn/v1/systemone", "model": "bocha-jev-v1"}},
            }, environ={})
            store.save(config)
            text = path.read_text(encoding="utf-8")
            self.assertIn('"api_key": "local-secret"', text)
            self.assertEqual(store.load().providers["jev"].api_key, "local-secret")
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_official_and_bocha_credentials_are_persisted_independently(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "decision_provider.json"
            store = ProviderConfigStore(path, environ={})
            config = parse_provider_config({
                "providers": {
                    "jev": {
                        "url": "https://api.typesafe.ai/v1/systemone",
                        "model": "jev-latest",
                        "api_key": "official-secret",
                    },
                    "bocha": {
                        "url": "https://jev.bocha.cn/v1/systemone",
                        "model": "bocha-jev-v1",
                        "api_key": "bocha-secret",
                    },
                },
            }, environ={})
            store.save(config)
            loaded = store.load()
            self.assertEqual(loaded.providers["jev"].url, "https://api.typesafe.ai/v1/systemone")
            self.assertEqual(loaded.providers["jev"].api_key, "official-secret")
            self.assertEqual(loaded.providers["bocha"].url, "https://jev.bocha.cn/v1/systemone")
            self.assertEqual(loaded.providers["bocha"].api_key, "bocha-secret")
            text = path.read_text(encoding="utf-8")
            self.assertIn('"api_key": "official-secret"', text)
            self.assertIn('"api_key": "bocha-secret"', text)

    def test_public_config_only_exposes_key_status(self):
        config = parse_provider_config({"providers": {"jev": {"api_key": "private-secret"}}}, environ={})
        public = config.public_dict()
        self.assertTrue(public["providers"]["jev"]["api_key_configured"])
        self.assertNotIn("private-secret", json.dumps(public))
        self.assertNotIn("api_key_b64", json.dumps(config.persisted_dict()))



class ProviderContractTests(unittest.TestCase):
    def setUp(self):
        self.state = make_state()
        self.candidate_set = build_candidate_set(self.state)
        self.action_id = self.candidate_set.admissible_candidates[0].action_id
        self.settings = ProviderSettings(
            url="http://decision.test/v1/decision",
            health_url="http://decision.test/health",
            model="configured-provider",
            timeout_seconds=0.75,
            confidence_threshold=0.5,
        )






    def test_single_admissible_action_skips_remote_provider(self):
        called = []
        candidate_set = replace(self.candidate_set, admissible_candidates=(self.candidate_set.admissible_candidates[0],))
        provider = BochaProvider(self.settings, api_key="private-key", opener=lambda *_args, **_kwargs: called.append(True))
        result = provider.choose(self.state, candidate_set)
        self.assertEqual(result.fallback_reason, "not_remote_eligible")
        self.assertEqual(result.status, "local")
        self.assertFalse(result.fallback)
        self.assertEqual(called, [])


    def test_post_only_endpoint_is_reported_as_reachable(self):
        settings = ProviderSettings("https://jev.test/v1/systemone", "", "jev-test", 0.75, 0.7)
        error = urllib.error.HTTPError(settings.url, 405, "method not allowed", {}, None)
        health = JevProvider(settings, api_key="private-key", opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(error)).health_check()
        self.assertTrue(health.ok)
        self.assertEqual(health.details["health_check"], "endpoint_rejects_get")

    def test_jev_key_only_enters_authorization_header(self):
        captured = {}

        def opener(request, timeout):
            captured["authorization"] = request.get_header("Authorization")
            return FakeResponse({
                "answers": {"next_action": {"choice": self.action_id, "confidence": 0.95}}
            })

        settings = ProviderSettings("https://jev.test/decision", "", "jev-test", 0.75, 0.7)
        result = JevProvider(settings, api_key="private-key", opener=opener).choose(self.state, self.candidate_set)
        self.assertEqual(result.action.source, "jev")
        self.assertEqual(captured["authorization"], "Bearer private-key")
        self.assertNotIn("private-key", repr(result))

    def test_jev_accepts_bocha_question_named_answer(self):
        def opener(request, timeout):
            return FakeResponse({
                "model": "bocha-jev-v1",
                "answers": {"refund": {"choice": self.action_id, "confidence": 0.91}},
                "latency_ms": 31.2,
            })

        settings = ProviderSettings("https://jev.bocha.cn/v1/systemone", "", "bocha-jev-v1", 0.75, 0.7)
        result = JevProvider(settings, api_key="private-key", opener=opener).choose(self.state, self.candidate_set)
        self.assertEqual(result.action.action_id, self.action_id)
        self.assertEqual(result.model, "bocha-jev-v1")
        self.assertEqual(result.server_latency_ms, 31.2)

    def test_bocha_uses_string_state_and_action_question(self):
        captured = {}

        def opener(request, timeout):
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse({
                "model": "bocha-jev-v1",
                "answers": {"action": {"choice": self.action_id, "confidence": 0.91}},
            })

        settings = ProviderSettings("https://jev.bocha.cn/v1/systemone", "", "bocha-jev-v1", 0.75, 0.7)
        result = BochaProvider(settings, api_key="private-key", opener=opener).choose(self.state, self.candidate_set)
        self.assertEqual(result.status, "success")
        self.assertIsInstance(captured["payload"]["state"], str)
        self.assertIn("action", captured["payload"]["questions"])

    def test_bocha_composed_decision_keeps_single_action_question(self):
        captured = {}

        def opener(request, timeout):
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse({
                "model": "bocha-jev-v1",
                "answers": {"action": {"choice": self.action_id, "confidence": 0.91}},
            })

        settings = ProviderSettings("https://jev.bocha.cn/v1/systemone", "", "bocha-jev-v1", 0.75, 0.7)
        result = BochaProvider(settings, api_key="private-key", opener=opener).choose_composed(self.state, self.candidate_set)
        self.assertEqual(result.status, "success")
        self.assertEqual(set(captured["payload"]["questions"]), {"action"})

    def test_jev_without_key_falls_back_without_network_request(self):
        called = []
        settings = ProviderSettings("https://jev.test/decision", "", "jev-test", 0.75, 0.7)
        provider = JevProvider(settings, opener=lambda *_args, **_kwargs: called.append(True))
        result = provider.choose(self.state, self.candidate_set)
        self.assertEqual(result.fallback_reason, "missing_api_key")
        self.assertEqual(result.action.source, "local")
        self.assertEqual(called, [])
        self.assertFalse(provider.health_check().ok)

    def test_factory_uses_plaintext_config_key_and_local_is_healthy(self):
        config = parse_provider_config({"providers": {"jev": {"api_key": "from-config"}}}, environ={})
        jev = create_provider("jev", config, environ={"TYPESAFE_API_KEY": "must-not-be-used"})
        self.assertEqual(jev.api_key, "from-config")
        local = create_provider("local", config)
        self.assertTrue(local.health_check().ok)
        self.assertEqual(local.choose(self.state, self.candidate_set).action.source, "local")

    def test_local_system_one_can_disable_auth_without_environment_key(self):
        config = parse_provider_config({
            "selected_provider": "systemone",
            "providers": {
                "systemone": {
                    "url": "http://127.0.0.1:8001/v1/systemone",
                    "model": "decider-v10",
                    "auth_required": False,
                },
            },
        }, environ={"BOCHA_JEV_API_KEY": "must-not-be-used"})
        captured = {}

        def opener(request, timeout):
            captured["authorization"] = request.get_header("Authorization")
            return FakeResponse({"answers": {"action": {"choice": self.action_id, "confidence": 0.91}}})

        provider = create_provider("systemone", config, environ={"BOCHA_JEV_API_KEY": "must-not-be-used"}, opener=opener)
        result = provider.choose(self.state, self.candidate_set)
        self.assertEqual(provider.model, "decider-v10")
        self.assertEqual(result.provider, "systemone")
        self.assertEqual(result.status, "success")
        self.assertIsNone(captured["authorization"])

    def test_systemone_and_bocha_configs_stay_independent(self):
        config = parse_provider_config({
            "selected_provider": "systemone",
            "providers": {
                "bocha": {"api_key": "bocha-secret"},
                "systemone": {"auth_required": False},
            },
        }, environ={})
        self.assertEqual(config.providers["bocha"].model, "bocha-jev-v1")
        self.assertEqual(config.providers["bocha"].api_key, "bocha-secret")
        self.assertEqual(config.providers["systemone"].model, "decider-v10")
        self.assertEqual(config.providers["systemone"].api_key, "")

    def test_bocha_is_an_independent_configured_provider(self):
        config = parse_provider_config({
            "selected_provider": "bocha",
            "providers": {
                "jev": {"url": "https://api.typesafe.ai/v1/systemone", "model": "jev-latest", "api_key": "official"},
                "bocha": {"url": "https://jev.bocha.cn/v1/systemone", "model": "bocha-jev-v1", "api_key": "bocha-key"},
            },
        }, environ={})
        provider = create_provider("bocha", config, environ={})
        self.assertIsInstance(provider, BochaProvider)
        self.assertEqual(provider.endpoint, "https://jev.bocha.cn/v1/systemone")
        self.assertEqual(provider.model, "bocha-jev-v1")
        self.assertEqual(provider.api_key, "bocha-key")


class MultiQuestionProviderTests(unittest.TestCase):
    def setUp(self):
        self.settings = ProviderSettings("https://jev.test/v1/systemone", "", "jev-test", 0.75, 0.7)
        self.questions = {
            "target": ProviderQuestion("Choose the target.", {"enemy_1": "near", "enemy_2": "far"}),
            "tactic": ProviderQuestion("Choose the tactic.", {"kite": "keep distance", "attack": "deal damage"}),
        }

    def test_two_questions_share_one_request_for_both_jev_providers(self):
        for provider_type in (JevProvider, BochaProvider):
            with self.subTest(provider=provider_type.name):
                calls = []

                def opener(request, timeout):
                    calls.append(request)
                    self.assertEqual(timeout, 0.75)
                    return FakeResponse({"model": "server-model", "latency_ms": 12, "answers": {
                        "tactic": {"choice": "kite", "confidence": 0.9},
                        "target": {"choice": "enemy_2", "probabilities": {"enemy_1": 0.15, "enemy_2": 0.85}},
                    }})

                result = provider_type(self.settings, api_key="secret", opener=opener).choose_questions(
                    {"phase": "combat"}, self.questions,
                )
                self.assertEqual(len(calls), 1)
                payload = json.loads(calls[0].data)
                self.assertEqual(json.loads(payload["state"]), {"phase": "combat"})
                self.assertEqual(set(payload["questions"]), {"target", "tactic"})
                self.assertEqual(payload["questions"]["target"]["type"], "choice")
                self.assertEqual(calls[0].get_header("Authorization"), "Bearer secret")
                self.assertEqual(result.status, "success")
                self.assertEqual(result.model, "server-model")
                self.assertEqual(result.answers["target"].selected_choice, "enemy_2")
                self.assertEqual(result.answers["target"].confidence, 0.85)
                self.assertEqual(result.answers["target"].margin, 0.7)
                self.assertEqual(result.answers["tactic"].selected_choice, "kite")
                self.assertEqual(result.server_latency_ms, 12)
                self.assertGreater(result.request_bytes, 0)
                self.assertNotIn("secret", repr(result))

    def test_missing_question_does_not_borrow_other_question_answer(self):
        provider = JevProvider(self.settings, api_key="key", opener=lambda *args, **kwargs: FakeResponse({
            "answers": {"tactic": {"choice": "kite", "confidence": 0.9}},
        }))
        result = provider.choose_questions({}, self.questions)
        self.assertEqual(result.status, "partial")
        self.assertEqual(result.answers["target"].status, "missing_answer")
        self.assertIsNone(result.answers["target"].selected_choice)
        self.assertEqual(result.answers["tactic"].status, "success")

    def test_invalid_and_low_confidence_answers_are_independent(self):
        provider = BochaProvider(self.settings, api_key="key", opener=lambda *args, **kwargs: FakeResponse({
            "answers": {
                "target": {"choice": "kite", "confidence": 1.0},
                "tactic": {"choice": "attack", "confidence": 0.4},
                "unrequested": {"choice": "enemy_1", "confidence": 1.0},
            },
        }))
        result = provider.choose_questions({}, self.questions)
        self.assertEqual(result.status, "invalid_answers")
        self.assertEqual(result.answers["target"].status, "invalid_choice")
        self.assertEqual(result.answers["tactic"].status, "low_confidence")
        self.assertNotIn("unrequested", result.answers)

    def test_malformed_confidence_never_becomes_success(self):
        for confidence in (True, -0.1, 1.1, float("nan"), float("inf"), "bad", None):
            with self.subTest(confidence=confidence):
                provider = JevProvider(self.settings, api_key="key", opener=lambda *args, **kwargs: FakeResponse({
                    "answers": {"target": {
                        "choice": "enemy_1", "confidence": confidence,
                        "probabilities": {"enemy_1": 0.99, "unknown": 1.0},
                    }},
                }))
                answer = provider.choose_questions({}, self.questions).answers["target"]
                self.assertEqual(answer.status, "invalid_confidence")
                self.assertNotIn("unknown", answer.probabilities)

    def test_missing_confidence_requires_selected_choice_probability(self):
        provider = JevProvider(self.settings, api_key="key", opener=lambda *args, **kwargs: FakeResponse({
            "answers": {"target": {"choice": "enemy_1", "distribution": {"enemy_2": 0.9}}},
        }))
        answer = provider.choose_questions({}, self.questions).answers["target"]
        self.assertEqual(answer.status, "invalid_confidence")

    def test_failure_results_preserve_requested_question_ids(self):
        for response in ([], {}, {"answers": []}):
            with self.subTest(response=response):
                provider = JevProvider(self.settings, api_key="key", opener=lambda *args, **kwargs: FakeResponse(response))
                result = provider.choose_questions({}, self.questions)
                self.assertEqual(result.status, "invalid_response")
                self.assertEqual(set(result.answers), set(self.questions))
        provider = JevProvider(self.settings, api_key="private-key", opener=lambda *args, **kwargs: (
            _ for _ in ()
        ).throw(socket.timeout("private-key delayed")))
        result = provider.choose_questions({}, self.questions)
        self.assertTrue(result.timed_out)
        self.assertEqual(result.status, "timeout")
        self.assertNotIn("private-key", result.error)

    def test_no_key_does_not_send_and_invalid_questions_fail_before_network(self):
        calls = []
        provider = JevProvider(self.settings, opener=lambda *args, **kwargs: calls.append(True))
        self.assertEqual(provider.choose_questions({}, self.questions).status, "missing_api_key")
        for questions in ({}, {"": self.questions["target"]}, {"target": ProviderQuestion("choose", {})}):
            with self.assertRaises(ValueError):
                provider.choose_questions({}, questions)
        self.assertEqual(calls, [])



if __name__ == "__main__":
    unittest.main()
