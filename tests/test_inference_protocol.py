"""Native llama.cpp protocol and watchdog regression contracts.

No model, SQL, database, network connection, or runtime service is started.
All payloads are synthetic protocol examples. No native model response
capture is available; these tests do not establish live-build compatibility.
"""

import socket
import json
from threading import Event, Lock, Thread, get_ident
from types import SimpleNamespace

import pytest

from stark_t2sql.contracts import FailureClass, ReasonCode
from stark_t2sql.errors import GenerationTimeoutError, GenerationTruncatedError, ModelGenerationError
from stark_t2sql.inference.client import (
    DecodingDefaults, LocalInferenceClient,
    _completion_termination,
    _interrupt_socket,
)
from stark_t2sql.inference.prompt_builder import BuiltPrompt
from stark_t2sql.utils.local_only import LoopbackEndpoint


@pytest.mark.parametrize("payload,expected", (
    (
        {"content": " SELECT COUNT(e.employee_id) FROM employees e",
         "tokens_predicted": 13, "stop": True},
        (False, False, "STOP_REASON_UNSPECIFIED", 13),
    ),
    (
        {"content": "SELECT 1", "tokens_predicted": 300, "stop": True},
        (True, False, "TOKEN_LIMIT", 300),
    ),
    (
        {"content": "SELECT 1", "tokens_predicted": 300, "stop": True,
         "stop_type": "word", "stopping_word": ";"},
        (False, True, "SEMICOLON_STOP", 300),
    ),
    (
        {"content": "SELECT 1", "tokens_predicted": 13, "stop": True,
         "stop_type": "eos"},
        (False, False, "EOS", 13),
    ),
    (
        {"content": "SELECT 1", "tokens_predicted": 300, "stop": True,
         "stop_type": "limit"},
        (True, False, "TOKEN_LIMIT", 300),
    ),
    (
        {"content": "SELECT 1", "tokens_predicted": 300, "stopped_word": True,
         "stopped_eos": False, "stopped_limit": False, "stopping_word": ";"},
        (False, True, "SEMICOLON_STOP", 300),
    ),
    (
        {"content": "SELECT 1", "tokens_predicted": 300, "stopped_word": False,
         "stopped_eos": False, "stopped_limit": True},
        (True, False, "TOKEN_LIMIT", 300),
    ),
    (
        {"content": "SELECT 1", "tokens_predicted": 8, "stopped_word": False,
         "stopped_eos": True, "stopped_limit": False},
        (False, False, "EOS", 8),
    ),
))
def test_native_completion_metadata_formats(payload, expected):
    assert _completion_termination(payload, 300) == expected


@pytest.mark.parametrize("payload", (
    {"tokens_predicted": 13},
    {"tokens_predicted": 13, "stop": False},
    {"tokens_predicted": 301, "stop": True},
    {"tokens_predicted": True, "stop": True},
    {"tokens_predicted": 12, "stop": "yes"},
    {"tokens_predicted": 12, "stop": True, "stop_type": "none"},
    {"tokens_predicted": 12, "stop": True, "stop_type": "word"},
    {"tokens_predicted": 12, "stop": True, "stop_type": "word",
     "stopping_word": "UNREVIEWED"},
    {"tokens_predicted": 12, "stop": True, "stop_type": "limit",
     "stopping_word": ";"},
    {"tokens_predicted": 12, "stop": True, "stop_type": "eos",
     "stopped_word": True, "stopped_eos": False, "stopped_limit": False,
     "stopping_word": ";"},
    {"tokens_predicted": 12, "stop": True, "truncated": True},
    {"tokens_predicted": 12, "stop": True, "truncated": "true"},
    {"tokens_predicted": 12, "stopped_word": True},
    {"tokens_predicted": 12, "stopped_word": False,
     "stopped_eos": False, "stopped_limit": False},
))
def test_missing_conflicting_or_unsafe_terminal_metadata_fails_closed(payload):
    with pytest.raises(ModelGenerationError):
        _completion_termination(payload, 300)


