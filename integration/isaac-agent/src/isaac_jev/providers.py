from __future__ import annotations

import json
import math
import os
import socket
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping, Protocol
from urllib.parse import urlparse

from .decision import (
    CandidateSet,
    SCHEMA_VERSION,
    build_candidate_set,
    build_policy_observation,
    local_policy_action,
    policy_router,
    _safety_filter,
)
from .models import Action, GameState, Vec2
from .tuning import PolicyProfile


PROVIDER_NAMES = frozenset({"jev", "bocha", "systemone", "local"})
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "decision_provider.json"
LEGACY_CONFIG_PATH = PROJECT_ROOT / "logs" / "decision_provider.json"


@dataclass(frozen=True)
class ProviderSettings:
    url: str = ""
    health_url: str = ""
    model: str = ""
    timeout_seconds: float = 0.75
    confidence_threshold: float = 0.0
    api_key: str = ""
    # ``None`` keeps direct constructor compatibility; persisted configs use
    # an explicit value so local System One endpoints can disable auth.
    auth_required: bool | None = None


def default_provider_settings(environ: Mapping[str, str] | None = None) -> dict[str, ProviderSettings]:
    environment = os.environ if environ is None else environ
    return {
        "jev": ProviderSettings(
            url=environment.get("JEV_API_URL", "https://api.typesafe.ai/v1/systemone"),
            model=environment.get("JEV_MODEL", "jev-latest"),
            timeout_seconds=0.75,
            confidence_threshold=0.70,
            auth_required=True,
        ),
        "bocha": ProviderSettings(
            url="https://jev.bocha.cn/v1/systemone",
            model="bocha-jev-v1",
            timeout_seconds=0.75,
            confidence_threshold=0.70,
            auth_required=True,
        ),
        "systemone": ProviderSettings(
            url="http://127.0.0.1:8001/v1/systemone",
            model="decider-v10",
            timeout_seconds=0.75,
            confidence_threshold=0.70,
            auth_required=False,
        ),
        "local": ProviderSettings(model="local-policy", timeout_seconds=0.75, confidence_threshold=0.0, auth_required=False),
    }


@dataclass(frozen=True)
class DecisionProviderConfig:
    version: int = 1
    selected_provider: str = "local"
    shadow_enabled: bool = False
    shadow_provider: str = "jev"
    providers: dict[str, ProviderSettings] = field(default_factory=default_provider_settings)

    def public_dict(self) -> dict[str, Any]:
        return self._dict(include_secrets=False)

    def _dict(self, include_secrets: bool) -> dict[str, Any]:
        provider_values: dict[str, dict[str, Any]] = {}
        for name, settings in self.providers.items():
            if name not in PROVIDER_NAMES:
                continue
            values = {
                key: value
                for key, value in asdict(settings).items()
                if value not in (None, "") and key != "api_key" and not (name == "local" and key in {"url", "health_url"})
            }
            if include_secrets:
                if settings.api_key:
                    values["api_key"] = settings.api_key
            else:
                values["api_key_configured"] = bool(settings.api_key)
            provider_values[name] = values
        return {
            "version": self.version,
            "selected_provider": self.selected_provider,
            "shadow_enabled": self.shadow_enabled,
            "shadow_provider": self.shadow_provider,
            "providers": provider_values,
        }

    def persisted_dict(self) -> dict[str, Any]:
        return self._dict(include_secrets=True)


class ProviderConfigError(ValueError):
    pass


