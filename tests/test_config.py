"""Configuration and startup guards.

These build throwaway Flask objects through load_config rather than touching the
module-level app, so they can exercise environments the test session is not
running under.
"""

import os
from datetime import timedelta

import pytest
from flask import Flask

import app as appmod


@pytest.fixture
def clean_env(monkeypatch):
    for name in ("SECRET_KEY", "FLASK_DEBUG", "SERVER_SOFTWARE", "SESSION_COOKIE_SECURE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(appmod, "EPHEMERAL_SECRET_KEY", False)
    yield monkeypatch


def _configured(**env):
    fresh = Flask(__name__)
    for key, value in env.items():
        os.environ[key] = value
    appmod.load_config(fresh)
    return fresh


def test_supplied_secret_key_is_used(clean_env):
    app = _configured(SECRET_KEY="a-real-key-from-the-environment")
    assert app.config["SECRET_KEY"] == "a-real-key-from-the-environment"
    assert appmod.EPHEMERAL_SECRET_KEY is False


def test_missing_key_is_generated_for_local_runs(clean_env):
    app = _configured()
    assert len(app.config["SECRET_KEY"]) >= 40
    assert appmod.EPHEMERAL_SECRET_KEY is True


def test_generated_keys_differ_between_processes(clean_env):
    first = _configured().config["SECRET_KEY"]
    os.environ.pop("SECRET_KEY", None)
    second = _configured().config["SECRET_KEY"]
    assert first != second


def test_missing_key_is_fatal_under_a_wsgi_server(clean_env):
    """Each gunicorn worker would generate a different key."""
    clean_env.setenv("SERVER_SOFTWARE", "gunicorn/23.0.0")
    with pytest.raises(RuntimeError, match="SECRET_KEY must be set"):
        appmod.load_config(Flask(__name__))


@pytest.mark.parametrize("server", ["gunicorn/26.0.0", "uWSGI/2.0", "waitress", "mod_wsgi/5.0"])
def test_wsgi_server_names_are_matched(server):
    assert appmod._is_wsgi_server(server) is True


@pytest.mark.parametrize("software", ["", "Werkzeug/3.1.8"])
def test_the_development_server_is_not_matched(software):
    assert appmod._is_wsgi_server(software) is False


def test_a_bare_environment_is_not_mistaken_for_a_server(clean_env):
    assert appmod._served_by_wsgi_server() is False


@pytest.mark.parametrize(
    "argv0",
    [
        r"E:\proj\venv\Scripts\waitress-serve",
        "/usr/local/bin/waitress-serve",
        "/usr/local/bin/gunicorn",
        # `python -m waitress` reports the package's __main__.py
        r"E:\proj\venv\Lib\site-packages\waitress\__main__.py",
        "/usr/lib/python3.13/site-packages/gunicorn/__main__.py",
    ],
)
def test_server_entry_points_are_detected(monkeypatch, argv0):
    monkeypatch.setattr(appmod.sys, "argv", [argv0])
    assert appmod._entry_point_is_wsgi_server() is True


@pytest.mark.parametrize(
    "argv0",
    [
        "app.py",
        r"E:\Projects\Car-Rental-App\app.py",
        "/usr/local/bin/flask",
        "/usr/local/bin/pytest",
        # A project directory named after a server must not trigger it.
        r"E:\Projects\gunicorn-demo\app.py",
        "/home/me/waitress-experiments/app.py",
        "",
    ],
)
def test_ordinary_entry_points_are_not_detected(monkeypatch, argv0):
    monkeypatch.setattr(appmod.sys, "argv", [argv0])
    assert appmod._entry_point_is_wsgi_server() is False


def test_launching_via_a_server_entry_point_is_fatal_without_a_key(clean_env, monkeypatch):
    """waitress and uWSGI never export SERVER_SOFTWARE, so without this the
    failure would only surface on the first request instead of at boot."""
    monkeypatch.setattr(appmod.sys, "argv", ["/usr/local/bin/waitress-serve"])
    with pytest.raises(RuntimeError, match="SECRET_KEY must be set"):
        appmod.load_config(Flask(__name__))


# Only gunicorn exports SERVER_SOFTWARE into os.environ, so the startup check
# above cannot see the others. They set it in the per-request WSGI environ,
# which is what the request-time guard below reads.
@pytest.mark.parametrize("server", ["waitress", "uWSGI/2.0", "gunicorn/26.0.0", "mod_wsgi/5.0"])
def test_generated_key_is_refused_by_a_real_server_at_request_time(
    admin_id, flask_app, monkeypatch, server
):
    monkeypatch.setattr(appmod, "EPHEMERAL_SECRET_KEY", True)
    response = flask_app.test_client().get(
        "/login", environ_overrides={"SERVER_SOFTWARE": server}
    )
    assert response.status_code == 503
    assert b"Refusing to serve" in response.data


def test_generated_key_still_serves_on_the_development_server(
    admin_id, flask_app, monkeypatch
):
    """The generated key exists precisely for this case."""
    monkeypatch.setattr(appmod, "EPHEMERAL_SECRET_KEY", True)
    response = flask_app.test_client().get(
        "/login", environ_overrides={"SERVER_SOFTWARE": "Werkzeug/3.1.8"}
    )
    assert response.status_code == 200


def test_a_real_key_serves_under_any_server(admin_id, flask_app, monkeypatch):
    monkeypatch.setattr(appmod, "EPHEMERAL_SECRET_KEY", False)
    response = flask_app.test_client().get(
        "/login", environ_overrides={"SERVER_SOFTWARE": "gunicorn/26.0.0"}
    )
    assert response.status_code == 200


def test_the_published_placeholder_key_is_gone():
    source = open(
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.py"),
        encoding="utf-8",
    ).read()
    code = "\n".join(
        line.split("#")[0] for line in source.splitlines() if not line.strip().startswith("#")
    )
    assert "your_secret_key" not in code
    assert "admin123" not in code
    assert "debug=True" not in code


def test_cookies_are_hardened_outside_debug(clean_env):
    app = _configured(SECRET_KEY="k" * 40, FLASK_DEBUG="0")
    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert app.config["PERMANENT_SESSION_LIFETIME"] == timedelta(hours=12)


def test_secure_cookies_relax_in_debug_so_localhost_works(clean_env):
    """A Secure cookie is never sent over the plain-http dev server."""
    app = _configured(SECRET_KEY="k" * 40, FLASK_DEBUG="1")
    assert app.config["SESSION_COOKIE_SECURE"] is False


def test_secure_cookies_relax_when_the_key_was_generated(clean_env):
    """A fresh clone runs on http://127.0.0.1 with no FLASK_DEBUG set. Leaving
    Secure on there would set a cookie the client never sends back, so login
    would appear to succeed and then immediately fail."""
    app = _configured()
    assert appmod.EPHEMERAL_SECRET_KEY is True
    assert app.config["SESSION_COOKIE_SECURE"] is False


def test_a_real_deployment_still_gets_secure_cookies(clean_env):
    app = _configured(SECRET_KEY="k" * 40)
    assert app.config["SESSION_COOKIE_SECURE"] is True


def test_secure_cookies_can_be_forced_back_on_in_debug(clean_env):
    app = _configured(SECRET_KEY="k" * 40, FLASK_DEBUG="1", SESSION_COOKIE_SECURE="1")
    assert app.config["SESSION_COOKIE_SECURE"] is True