def test_watchdog_shutdown_does_not_close_shared_http_connection():
    class SocketProbe:
        def __init__(self):
            self.shutdown_calls = []

        def shutdown(self, how):
            self.shutdown_calls.append(how)

    class HTTPConnectionProbe:
        def __init__(self):
            self.sock = SocketProbe()
            self.close_called = False

        def close(self):
            self.close_called = True
            self.sock = None

    connection = HTTPConnectionProbe()
    _interrupt_socket(connection)
    assert connection.sock is not None
    assert connection.sock.shutdown_calls == [socket.SHUT_RDWR]
    assert connection.close_called is False


def test_watchdog_handles_socket_already_detached_without_mutating_connection():
    class ConnectionProbe:
        sock = None

        def close(self):
            raise AssertionError("Watchdog must not call HTTPConnection.close")

    _interrupt_socket(ConnectionProbe())


@pytest.mark.parametrize("metadata", (
    {"stop_type": None}, {"stop_type": ""}, {"stop_type": 1},
    {"stop_type": "stop"}, {"stop_type": "unknown"}, {"stop_type": "EOS"},
    {"stopping_word": ";"}, {"stopping_word": "UNREVIEWED"},
    {"stopping_word": None}, {"stopping_word": False}, {"stopping_word": []},
    {"truncated": None}, {"truncated": 0}, {"stop": None}, {"stop": 1},
    {"finish_reason": "length"}, {"finish_reason": "stop"}, {"finish_reason": "unknown"},
    {"stopped_eos": None}, {"stopped_limit": False},
    {"stopped_word": False, "stopped_eos": True, "stopped_limit": True},
    {"stop_type": "word", "stopping_word": ";", "stopped_word": True},
    {"stop_type": "word", "stopping_word": ";", "stopped_word": True, "stopped_eos": False, "stopped_limit": True},
    {"stop_type": "eos", "stopping_word": ";"},
    {"stop_type": "eos", "stop": False},
))
def test_untrusted_or_conflicting_metadata_cannot_be_masked_by_compact_stop(metadata):
    payload = {"tokens_predicted": 12, "stop": True, **metadata}
    with pytest.raises(ModelGenerationError):
        _completion_termination(payload, 300)


@pytest.mark.parametrize("tokens", (None, True, False, -1, 301, 1.0, "12", [], float("nan")))
def test_native_count_must_be_an_exact_integer_within_the_request(tokens):
    with pytest.raises(ModelGenerationError):
        _completion_termination({"tokens_predicted": tokens, "stop": True}, 300)


@pytest.mark.parametrize("maximum", (None, True, 0, -1, 300.0, "300"))
def test_request_token_bound_must_be_explicit(maximum):
    with pytest.raises(ModelGenerationError):
        _completion_termination({"tokens_predicted": 12, "stop": True}, maximum)


@pytest.mark.parametrize("kind,legacy", (
    ("word", {"stopped_word": True, "stopped_eos": False, "stopped_limit": False}),
    ("eos", {"stopped_word": False, "stopped_eos": True, "stopped_limit": False}),
    ("limit", {"stopped_word": False, "stopped_eos": False, "stopped_limit": True}),
))
def test_consistent_modern_and_legacy_evidence_agree(kind, legacy):
    payload = {"tokens_predicted": 12, "stop_type": kind, **legacy}
    if kind == "word":
        payload["stopping_word"] = ";"
    assert _completion_termination(payload, 300) == (kind == "limit", kind == "word", {"word": "SEMICOLON_STOP", "eos": "EOS", "limit": "TOKEN_LIMIT"}[kind], 12)


@pytest.mark.parametrize("metadata", (
    {"stop": True}, {"stop_type": "eos"},
    {"stopped_word": False, "stopped_eos": True, "stopped_limit": False},
))
def test_no_earlier_word_stop_at_token_cap_is_exhaustion(metadata):
    assert _completion_termination({"tokens_predicted": 300, **metadata}, 300) == (True, False, "TOKEN_LIMIT", 300)