class ProviderConfigStore:
    def __init__(self, path: str | Path = DEFAULT_CONFIG_PATH, environ: Mapping[str, str] | None = None) -> None:
        self.path = Path(path)
        self.environ = os.environ if environ is None else environ

    def load(self) -> DecisionProviderConfig:
        if not self.path.exists():
            legacy = LEGACY_CONFIG_PATH
            if self.path == DEFAULT_CONFIG_PATH and legacy.exists():
                try:
                    raw = json.loads(legacy.read_text(encoding="utf-8"))
                    config = parse_provider_config(raw, self.environ)
                    self.save(config)
                    return config
                except (OSError, UnicodeError, json.JSONDecodeError, ProviderConfigError):
                    pass
            config = DecisionProviderConfig(providers=default_provider_settings(self.environ))
            # The real project config is local-only and ignored by Git. Create
            # it on first startup so users can see and edit the active defaults.
            if self.path == DEFAULT_CONFIG_PATH:
                try:
                    self.save(config)
                except OSError:
                    # Read-only installations can still run with in-memory defaults.
                    pass
            return config
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ProviderConfigError(f"cannot load provider config: {error}") from error
        return parse_provider_config(raw, self.environ)

    def save(self, config: DecisionProviderConfig) -> None:
        validated = parse_provider_config(config.persisted_dict(), self.environ)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(validated.persisted_dict(), ensure_ascii=False, indent=2) + "\n"
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp", delete=False
            ) as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
                temp_path = Path(handle.name)
            os.replace(temp_path, self.path)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()


def parse_provider_config(raw: Any, environ: Mapping[str, str] | None = None) -> DecisionProviderConfig:
    if not isinstance(raw, Mapping):
        raise ProviderConfigError("provider config must be a JSON object")
    defaults = default_provider_settings(environ)
    selected = _provider_name(raw.get("selected_provider", "local"), "selected_provider")
    shadow = _provider_name(raw.get("shadow_provider", "jev"), "shadow_provider")
    shadow_enabled = raw.get("shadow_enabled", False)
    if not isinstance(shadow_enabled, bool):
        raise ProviderConfigError("shadow_enabled must be a boolean")
    if shadow_enabled and shadow == selected:
        raise ProviderConfigError("shadow_provider must differ from selected_provider")
    version = raw.get("version", 1)
    if not isinstance(version, int) or isinstance(version, bool) or version != 1:
        raise ProviderConfigError("unsupported provider config version")
    raw_providers = raw.get("providers", {})
    if not isinstance(raw_providers, Mapping):
        raise ProviderConfigError("providers must be a JSON object")
    providers: dict[str, ProviderSettings] = {}
    for name in PROVIDER_NAMES:
        value = raw_providers.get(name, {})
        if not isinstance(value, Mapping):
            raise ProviderConfigError(f"providers.{name} must be a JSON object")
        providers[name] = _parse_settings(name, value, defaults[name])
    return DecisionProviderConfig(version, selected, shadow_enabled, shadow, providers)


