"""Future FR-4 llama.cpp native completion client for explicit local loopback.

No connection, model read, warmup or service discovery occurs on import. The
future service launcher must establish one inference slot, prefix caching,
reviewed beam support and measured memory enforcement. This client requires
those actual trusted source declarations; it cannot establish them by a prompt
instruction or a persona/UI parameter. It never launches or downloads a model.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from http.client import HTTPConnection, HTTPException
import json
import math
import socket
from threading import Event, Lock, Thread
from time import monotonic
from urllib.parse import urlsplit

from ..config import AppConfig, require_source_file
from ..contracts import FailureClass, ReasonCode
from ..errors import (
    ConfigurationError, GenerationTimeoutError, GenerationTruncatedError, MissingDependencyError,
    ModelGenerationError, StarkT2SQLError,
)
from ..utils.fingerprints import sha256_file
from ..utils.local_only import require_allowed_url
from .prompt_builder import BuiltPrompt
from .template import require_sha256


@dataclass(frozen=True, slots=True)
class DecodingDefaults:
    """Frozen initial FR-4 baseline; changing it needs a new measured baseline.

    FR-4 requires a fixed seed without assigning its numeric value. 42 is an
    explicit implementation choice to be recorded with the eventual run.
    """

    temperature: float = field(default=0.0, init=False)
    seed: int = field(default=42, init=False)
    max_tokens: int = field(default=300, init=False)
    stop: tuple[str, ...] = field(default=(";",), init=False)
    timeout_seconds: float = field(default=120.0, init=False)


@dataclass(frozen=True, slots=True)
class LocalModelServiceContract:
    """Trusted actual deployment/build evidence supplied by the later owner.

    Digest strings must describe real inputs, not placeholders. The launcher
    declaration must come from local reviewed service configuration. This source
    declaration does not probe service flags or certify a running deployment.
    Greedy runs must not be compared with published SQLCoder beam benchmarks
    when actual local build review establishes missing beam support (FR-4.6).
    """

    model_sha256: str
    llama_cpp_build: str
    launcher_sha256: str
    beam_support_reviewed: bool
    beam_supported: bool
    weights_postdate_2024_02_07: bool
    memory_limit_enforced: bool
    slots: int = 1
    prefix_cache_enabled: bool = True

    def __post_init__(self) -> None:
        require_sha256(self.model_sha256, label="the actual GGUF model")
        require_sha256(self.launcher_sha256, label="the actual local model-service launcher")
        if not isinstance(self.llama_cpp_build, str) or not self.llama_cpp_build.strip():
            raise MissingDependencyError("The actual llama.cpp build identifier is required.")
        booleans = (
            self.beam_support_reviewed, self.beam_supported,
            self.weights_postdate_2024_02_07, self.memory_limit_enforced,
            self.prefix_cache_enabled,
        )
        if any(type(value) is not bool for value in booleans):
            raise ConfigurationError("Model service evidence must use explicit boolean declarations.")
        if not self.beam_support_reviewed:
            raise MissingDependencyError("Actual local build beam-support review evidence is pending.")
        if not self.weights_postdate_2024_02_07:
            raise MissingDependencyError("Required post-update SQLCoder weight provenance is unavailable.")
        if not self.memory_limit_enforced:
            raise MissingDependencyError("The actual local model service has no recorded memory enforcement.")
        if type(self.slots) is not int or self.slots != 1 or not self.prefix_cache_enabled:
            raise ConfigurationError("FR-4 requires one model inference slot and enabled prefix caching.")


@dataclass(frozen=True, slots=True)
class GenerationResult:
    """Internal generated text and explicit termination facts for FR-4.8.

    raw_response is the bounded native JSON response, intended only for local
    CLI/harness diagnostics. Neither this object nor the raw content belongs in
    persona UI state. ``token_limit_reached`` is not an elapsed-time timeout.
    """

    raw_output: str = field(repr=False)
    generation_ms: float
    token_limit_reached: bool
    stopped_semicolon: bool
    finish_reason: str
    tokens_predicted: int
    scored: bool = True
    raw_response: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.raw_output, str) or not isinstance(self.finish_reason, str):
            raise ConfigurationError("Model generation content and termination reason must be text.")
        if (
            isinstance(self.generation_ms, bool) or not isinstance(self.generation_ms, (int, float))
            or not math.isfinite(self.generation_ms) or self.generation_ms < 0
        ):
            raise ConfigurationError("Generation duration must be finite and nonnegative.")
        if type(self.tokens_predicted) is not int or self.tokens_predicted < 0:
            raise ConfigurationError("Generated-token metadata must be a nonnegative integer.")
        if any(type(value) is not bool for value in (
            self.token_limit_reached, self.stopped_semicolon, self.scored,
        )):
            raise ConfigurationError("Generation termination metadata must be explicit booleans.")


def _attach_generation_details(
    error: StarkT2SQLError, *, started: float, raw_output: str | None,
    raw_response: str | None = None,
) -> StarkT2SQLError:
    """Preserve private text on shared typed exceptions for the pipeline trace."""
    error.raw_output = raw_output
    error.raw_response = raw_response
    error.generation_ms = max(0.0, (monotonic() - started) * 1000.0)
    error.failure_class = (
        FailureClass.TIMEOUT_GEN if isinstance(error, GenerationTimeoutError)
        else FailureClass.TRUNCATED_GEN if isinstance(error, GenerationTruncatedError)
        else FailureClass.RUNTIME
    )
    return error


class _RequestSocket:
    """Retain the request socket if http.client detaches it for a close response.

    The foreground captures after request() connects, before getresponse() can
    clear HTTPConnection.sock. The watchdog may only shut down this handle;
    response/connection closure remains with the requesting thread.
    """

    def __init__(self, connection: HTTPConnection) -> None:
        self._connection = connection
        self._captured = None
        self._lock = Lock()

    def capture(self) -> None:
        with self._lock:
            self._captured = getattr(self._connection, "sock", None)

    @property
    def sock(self):
        with self._lock:
            return self._captured if self._captured is not None else getattr(self._connection, "sock", None)


def _interrupt_socket(connection: HTTPConnection | _RequestSocket) -> None:
    """Interrupt I/O without closing or mutating the shared HTTPConnection."""
    current_socket = getattr(connection, "sock", None)
    if current_socket is not None:
        try:
            current_socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


def _deadline_guard(
    connection: HTTPConnection | _RequestSocket, *, deadline: float, done: Event,
    expired: Event, cancelled: Event, cancel_event: Event | None,
) -> None:
    while not done.is_set():
        if cancel_event is not None and cancel_event.is_set():
            cancelled.set()
            _interrupt_socket(connection)
            return
        remaining = deadline - monotonic()
        if remaining <= 0:
            expired.set()
            _interrupt_socket(connection)
            return
        done.wait(min(0.05, remaining))


def _completion_termination(payload: dict[str, object], max_tokens: int) -> tuple[bool, bool, str, int]:
    """Normalize native llama.cpp completion metadata without inventing a stop reason.

    Older releases report stopped_word/stopped_eos/stopped_limit. Modern releases
    may supply stop_type and stopping_word when response_fields requests them.
    Some local builds return only stop and tokens_predicted: stop=True proves
    termination, but does NOT mean that the semicolon stopping word was seen.

    An ambiguous completion exactly at the token cap is conservatively treated
    as truncated, unless a native word-stop explicitly proves semicolon stop.
    A SQL AST validator must still review every candidate after extraction.
    """
    if type(payload) is not dict or type(max_tokens) is not int or max_tokens <= 0:
        raise ModelGenerationError("Native completion metadata and request limit are malformed.")
    # /completion is the native API. OpenAI finish_reason aliases cannot prove
    # a native stop or override explicit native flags (especially 'limit').
    if "finish_reason" in payload:
        raise ModelGenerationError("Non-native completion stop metadata is unsupported.")
    tokens = payload.get("tokens_predicted")
    if type(tokens) is not int or not 0 <= tokens <= max_tokens:
        raise ModelGenerationError("Native predicted-token metadata is missing or outside the request limit.")
    if "truncated" in payload:
        if type(payload["truncated"]) is not bool:
            raise ModelGenerationError("Native prompt truncation metadata is malformed.")
        if payload["truncated"]:
            raise ModelGenerationError("The model truncated its supplied prompt context.")
    if "stop" in payload and type(payload["stop"]) is not bool:
        raise ModelGenerationError("Native completion terminal flag is malformed.")
    terminal_flag = payload.get("stop")
    stop_type = payload.get("stop_type")
    if "stop_type" in payload and type(stop_type) is not str:
        raise ModelGenerationError("Native stop_type is malformed.")
    if "stopping_word" in payload and type(payload["stopping_word"]) is not str:
        raise ModelGenerationError("Native stopping_word is malformed.")
    legacy_keys = ("stopped_word", "stopped_eos", "stopped_limit")
    has_legacy = any(key in payload for key in legacy_keys)
    if stop_type is not None:
        if type(stop_type) is not str or stop_type not in {"word", "eos", "limit", "none"}:
            raise ModelGenerationError("Native stop_type is unsupported.")
        if stop_type == "none" or terminal_flag is False:
            raise ModelGenerationError("The unstreamed completion did not report a terminal state.")
        if has_legacy:
            if any(type(payload.get(key)) is not bool for key in legacy_keys):
                raise ModelGenerationError("Conflicting or partial native completion metadata.")
            expected = {
                "word": (True, False, False),
                "eos": (False, True, False),
                "limit": (False, False, True),
            }[stop_type]
            if tuple(payload[key] for key in legacy_keys) != expected:
                raise ModelGenerationError("Native completion stop metadata conflicts.")
        if stop_type == "word":
            if payload.get("stopping_word") != ";":
                raise ModelGenerationError("The service reported an unapproved stopping word.")
            return False, True, "SEMICOLON_STOP", tokens
        if payload.get("stopping_word") not in (None, ""):
            raise ModelGenerationError("A stopping word was reported without a word stop.")
        reached_limit = stop_type == "limit" or tokens >= max_tokens
        return reached_limit, False, "TOKEN_LIMIT" if reached_limit else "EOS", tokens
    if has_legacy:
        if any(type(payload.get(key)) is not bool for key in legacy_keys):
            raise ModelGenerationError("Partial native legacy completion metadata.")
        word, eos, limit = (payload[key] for key in legacy_keys)
        if sum((word, eos, limit)) != 1 or terminal_flag is False:
            raise ModelGenerationError("Native legacy completion states conflict or are not terminal.")
        if word:
            if payload.get("stopping_word") != ";":
                raise ModelGenerationError("The service reported an unapproved stopping word.")
            return False, True, "SEMICOLON_STOP", tokens
        if payload.get("stopping_word") not in (None, ""):
            raise ModelGenerationError("A stopping word was reported without a word stop.")
        reached_limit = limit or tokens >= max_tokens
        return reached_limit, False, "TOKEN_LIMIT" if reached_limit else "EOS", tokens
    if terminal_flag is True:
        if payload.get("stopping_word") not in (None, ""):
            raise ModelGenerationError("A stopping word was reported without a word-stop reason.")
        # A compact response cannot distinguish EOS from a stop word. Never
        # claim that it specifically stopped on ';' or completed at the cap.
        if tokens >= max_tokens:
            return True, False, "TOKEN_LIMIT", tokens
        return False, False, "STOP_REASON_UNSPECIFIED", tokens
    raise ModelGenerationError("Native generation termination metadata is unavailable.")


def _completion_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate JSON keys instead of hiding conflicting stop evidence."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ModelGenerationError("The native completion contains duplicate metadata keys.")
        result[key] = value
    return result


class LocalInferenceClient:
    """One-flight, bounded /completion requests through http.client.

    Numeric destinations come from the existing exact endpoint guard. Standard
    http.client does not inherit environment proxies, resolve custom DNS names,
    follow redirects or apply an external retry. No alternative HTTP provider
    or endpoint supplied by question/UI text is accepted.
    """

    def __init__(self, config: AppConfig, *, service: LocalModelServiceContract) -> None:
        if type(config) is not AppConfig or type(service) is not LocalModelServiceContract:
            raise ConfigurationError("Local inference requires typed application and service declarations.")
        if config.limits.generation_timeout_seconds <= 0:
            raise ConfigurationError("Generation timeout must be positive.")
        canonical = require_allowed_url(
            config.llama_cpp_url, allowed_endpoints=config.allowed_runtime_endpoints,
        )
        parsed = urlsplit(canonical)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1"}:
            raise ConfigurationError("The FR-4 llama.cpp service must use explicit HTTP at 127.0.0.1 or ::1.")
        if parsed.path not in {"", "/"} or parsed.query:
            raise ConfigurationError("The llama.cpp configuration must name the local service root.")
        model_file = require_source_file(config.paths.model_file, label="actual local GGUF model")
        if sha256_file(model_file) != service.model_sha256:
            raise ConfigurationError("The local GGUF file differs from the trusted model-source binding.")
        if config.resource_budgets.model_memory_limit_mib is None:
            raise MissingDependencyError("The measured local model memory budget is unavailable.")
        measurement = require_source_file(
            config.resource_budgets.measurement_source, label="actual model resource measurements",
        )
        self.measurement_sha256 = sha256_file(measurement)
        self.config = config
        self.service = service
        self.decoding = DecodingDefaults()
        self._host = parsed.hostname
        self._port = parsed.port
        self._single_flight = Lock()

    def generate(self, prompt: BuiltPrompt, *, cancel_event: Event | None = None) -> GenerationResult:
        """Send one native request bounded by the configured total deadline.

        Structured metadata never infers a stopping word from generated text.
        Actual local build compatibility remains unverified until real response
        evidence is supplied. The watchdog only interrupts I/O; the foreground
        closes resources and releases the single-flight guard in finally.
        """
        if type(prompt) is not BuiltPrompt:
            raise ConfigurationError("The model accepts only a built immutable prompt.")
        if cancel_event is not None and not isinstance(cancel_event, Event):
            raise ConfigurationError("A request cancellation event must be explicitly supplied.")
        if not self._single_flight.acquire(blocking=False):
            raise ModelGenerationError("The local model already has an active request.")
        started = monotonic()
        deadline = started + self.config.limits.generation_timeout_seconds
        connection: HTTPConnection | None = None
        response = None
        watcher: Thread | None = None
        done, expired, cancelled = Event(), Event(), Event()
        raw_output: str | None = None
        response_text: str | None = None
        try:
            if cancel_event is not None and cancel_event.is_set():
                raise ModelGenerationError("Generation was cancelled before submission.")
            # Reapply the source allowlist at submission, with no proxy routing.
            require_allowed_url(self.config.llama_cpp_url, allowed_endpoints=self.config.allowed_runtime_endpoints)
            connection = HTTPConnection(self._host, self._port, timeout=max(0.001, deadline - monotonic()))
            interruption = _RequestSocket(connection)
            watcher = Thread(
                target=_deadline_guard,
                kwargs={
                    "connection": interruption, "deadline": deadline, "done": done,
                    "expired": expired, "cancelled": cancelled, "cancel_event": cancel_event,
                },
                name="stark-local-generation-deadline", daemon=True,
            )
            watcher.start()
            body = json.dumps({
                "prompt": prompt.text, "temperature": self.decoding.temperature,
                "seed": self.decoding.seed, "n_predict": self.decoding.max_tokens,
                "stop": list(self.decoding.stop), "stream": False,
                "cache_prompt": True, "id_slot": 0,
                # A server may omit unsupported fields. Their request is not
                # evidence of termination; the parser requires actual metadata.
                "response_fields": [
                    "content", "tokens_predicted", "stop", "stop_type",
                    "stopping_word", "stopped_word", "stopped_eos",
                    "stopped_limit", "truncated",
                ],
            }, ensure_ascii=False, allow_nan=False).encode("utf-8")
            connection.request("POST", "/completion", body=body, headers={
                "Content-Type": "application/json", "Accept": "application/json",
                "Connection": "close",
            })
            interruption.capture()
            if expired.is_set() or monotonic() >= deadline:
                raise GenerationTimeoutError("The local model exceeded its total generation deadline.")
            if cancelled.is_set() or (cancel_event is not None and cancel_event.is_set()):
                raise ModelGenerationError("Generation was cancelled; the candidate must not execute.")
            response = connection.getresponse()
            # No redirects are followed, even to another loopback endpoint.
            if 300 <= response.status < 400:
                raise ModelGenerationError("The local model returned a redirect; redirects are disabled.")
            # Bounded diagnostics: model output is <=300 tokens, but a malformed
            # service must not stream an unbounded response into local memory.
            response_bytes = response.read(2_097_153)
            if len(response_bytes) > 2_097_152:
                raise ModelGenerationError("The local model response exceeded the configured byte bound.")
            response_text = response_bytes.decode("utf-8", errors="strict")
            if response.status != 200:
                raise ModelGenerationError("The local model returned an unsuccessful completion response.")
            payload = json.loads(response_text, object_pairs_hook=_completion_object)
            if not isinstance(payload, dict) or not isinstance(payload.get("content"), str):
                raise ModelGenerationError("The local model response has no native completion content.")
            raw_output = payload["content"]
            reached_limit, stopped_semicolon, finish, tokens = _completion_termination(
                payload, self.decoding.max_tokens,
            )
            if expired.is_set() or monotonic() >= deadline:
                raise GenerationTimeoutError("The local model exceeded its total generation deadline.")
            if cancelled.is_set() or (cancel_event is not None and cancel_event.is_set()):
                raise ModelGenerationError("Generation was cancelled; the candidate must not execute.")
            if reached_limit:
                # The extractor's historical first-delimiter rule cannot turn
                # server-reported exhaustion into completion, even if raw text
                # contains ';'. Preserve the existing typed FR-4.8 failure.
                raise GenerationTruncatedError("The model reached its generation token limit without a verified semicolon stop.")
            return GenerationResult(
                raw_output, (monotonic() - started) * 1000.0,
                reached_limit, stopped_semicolon, finish, tokens, prompt.scored, response_text,
            )
        except StarkT2SQLError as exc:
            if not isinstance(exc, GenerationTimeoutError) and (expired.is_set() or monotonic() >= deadline):
                replacement = GenerationTimeoutError("The local model exceeded its total generation deadline.")
                raise _attach_generation_details(replacement, started=started, raw_output=raw_output, raw_response=response_text) from exc
            raise _attach_generation_details(exc, started=started, raw_output=raw_output, raw_response=response_text)
        except (TimeoutError, socket.timeout) as exc:
            if not expired.is_set() and monotonic() < deadline and (cancelled.is_set() or (cancel_event is not None and cancel_event.is_set())):
                error = ModelGenerationError("Generation was cancelled; the candidate must not execute.")
            else:
                error = GenerationTimeoutError("The local model generation timed out.")
            raise _attach_generation_details(error, started=started, raw_output=raw_output, raw_response=response_text) from exc
        except (OSError, HTTPException, UnicodeError, ValueError, TypeError, AttributeError) as exc:
            if expired.is_set() or monotonic() >= deadline:
                error = GenerationTimeoutError("The local model exceeded its total generation deadline.")
            elif cancelled.is_set() or (cancel_event is not None and cancel_event.is_set()):
                error = ModelGenerationError("Generation was cancelled; the candidate must not execute.")
            elif isinstance(exc, (OSError, HTTPException)):
                error = ModelGenerationError("The local model service is unavailable.", reason_code=ReasonCode.MODEL_UNAVAILABLE)
            else:
                error = ModelGenerationError("The local model returned a malformed completion response.")
            raise _attach_generation_details(error, started=started, raw_output=raw_output, raw_response=response_text) from exc
        finally:
            done.set()
            try:
                try:
                    if response is not None:
                        try:
                            response.close()
                        except OSError:
                            pass
                finally:
                    try:
                        if connection is not None:
                            try:
                                connection.close()
                            except OSError:
                                pass
                    finally:
                        if watcher is not None:
                            watcher.join(timeout=0.1)
            finally:
                self._single_flight.release()


def warmup(
    client: LocalInferenceClient, prompt: BuiltPrompt, *, cancel_event: Event | None = None,
) -> GenerationResult:
    """Explicit future helper; never called on import/startup by this module.

    The caller must perform one warmup before a measured run and exclude this
    result from every score/metric. A warmup uses real configured local inputs;
    this source contains no planted question, fixture or sample completion.
    """
    if type(client) is not LocalInferenceClient or type(prompt) is not BuiltPrompt:
        raise ConfigurationError("Warmup requires the configured local client and an actual built prompt.")
    return client.generate(replace(prompt, scored=False), cancel_event=cancel_event)