@pytest.fixture
def native_request(monkeypatch):
    """Transport-only unit composition: no model files, evidence or sockets.

    Bypass constructor resource verification explicitly for this synthetic test;
    this fixture is not a model/service approval or a deployed client instance.
    The production generate(), parser, watchdog and endpoint guard run as-is.
    """
    from stark_t2sql.inference import client as module

    owner = get_ident()
    shutdown = Event()
    request = SimpleNamespace(
        payload={"content": "SELECT 1", "tokens_predicted": 3, "stop_type": "eos"},
        response_bytes=None, status=200, detach=False, read_hook=None,
        request_error=None, close_error=False, connections=[], events=[], bodies=[],
    )

    class SocketProbe:
        def shutdown(self, how):
            request.events.append(("shutdown", how, get_ident()))
            shutdown.set()

        def close(self):
            raise AssertionError("The watchdog cannot close a shared socket")

    class ResponseProbe:
        @property
        def status(self):
            return request.status

        def read(self, limit):
            assert limit == 2_097_153
            if request.read_hook:
                request.read_hook()
            return request.response_bytes if request.response_bytes is not None else json.dumps(request.payload).encode()

        def close(self):
            request.events.append(("response.close", get_ident()))
            if isinstance(request.close_error, BaseException):
                raise request.close_error
            if request.close_error:
                raise OSError("TEST_ONLY cleanup failure")

    class ConnectionProbe:
        def __init__(self, host, port, *, timeout):
            assert (host, port) == ("127.0.0.1", 18081)
            self.sock = None
            self.timeout = timeout
            request.connections.append(self)

        def request(self, method, path, *, body, headers):
            assert method == "POST" and path == "/completion"
            self.sock = SocketProbe()
            request.bodies.append(json.loads(body))
            if request.request_error:
                raise request.request_error

        def getresponse(self):
            if request.detach:
                self.sock = None  # http.client may transfer ownership to the response.
            return ResponseProbe()

        def close(self):
            request.events.append(("connection.close", get_ident()))
            self.sock = None

    monkeypatch.setattr(module, "HTTPConnection", ConnectionProbe)
    client = object.__new__(LocalInferenceClient)
    client.config = SimpleNamespace(
        limits=SimpleNamespace(generation_timeout_seconds=2.0),
        llama_cpp_url="http://127.0.0.1:18081",
        allowed_runtime_endpoints=(LoopbackEndpoint("http", "127.0.0.1", 18081),),
    )
    client.decoding = DecodingDefaults()
    client._host, client._port, client._single_flight = "127.0.0.1", 18081, Lock()
    prompt = BuiltPrompt("TEST_ONLY private prompt", 2, *("a" * 64 for _ in range(4)))
    request.client, request.prompt, request.shutdown, request.owner = client, prompt, shutdown, owner
    return request


@pytest.mark.parametrize("metadata,reason", (
    ({"stop_type": "word", "stopping_word": ";"}, "SEMICOLON_STOP"),
    ({"stop_type": "eos"}, "EOS"),
    ({"stop": True}, "STOP_REASON_UNSPECIFIED"),
    ({"stopped_word": False, "stopped_eos": True, "stopped_limit": False}, "EOS"),
))
def test_generate_uses_reported_metadata_and_never_appends_semicolon(native_request, metadata, reason):
    unit = native_request
    unit.payload = {"content": "SELECT 1", "tokens_predicted": 3, **metadata}
    result = unit.client.generate(unit.prompt)
    assert result.raw_output == "SELECT 1" and result.finish_reason == reason
    assert result.stopped_semicolon is (reason == "SEMICOLON_STOP")
    assert not result.token_limit_reached
    assert "SELECT 1" not in repr(result)
    body = unit.bodies[0]
    assert body["stop"] == [";"] and body["n_predict"] == 300
    assert body["temperature"] == 0 and body["seed"] == 42
    assert body["stream"] is False and body["cache_prompt"] is True and body["id_slot"] == 0
    assert {"stop_type", "stopping_word", "stopped_limit", "truncated", "tokens_predicted"} <= set(body["response_fields"])
    assert unit.events == [("response.close", unit.owner), ("connection.close", unit.owner)]
    assert not unit.client._single_flight.locked()


