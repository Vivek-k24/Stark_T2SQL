"""Read-only live-status checks do not activate the connected SQL runtime."""

from contextlib import nullcontext
import http.client
import socket
import pytest

from stark_t2sql.ui.project_status import live_service_status


def test_live_services_show_listener_and_model_health(monkeypatch):
    monkeypatch.setenv("STARK_PG_PORT", "5433")
    monkeypatch.setenv("STARK_LLAMACPP_PORT", "8081")
    touched = []

    def connect(address, *, timeout):
        touched.append(("postgres", address, timeout))
        return nullcontext(object())

    class Response:
        status = 200

        def read(self, length):
            assert length == 256
            return b'{"status":"ok"}'

    class Connection:
        def __init__(self, host, port, *, timeout):
            touched.append(("model", (host, port), timeout))

        def request(self, method, path, *, headers):
            assert (method, path) == ("GET", "/health")
            assert headers["Connection"] == "close"

        def getresponse(self):
            return Response()

        def close(self):
            touched.append(("close",))

    monkeypatch.setattr(socket, "create_connection", connect)
    monkeypatch.setattr(http.client, "HTTPConnection", Connection)
    assert live_service_status() == {
        "PostgreSQL listener": "LISTENING — authentication not checked",
        "SQLCoder model": "ONLINE",
    }
    assert len(touched) == 3


def test_live_services_offline_fail_closed(monkeypatch):
    def unavailable(*args, **kwargs):
        raise ConnectionRefusedError("offline")

    monkeypatch.setattr(socket, "create_connection", unavailable)
    monkeypatch.setattr(http.client, "HTTPConnection", unavailable)
    assert live_service_status() == {
        "PostgreSQL listener": "OFFLINE",
        "SQLCoder model": "OFFLINE",
    }


def test_live_services_reject_unapproved_destination(monkeypatch):
    monkeypatch.setenv("STARK_PG_HOST", "example.com")
    monkeypatch.setenv("STARK_LLAMACPP_HOST", "example.com")
    monkeypatch.setenv("STARK_PG_PORT", "5433")
    monkeypatch.setenv("STARK_LLAMACPP_PORT", "8081")

    def should_not_connect(*args, **kwargs):
        raise AssertionError("Unexpected connection")

    monkeypatch.setattr(socket, "create_connection", should_not_connect)
    monkeypatch.setattr(http.client, "HTTPConnection", should_not_connect)
    assert live_service_status() == {
        "PostgreSQL listener": "NOT CONFIGURED",
        "SQLCoder model": "NOT CONFIGURED",
    }


def test_live_services_reject_invalid_port(monkeypatch):
    monkeypatch.setenv("STARK_PG_PORT", "not-a-port")
    monkeypatch.setenv("STARK_LLAMACPP_PORT", "0")
    assert live_service_status() == {
        "PostgreSQL listener": "NOT CONFIGURED",
        "SQLCoder model": "NOT CONFIGURED",
    }


@pytest.mark.parametrize("timeout", (0, -1, 2.1, float("nan"), float("inf"), True, "0.4"))
def test_invalid_sensor_deadline_is_rejected_before_network(monkeypatch, timeout):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid deadlines must not initiate a network operation")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(http.client, "HTTPConnection", forbidden)
    with pytest.raises(ValueError):
        live_service_status(timeout_seconds=timeout)


@pytest.mark.parametrize("status,expected", ((503, "LOADING"), (401, "OFFLINE")))
def test_model_loading_and_rejected_health_are_distinct(monkeypatch, status, expected):
    monkeypatch.setenv("STARK_PG_HOST", "127.0.0.1")
    monkeypatch.setenv("STARK_LLAMACPP_HOST", "127.0.0.1")
    monkeypatch.setenv("STARK_PG_PORT", "5433")
    monkeypatch.setenv("STARK_LLAMACPP_PORT", "8081")
    monkeypatch.setattr(socket, "create_connection", lambda *args, **kwargs: nullcontext(object()))
    calls = []

    class Response:
        def __init__(self): self.status = status
        def read(self, bound): assert bound == 256

    class Connection:
        def __init__(self, host, port, *, timeout):
            assert (host, port, timeout) == ("127.0.0.1", 8081, 0.4)
        def request(self, method, path, *, headers): calls.append((method, path))
        def getresponse(self): return Response()
        def close(self): calls.append("closed")

    monkeypatch.setattr(http.client, "HTTPConnection", Connection)
    assert live_service_status()["SQLCoder model"] == expected
    assert calls == [("GET", "/health"), "closed"]


def test_stalled_sensors_fail_closed_and_close_http_without_launching_services(monkeypatch):
    import subprocess
    monkeypatch.setenv("STARK_PG_HOST", "127.0.0.1")
    monkeypatch.setenv("STARK_LLAMACPP_HOST", "127.0.0.1")
    monkeypatch.setenv("STARK_PG_PORT", "5433")
    monkeypatch.setenv("STARK_LLAMACPP_PORT", "8081")
    calls = []

    def stalled(address, *, timeout):
        assert address == ("127.0.0.1", 5433) and timeout == 0.4
        raise TimeoutError("sensor deadline")

    class Connection:
        def __init__(self, host, port, *, timeout):
            assert (host, port, timeout) == ("127.0.0.1", 8081, 0.4)
        def request(self, *args, **kwargs): raise TimeoutError("sensor deadline")
        def close(self): calls.append("closed")

    monkeypatch.setattr(socket, "create_connection", stalled)
    monkeypatch.setattr(http.client, "HTTPConnection", Connection)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("Health cannot start a service"))
    assert live_service_status() == {"PostgreSQL listener": "OFFLINE", "SQLCoder model": "OFFLINE"}
    assert calls == ["closed"]
