"""Read-only live-status checks do not activate the connected SQL runtime."""

from contextlib import nullcontext
import http.client
import socket

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