@pytest.mark.parametrize("metadata", (
    {"stop_type": "limit"}, {"stop": True}, {"stop_type": "eos"},
    {"stopped_word": False, "stopped_eos": False, "stopped_limit": True},
    {"stopped_word": False, "stopped_eos": True, "stopped_limit": False},
))
def test_generation_exhaustion_cannot_reach_extractor_even_when_raw_text_ends_in_semicolon(native_request, metadata):
    unit = native_request
    unit.payload = {"content": "TEST_ONLY SELECT 'unfinished;", "tokens_predicted": 300, **metadata}
    with pytest.raises(GenerationTruncatedError) as captured:
        unit.client.generate(unit.prompt)
    assert captured.value.reason_code is ReasonCode.GENERATION_TRUNCATED
    assert captured.value.failure_class is FailureClass.TRUNCATED_GEN
    assert not isinstance(captured.value, GenerationTimeoutError)
    assert captured.value.raw_output == unit.payload["content"]
    assert "TEST_ONLY" not in captured.value.safe_public_description
    assert not unit.client._single_flight.locked()


def test_verified_word_stop_at_cap_is_distinct_from_exhaustion(native_request):
    unit = native_request
    unit.payload = {"content": "SELECT 1", "tokens_predicted": 300, "stop_type": "word", "stopping_word": ";"}
    assert unit.client.generate(unit.prompt).stopped_semicolon is True


@pytest.mark.parametrize("metadata", ({}, {"timings": {"predicted_n": 3}}, {"usage": {"completion_tokens": 3}}))
def test_missing_or_ignored_requested_fields_are_not_guessed(native_request, metadata):
    unit = native_request
    unit.payload = {"content": "SELECT 1;", **metadata}
    with pytest.raises(ModelGenerationError):
        unit.client.generate(unit.prompt)
    assert not unit.client._single_flight.locked()


def test_duplicate_wire_keys_cannot_hide_conflicting_native_states(native_request):
    unit = native_request
    unit.response_bytes = b'{"content":"SELECT 1;","tokens_predicted":300,"stop_type":"limit","stop_type":"word","stopping_word":";"}'
    with pytest.raises(ModelGenerationError, match="duplicate"):
        unit.client.generate(unit.prompt)


@pytest.mark.parametrize("detach", (False, True))
def test_total_deadline_interrupts_body_even_after_http_connection_detaches_socket(native_request, detach):
    from time import monotonic
    unit = native_request
    unit.detach = detach
    unit.client.config.limits.generation_timeout_seconds = 0.08
    def blocked_read():
        assert unit.shutdown.wait(2), "Watchdog did not interrupt the captured socket"
        raise OSError("TEST_ONLY interrupted body")
    unit.read_hook = blocked_read
    started = monotonic()
    with pytest.raises(GenerationTimeoutError) as captured:
        unit.client.generate(unit.prompt)
    assert monotonic() - started < 2
    assert 0 < unit.connections[0].timeout <= 0.080001  # monotonic float subtraction rounding
    assert captured.value.failure_class is FailureClass.TIMEOUT_GEN
    assert next(event for event in unit.events if event[0] == "shutdown")[2] != unit.owner
    assert unit.events[-2:] == [("response.close", unit.owner), ("connection.close", unit.owner)]
    assert not unit.client._single_flight.locked()


@pytest.mark.parametrize("read_error", (OSError, TimeoutError))
def test_cancelled_blocked_read_is_generation_error_not_elapsed_timeout(native_request, read_error):
    unit = native_request
    cancel = Event()
    def blocked_read():
        cancel.set()
        assert unit.shutdown.wait(2)
        raise read_error("TEST_ONLY interrupted request")
    unit.read_hook = blocked_read
    with pytest.raises(ModelGenerationError) as captured:
        unit.client.generate(unit.prompt, cancel_event=cancel)
    assert not isinstance(captured.value, GenerationTimeoutError)
    assert captured.value.failure_class is FailureClass.RUNTIME
    assert not unit.client._single_flight.locked()