def _provider_name(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or value not in PROVIDER_NAMES:
        raise ProviderConfigError(f"{field_name} must be one of: jev, bocha, systemone, local")
    return value


def _parse_settings(name: str, raw: Mapping[str, Any], default: ProviderSettings) -> ProviderSettings:
    # Explicitly select persisted fields so credentials and arbitrary request headers can never reach disk.
    url = _url(raw.get("url", default.url), f"providers.{name}.url", required=name != "local")
    health_url = _url(raw.get("health_url", default.health_url), f"providers.{name}.health_url", required=False)
    model = raw.get("model", default.model)
    if not isinstance(model, str) or not model.strip() or len(model) > 200:
        raise ProviderConfigError(f"providers.{name}.model must be a non-empty string")
    timeout = _finite_number(raw.get("timeout_seconds", default.timeout_seconds), f"providers.{name}.timeout_seconds")
    threshold = _finite_number(raw.get("confidence_threshold", default.confidence_threshold), f"providers.{name}.confidence_threshold")
    if not 0.05 <= timeout <= 30.0:
        raise ProviderConfigError(f"providers.{name}.timeout_seconds must be between 0.05 and 30")
    if not 0.0 <= threshold <= 1.0:
        raise ProviderConfigError(f"providers.{name}.confidence_threshold must be between 0 and 1")
    auth_required = raw.get("auth_required", default.auth_required)
    if auth_required is not None and not isinstance(auth_required, bool):
        raise ProviderConfigError(f"providers.{name}.auth_required must be a boolean")
    # Plaintext project configuration is intentional. Keep accepting the old
    # api_key_b64 field once so existing installations can be migrated by the
    # next save, but never write that format again.
    api_key = raw.get("api_key", default.api_key)
    if raw.get("api_key_b64") not in (None, "") and raw.get("api_key") in (None, ""):
        encoded_key = raw.get("api_key_b64")
        if not isinstance(encoded_key, str):
            raise ProviderConfigError(f"providers.{name}.api_key_b64 must be a string")
        try:
            import base64
            api_key = base64.b64decode(encoded_key.encode("ascii"), validate=True).decode("utf-8")
        except (ValueError, UnicodeError) as error:
            raise ProviderConfigError(f"providers.{name}.api_key_b64 is invalid") from error
    if not isinstance(api_key, str) or len(api_key) > 4096:
        raise ProviderConfigError(f"providers.{name}.api_key must be a string")
    return ProviderSettings(url, health_url, model.strip(), timeout, threshold, api_key.strip(), auth_required)


def _url(value: Any, field_name: str, required: bool) -> str:
    if value in (None, "") and not required:
        return ""
    if not isinstance(value, str) or len(value) > 2048:
        raise ProviderConfigError(f"{field_name} must be an HTTP(S) URL")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ProviderConfigError(f"{field_name} must be an HTTP(S) URL without credentials")
    return value


def _finite_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool):
        raise ProviderConfigError(f"{field_name} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ProviderConfigError(f"{field_name} must be numeric") from error
    if not math.isfinite(number):
        raise ProviderConfigError(f"{field_name} must be finite")
    return number


@dataclass(frozen=True)
class ProviderHealth:
    provider: str
    ok: bool
    endpoint: str
    model: str
    latency_ms: float
    error: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderQuestion:
    """One independent, finite Choice question in a System One request."""

    instructions: str
    criteria: Mapping[str, str]

    def payload(self) -> dict[str, Any]:
        if not isinstance(self.instructions, str) or not self.instructions.strip():
            raise ValueError("question instructions must be non-empty")
        if not self.criteria or any(
            not isinstance(key, str) or not key or not isinstance(value, str)
            for key, value in self.criteria.items()
        ):
            raise ValueError("question criteria must map non-empty choice IDs to descriptions")
        return {"type": "choice", "instructions": self.instructions, "criteria": dict(self.criteria)}


@dataclass(frozen=True)
class ProviderAnswer:
    question_id: str
    selected_choice: str | None = None
    probabilities: dict[str, float] = field(default_factory=dict)
    confidence: float = 0.0
    top1_probability: float = 0.0
    top2_probability: float = 0.0
    margin: float = 0.0
    entropy: float = 0.0
    status: str = "missing_answer"


@dataclass(frozen=True)
class ProviderQuestionBatch:
    provider: str
    model: str
    answers: dict[str, ProviderAnswer]
    status: str
    client_latency_ms: float = 0.0
    server_latency_ms: float | None = None
    request_bytes: int = 0
    estimated_input_tokens: int = 0
    timed_out: bool = False
    error: str = ""


@dataclass(frozen=True)
class ProviderDecision:
    provider: str
    model: str
    action: Action
    selected_choice: str | None
    probabilities: dict[str, float]
    confidence: float
    top1_probability: float
    top2_probability: float
    margin: float
    entropy: float
    client_latency_ms: float
    server_latency_ms: float | None
    status: str
    fallback: bool = False
    fallback_reason: str = ""
    timed_out: bool = False
    error: str = ""
    request_bytes: int = 0
    estimated_input_tokens: int = 0
    policy: str = "local"
    schema_version: str = SCHEMA_VERSION
    judgments: dict[str, dict[str, Any]] = field(default_factory=dict)


class DecisionProvider(Protocol):
    name: str
    model: str
    endpoint: str

    def choose(self, state: GameState, candidate_set: CandidateSet | None = None) -> ProviderDecision: ...

    def health_check(self) -> ProviderHealth: ...


class LocalProvider:
    name = "local"
    endpoint = ""

    def __init__(self, settings: ProviderSettings | None = None, profile: PolicyProfile | None = None) -> None:
        self.settings = settings or default_provider_settings()["local"]
        self.model = self.settings.model
        self.profile = (profile or PolicyProfile()).bounded()

    def choose(self, state: GameState, candidate_set: CandidateSet | None = None) -> ProviderDecision:
        candidate_set = candidate_set or build_candidate_set(state, self.profile)
        action = local_policy_action(state, candidate_set, self.profile)
        return ProviderDecision(
            provider=self.name, model=self.model, action=action, selected_choice=action.action_id,
            probabilities={action.action_id: 1.0}, confidence=1.0, top1_probability=1.0,
            top2_probability=0.0, margin=1.0, entropy=0.0, client_latency_ms=0.0,
            server_latency_ms=None, status="success", policy=policy_router(state, candidate_set),
        )

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(self.name, True, "", self.model, 0.0, details={"mode": "in_process"})


class RemoteDecisionProvider:
    name = "remote"
    requires_api_key = False

    def __init__(
        self,
        settings: ProviderSettings,
        api_key: str = "",
        profile: PolicyProfile | None = None,
        opener: Any = None,
    ) -> None:
        self.settings = settings
        self.endpoint = settings.url
        self.model = settings.model
        self.api_key = api_key
        self.profile = (profile or PolicyProfile()).bounded()
        if settings.auth_required is not None:
            self.requires_api_key = settings.auth_required
        self._opener = opener or urllib.request.urlopen

    def choose(self, state: GameState, candidate_set: CandidateSet | None = None) -> ProviderDecision:
        candidate_set = candidate_set or build_candidate_set(state, self.profile)
        candidates = list(candidate_set.admissible_candidates)
        route = policy_router(state, candidate_set)
        fallback_action = local_policy_action(state, candidate_set, self.profile)
        if route not in {"combat", "loot", "navigation"} or len(candidates) < 2:
            return self._fallback(fallback_action, route, "not_remote_eligible", status="local", fallback=False)
        if self.requires_api_key and not self.api_key:
            return self._fallback(fallback_action, route, "missing_api_key", error=f"{self.name} API key is not configured")
        observation = build_policy_observation(state, candidate_set)
        instructions = {
            "combat": "Choose one admissible combat action that best balances survival and damage.",
            "loot": "Choose one admissible reward action; prefer the best value for the current resources.",
            "navigation": "Choose one admissible navigation action and follow the planner's intended exit.",
        }.get(route, "Choose exactly one admissible action for the current phase.")
        if state.recovery_active:
            instructions = "Choose one genuinely safe short recovery waypoint that can free Isaac from the stalled doorway. Do not choose a closed or locked door."
        payload = self._request_payload(observation, instructions, candidates)
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(self.endpoint, data=data, headers=headers, method="POST")
        started = time.monotonic()
        try:
            with self._opener(request, timeout=self.settings.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except Exception as error:
            latency = (time.monotonic() - started) * 1000.0
            timed_out = _is_timeout(error)
            reason = _remote_error_reason(error)
            return self._fallback(
                fallback_action, route, reason, latency=latency, timed_out=timed_out,
                error=_safe_error(error, self.api_key), request_bytes=len(data),
            )
        latency = (time.monotonic() - started) * 1000.0
        if not isinstance(body, Mapping):
            return self._fallback(fallback_action, route, "response_not_an_object", latency=latency, request_bytes=len(data))
        answers = body.get("answers", {}) if isinstance(body.get("answers"), Mapping) else {}
        # TypeSafe uses the fixed ``next_action`` key in this project, while
        # Bocha's example names the answer after the question (for example
        # ``refund``). Prefer the project key, then accept a single answer so
        # both Jev-compatible response shapes share the same contract.
        answer = answers.get("next_action", {})
        if not answer and len(answers) == 1:
            answer = next(iter(answers.values()))
        if not isinstance(answer, Mapping):
            answer = {}
        choice = answer.get("choice") or answer.get("value") or answer.get("answer")
        confidence = _response_number(answer.get("confidence"), 0.0)
        probabilities = _probabilities(answer.get("probabilities", answer.get("distribution", {})))
        top1, top2, margin, entropy = _distribution_metrics(probabilities)
        server_latency = _optional_response_number(body.get("latency_ms"))
        selected = next((item for item in candidates if item.action_id == choice), None)
        if selected is None:
            return self._fallback(
                fallback_action, route, "invalid_choice", choice=str(choice) if choice is not None else None,
                probabilities=probabilities, confidence=confidence, latency=latency, server_latency=server_latency,
                request_bytes=len(data),
            )
        if confidence < self.settings.confidence_threshold:
            return self._fallback(
                fallback_action, route, "low_confidence", choice=str(choice), probabilities=probabilities,
                confidence=confidence, latency=latency, server_latency=server_latency, request_bytes=len(data),
            )
        selected_action = replace(selected, confidence=confidence, source=self.name)
        action = _safety_filter(state, selected_action, self.profile)
        return ProviderDecision(
            provider=self.name, model=str(body.get("model") or self.model), action=action,
            selected_choice=str(choice), probabilities=probabilities, confidence=confidence,
            top1_probability=top1, top2_probability=top2, margin=margin, entropy=entropy,
            client_latency_ms=round(latency, 2), server_latency_ms=server_latency,
            status="success" if action.action_id == selected_action.action_id else "safety_filtered",
            request_bytes=len(data), estimated_input_tokens=max(1, (len(data) + 3) // 4), policy=route,
        )

    def _fallback(
        self,
        action: Action,
        policy: str,
        reason: str,
        *,
        status: str = "fallback",
        choice: str | None = None,
        probabilities: dict[str, float] | None = None,
        confidence: float = 0.0,
        latency: float = 0.0,
        server_latency: float | None = None,
        timed_out: bool = False,
        error: str = "",
        request_bytes: int = 0,
        fallback: bool = True,
    ) -> ProviderDecision:
        probabilities = probabilities or {}
        top1, top2, margin, entropy = _distribution_metrics(probabilities)
        return ProviderDecision(
            provider=self.name, model=self.model, action=replace(action, source="local"),
            selected_choice=choice, probabilities=probabilities, confidence=confidence,
            top1_probability=top1, top2_probability=top2, margin=margin, entropy=entropy,
            client_latency_ms=round(latency, 2), server_latency_ms=server_latency, status=status,
            fallback=fallback, fallback_reason=reason, timed_out=timed_out, error=error,
            request_bytes=request_bytes, estimated_input_tokens=max(1, (request_bytes + 3) // 4) if request_bytes else 0,
            policy=policy,
        )

    def _request_payload(self, observation: Mapping[str, Any], instructions: str, candidates: list[Any]) -> dict[str, Any]:
        return {
            "model": self.model,
            "state": observation,
            "questions": {
                "next_action": {
                    "type": "choice",
                    "instructions": instructions,
                    "criteria": {item.action_id: item.reason for item in candidates},
                }
            },
        }

    def health_check(self) -> ProviderHealth:
        url = self.settings.health_url or self.endpoint
        if self.requires_api_key and not self.api_key:
            return ProviderHealth(self.name, False, url, self.model, 0.0, error=f"{self.name} API key is not configured")
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(url, headers=headers, method="GET")
        started = time.monotonic()
        try:
            with self._opener(request, timeout=self.settings.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
                try:
                    body = json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    body = {"response": raw[:500]}
            details = body if isinstance(body, dict) else {"response": body}
            return ProviderHealth(
                self.name, True, url, str(details.get("model") or self.model),
                round((time.monotonic() - started) * 1000.0, 2), details=_public_health_details(details),
            )
        except Exception as error:
            if isinstance(error, urllib.error.HTTPError) and error.code in {405, 501}:
                return ProviderHealth(
                    self.name, True, url, self.model,
                    round((time.monotonic() - started) * 1000.0, 2),
                    details={"reachable": True, "health_check": "endpoint_rejects_get", "http_status": error.code},
                )
            return ProviderHealth(
                self.name, False, url, self.model, round((time.monotonic() - started) * 1000.0, 2),
                error=_safe_error(error, self.api_key),
            )


class JevProvider(RemoteDecisionProvider):
    name = "jev"
    requires_api_key = True

    def choose_composed(self, state: GameState, candidate_set: CandidateSet | None = None) -> ProviderDecision:
        """Compose small System One judgments within the local legal action set."""
        candidate_set = candidate_set or build_candidate_set(state, self.profile)
        candidates = list(candidate_set.admissible_candidates)
        route = policy_router(state, candidate_set)
        fallback_action = local_policy_action(state, candidate_set, self.profile)
        if route not in {"combat", "loot", "navigation"} or len(candidates) < 2:
            return self._fallback(fallback_action, route, "not_remote_eligible", status="local", fallback=False)

        questions = {
            "action": ProviderQuestion(
                ("Choose the safest distinct waypoint to escape the confirmed navigation stall."
                 if state.recovery_active else "Choose the best legal next action for survival and progress."),
                {item.action_id: item.reason for item in candidates},
            ),
        }
        if route == "combat":
            # Bocha's public System One contract accepts one `action` Choice
            # reliably; keep the multi-primitive composition for the official
            # Jev endpoint until Bocha exposes the same multi-answer schema.
            if self.name not in {"bocha", "systemone"}:
                questions["dodge"] = ProviderQuestion(
                    "Should Isaac dodge now based on nearby enemies and projectiles?",
                    {"yes": "Prioritize an evasive movement", "no": "Keep the chosen movement"},
                )
                if any(item.shoot != Vec2() for item in candidates):
                    questions["trigger"] = ProviderQuestion(
                        "Should the attack trigger be held right now?",
                        {"hold": "Fire at the current target", "release": "Do not fire this moment"},
                    )

        batch = self.choose_questions(build_policy_observation(state, candidate_set), questions)
        judgments = {
            key: {"choice": answer.selected_choice, "status": answer.status, "confidence": answer.confidence}
            for key, answer in batch.answers.items()
        }
        action_answer = batch.answers["action"]
        selected = next((item for item in candidates if item.action_id == action_answer.selected_choice), None)
        if action_answer.status != "success" or selected is None:
            reason = f"action:{action_answer.status}" if batch.status in {"success", "partial", "invalid_answers"} else batch.status
            return replace(
                self._fallback(
                    fallback_action, route, reason, status=batch.status, choice=action_answer.selected_choice,
                    probabilities=action_answer.probabilities, confidence=action_answer.confidence,
                    latency=batch.client_latency_ms, server_latency=batch.server_latency_ms,
                    timed_out=batch.timed_out, error=batch.error, request_bytes=batch.request_bytes,
                ),
                estimated_input_tokens=batch.estimated_input_tokens, judgments=judgments,
            )

        overrides: list[str] = []
        dodge = batch.answers.get("dodge")
        if dodge and dodge.status == "success" and dodge.selected_choice == "yes":
            evasive = next((item for item in candidates if item.action_id.startswith(("strafe_", "retreat_", "evade_")) and item.move != Vec2()), None)
            if evasive is not None:
                selected = evasive
        elif dodge and dodge.status != "success":
            overrides.append(f"dodge:{dodge.status}")
        trigger = batch.answers.get("trigger")
        if trigger and trigger.status == "success" and trigger.selected_choice == "release":
            selected = replace(selected, shoot=Vec2())
        elif trigger and trigger.status != "success":
            overrides.append(f"trigger:{trigger.status}")

        selected = replace(selected, confidence=action_answer.confidence, source=self.name)
        action = _safety_filter(state, selected, self.profile) if route == "combat" else selected
        return ProviderDecision(
            provider=self.name, model=batch.model, action=action,
            selected_choice=action_answer.selected_choice, probabilities=action_answer.probabilities,
            confidence=action_answer.confidence, top1_probability=action_answer.top1_probability,
            top2_probability=action_answer.top2_probability, margin=action_answer.margin,
            entropy=action_answer.entropy, client_latency_ms=batch.client_latency_ms,
            server_latency_ms=batch.server_latency_ms, status="partial" if overrides else batch.status,
            fallback=bool(overrides), fallback_reason=",".join(overrides), timed_out=batch.timed_out,
            error=batch.error, request_bytes=batch.request_bytes,
            estimated_input_tokens=batch.estimated_input_tokens, policy=route,
            schema_version="jev-composition-v1", judgments=judgments,
        )

    def choose_questions(
        self,
        observation: Mapping[str, Any],
        questions: Mapping[str, ProviderQuestion],
    ) -> ProviderQuestionBatch:
        """Ask independent questions once; never infer one answer from another.

        This returns judgments, not executable actions. The caller must combine
        valid answers with its current admissible actions and local safety rules.
        The existing single-action ``choose`` contract remains unchanged.
        """
        if not questions or any(not isinstance(key, str) or not key for key in questions):
            raise ValueError("questions must have non-empty string IDs")
        payload = {
            "model": self.model,
            "state": json.dumps(observation, ensure_ascii=False, separators=(",", ":")),
            "questions": {key: question.payload() for key, question in questions.items()},
        }
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        byte_count = len(data)
        missing = {key: ProviderAnswer(key) for key in questions}
        if self.requires_api_key and not self.api_key:
            return ProviderQuestionBatch(self.name, self.model, missing, "missing_api_key")
        request = urllib.request.Request(
            self.endpoint, data=data,
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
            },
            method="POST",
        )
        started = time.monotonic()
        try:
            with self._opener(request, timeout=self.settings.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except Exception as error:
            return ProviderQuestionBatch(
                self.name, self.model, missing, _remote_error_reason(error),
                client_latency_ms=round((time.monotonic() - started) * 1000.0, 2),
                request_bytes=byte_count, estimated_input_tokens=max(1, (byte_count + 3) // 4),
                timed_out=_is_timeout(error), error=_safe_error(error, self.api_key),
            )
        latency = round((time.monotonic() - started) * 1000.0, 2)
        if not isinstance(body, Mapping) or not isinstance(body.get("answers"), Mapping):
            return ProviderQuestionBatch(
                self.name, self.model, missing, "invalid_response", client_latency_ms=latency,
                request_bytes=byte_count, estimated_input_tokens=max(1, (byte_count + 3) // 4),
            )
        answers = {
            key: _parse_question_answer(key, question, body["answers"].get(key), self.settings.confidence_threshold)
            for key, question in questions.items()
        }
        successes = sum(answer.status == "success" for answer in answers.values())
        status = "success" if successes == len(answers) else "partial" if successes else "invalid_answers"
        return ProviderQuestionBatch(
            self.name, str(body.get("model") or self.model), answers, status,
            client_latency_ms=latency, server_latency_ms=_optional_response_number(body.get("latency_ms")),
            request_bytes=byte_count, estimated_input_tokens=max(1, (byte_count + 3) // 4),
        )


class BochaProvider(JevProvider):
    name = "bocha"
    requires_api_key = True

    def _request_payload(self, observation: Mapping[str, Any], instructions: str, candidates: list[Any]) -> dict[str, Any]:
        # Bocha's System One endpoint follows its public example: state is a
        # text field and the answer is keyed by ``action`` rather than the
        # project's internal ``next_action`` question id.
        return {
            "model": self.model,
            "state": json.dumps(observation, ensure_ascii=False, separators=(",", ":")),
            "questions": {
                "action": {
                    "type": "choice",
                    "instructions": instructions,
                    "criteria": {item.action_id: item.reason for item in candidates},
                }
            },
        }


class SystemOneProvider(BochaProvider):
    name = "systemone"
    requires_api_key = False


def _parse_question_answer(
    question_id: str, question: ProviderQuestion, raw: Any, threshold: float,
) -> ProviderAnswer:
    if not isinstance(raw, Mapping):
        return ProviderAnswer(question_id, status="missing_answer" if raw is None else "invalid_answer")
    choice = raw.get("choice", raw.get("value", raw.get("answer")))
    probabilities = _probabilities(raw.get("probabilities", raw.get("distribution", {})))
    # Do not report probabilities for choices that this question never offered.
    probabilities = {key: value for key, value in probabilities.items() if key in question.criteria and value <= 1.0}
    confidence = _optional_response_number(raw.get("confidence"))
    if confidence is None and "confidence" not in raw and isinstance(choice, str):
        confidence = probabilities.get(choice)
    valid_confidence = confidence is not None and 0.0 <= confidence <= 1.0
    top1, top2, margin, entropy = _distribution_metrics(probabilities)
    if not isinstance(choice, str) or choice not in question.criteria:
        status = "invalid_choice"
    elif not valid_confidence:
        status = "invalid_confidence"
    elif confidence < threshold:
        status = "low_confidence"
    else:
        status = "success"
    return ProviderAnswer(
        question_id=question_id, selected_choice=choice if isinstance(choice, str) else None,
        probabilities=probabilities, confidence=confidence if valid_confidence else 0.0,
        top1_probability=top1, top2_probability=top2, margin=margin, entropy=entropy, status=status,
    )


def create_provider(
    name: str,
    config: DecisionProviderConfig,
    profile: PolicyProfile | None = None,
    environ: Mapping[str, str] | None = None,
    opener: Any = None,
) -> DecisionProvider:
    name = _provider_name(name, "provider")
    settings = config.providers[name]
    if name == "local":
        return LocalProvider(settings, profile)
    if name == "bocha":
        return BochaProvider(settings, api_key=settings.api_key, profile=profile, opener=opener)
    if name == "systemone":
        return SystemOneProvider(settings, api_key=settings.api_key, profile=profile, opener=opener)
    return JevProvider(settings, api_key=settings.api_key, profile=profile, opener=opener)


def _probabilities(value: Any) -> dict[str, float]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, float] = {}
    for key, raw in value.items():
        number = _optional_response_number(raw)
        if number is not None and number >= 0.0:
            result[str(key)] = number
    return result


def _distribution_metrics(probabilities: Mapping[str, float]) -> tuple[float, float, float, float]:
    values = sorted((value for value in probabilities.values() if math.isfinite(value) and value >= 0.0), reverse=True)
    total = sum(values)
    if total <= 0.0:
        return 0.0, 0.0, 0.0, 0.0
    normalized = [value / total for value in values]
    top1 = normalized[0]
    top2 = normalized[1] if len(normalized) > 1 else 0.0
    entropy = -sum(value * math.log(value, 2) for value in normalized if value > 0.0)
    return round(top1, 6), round(top2, 6), round(top1 - top2, 6), round(entropy, 6)


def _response_number(value: Any, default: float) -> float:
    number = _optional_response_number(value)
    return default if number is None else number


def _optional_response_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _is_timeout(error: Exception) -> bool:
    if isinstance(error, (TimeoutError, socket.timeout)):
        return True
    return isinstance(error, urllib.error.URLError) and isinstance(error.reason, (TimeoutError, socket.timeout))


def _remote_error_reason(error: Exception) -> str:
    if _is_timeout(error):
        return "timeout"
    if isinstance(error, urllib.error.HTTPError):
        return "http_error"
    if isinstance(error, (json.JSONDecodeError, UnicodeError)):
        return "invalid_response"
    return "network_error"


def _safe_error(error: Exception, api_key: str) -> str:
    message = f"{type(error).__name__}: {error}"
    if isinstance(error, urllib.error.HTTPError):
        try:
            body = error.read(4096).decode("utf-8", errors="replace").strip()
        except Exception:
            body = ""
        if body:
            message += f" response={body}"
    if api_key:
        message = message.replace(api_key, "[redacted]")
    return message[:500]


def _public_health_details(value: Mapping[str, Any]) -> dict[str, Any]:
    blocked = {"authorization", "api_key", "apikey", "token", "access_token"}
    return {
        str(key): _sanitize_health_value(item)
        for key, item in value.items()
        if str(key).lower() not in blocked
    }


def _sanitize_health_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _public_health_details(value)
    if isinstance(value, list):
        return [_sanitize_health_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)[:500]
