"""Native llama.cpp protocol and watchdog regression contracts.

No model, SQL, database, network connection, or runtime service is started.
The compact fixture matches the fields observed from the local Windows CPU
llama-server on 127.0.0.1:8081; it does not assert unseen stop metadata.
"""

import socket

import pytest

from stark_t2sql.errors import ModelGenerationError
from stark_t2sql.inference.client import (
    _completion_termination,
    _interrupt_socket,
)


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