def test_pre_cancelled_request_opens_no_transport_and_releases_lock(native_request):
    unit = native_request
    cancel = Event()
    cancel.set()
    with pytest.raises(ModelGenerationError):
        unit.client.generate(unit.prompt, cancel_event=cancel)
    assert not unit.connections and not unit.client._single_flight.locked()


def test_concurrent_generate_is_rejected_without_submitting_duplicate(native_request):
    unit = native_request
    entered, release = Event(), Event()
    results, errors = [], []
    def blocked_read():
        entered.set()
        assert release.wait(2)
    unit.read_hook = blocked_read
    def first_request():
        try:
            results.append(unit.client.generate(unit.prompt))
        except BaseException as error:
            errors.append(error)
    worker = Thread(target=first_request)
    worker.start()
    try:
        assert entered.wait(2)
        with pytest.raises(ModelGenerationError, match="already has an active request"):
            unit.client.generate(unit.prompt)
        assert len(unit.connections) == len(unit.bodies) == 1
    finally:
        release.set()
        worker.join(2)
    assert not worker.is_alive() and not errors and len(results) == 1
    assert not unit.client._single_flight.locked()


@pytest.mark.parametrize("failure", (OSError("TEST_ONLY transport"), ValueError("TEST_ONLY malformed"), KeyboardInterrupt()))
def test_request_exceptions_and_base_exception_release_foreground_connection(native_request, failure):
    unit = native_request
    unit.request_error = failure
    expected = KeyboardInterrupt if isinstance(failure, KeyboardInterrupt) else ModelGenerationError
    with pytest.raises(expected):
        unit.client.generate(unit.prompt)
    assert unit.events == [("connection.close", unit.owner)]
    assert not unit.client._single_flight.locked()


@pytest.mark.parametrize("wire,status", ((b'not json', 200), (b'\xff', 200), (b'[]', 200), (b'{}', 200), (b'{}', 302), (b'{}', 503), (b'x' * 2_097_153, 200)), ids=("invalid-json", "invalid-utf8", "array", "missing-content", "redirect", "service-error", "byte-bound"))
def test_response_failures_close_resources_and_release_single_flight(native_request, wire, status):
    unit = native_request
    unit.response_bytes, unit.status = wire, status
    with pytest.raises(ModelGenerationError):
        unit.client.generate(unit.prompt)
    assert unit.events[-2:] == [("response.close", unit.owner), ("connection.close", unit.owner)]
    assert not unit.client._single_flight.locked()


def test_response_cleanup_error_still_closes_connection_and_releases_lock(native_request):
    unit = native_request
    unit.close_error = True
    assert unit.client.generate(unit.prompt).finish_reason == "EOS"
    assert unit.events[-1] == ("connection.close", unit.owner)
    assert not unit.client._single_flight.locked()


@pytest.mark.parametrize("failure", (ValueError("TEST_ONLY abnormal response cleanup"), KeyboardInterrupt()))
def test_abnormal_response_cleanup_still_attempts_connection_cleanup(native_request, failure):
    unit = native_request
    unit.close_error = failure
    with pytest.raises(type(failure)):
        unit.client.generate(unit.prompt)
    assert unit.events[-2:] == [("response.close", unit.owner), ("connection.close", unit.owner)]
    assert not unit.client._single_flight.locked()


def test_shutdown_race_with_already_closed_descriptor_is_safe():
    class ClosedSocket:
        def shutdown(self, how):
            raise OSError("TEST_ONLY descriptor closed by its owner")
    connection = SimpleNamespace(sock=ClosedSocket())
    original = connection.sock
    _interrupt_socket(connection)
    assert connection.sock is original
