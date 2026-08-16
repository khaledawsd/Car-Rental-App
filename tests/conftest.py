"""Shared fixtures.

The environment must be configured before `app` is imported, because the module
builds its Flask instance and reads config at import time. Wrapping that in an
application factory is the next refactor; until then, this is the seam.
"""

import os
import pathlib
import sys
import tempfile
from datetime import datetime, timedelta

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TMP = tempfile.mkdtemp(prefix="carrental-tests-")
os.environ["SECRET_KEY"] = "testing-only-not-a-real-secret-key"
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(_TMP) / "test.db").as_posix()
os.environ["FLASK_DEBUG"] = "0"
os.environ["AUTO_CREATE_DB"] = "1"
os.environ.pop("SERVER_SOFTWARE", None)

import app as appmod  # noqa: E402

ADMIN_PW = "AdminPassword1!"
CUSTOMER_PW = "CustomerPass1!"

DT_FORMAT = "%Y-%m-%dT%H:%M"


def in_days(days, hour=10, minute=0):
    """A booking datetime relative to now, as the form expects it.

    These were hardcoded 2030 dates. Now that a pick-up in the past is
    rejected, hardcoding a year would quietly turn the whole rental suite red
    the moment that year arrives.
    """
    when = (datetime.now() + timedelta(days=days)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    return when.strftime(DT_FORMAT)


def minutes_from_now(minutes):
    return (datetime.now() + timedelta(minutes=minutes)).strftime(DT_FORMAT)


@pytest.fixture(scope="session")
def flask_app():
    appmod.app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        RATELIMIT_ENABLED=False,
        # The real config turns this on outside debug; the test client will not
        # send a Secure cookie over http, so every login would silently fail.
        SESSION_COOKIE_SECURE=False,
    )
    appmod.limiter.enabled = False
    return appmod.app


@pytest.fixture(autouse=True)
def clean_db(flask_app):
    """Drop and rebuild the schema around every test, and clear cached state."""
    with flask_app.app_context():
        appmod.db.drop_all()
        appmod.db.create_all()
    appmod._admin_exists = False
    try:
        appmod.limiter.reset()
    except Exception:
        pass
    yield
    with flask_app.app_context():
        appmod.db.session.remove()


@pytest.fixture
def make_user(flask_app):
    """Create a user and return its id (detached instances are not reusable)."""

    def _make(username, password, role=appmod.ROLE_CUSTOMER, approved=True):
        with flask_app.app_context():
            user = appmod.User(
                username=username,
                password=appmod.bcrypt.generate_password_hash(password).decode("utf-8"),
                role=role,
                approved=approved,
            )
            appmod.db.session.add(user)
            appmod.db.session.commit()
            if role == appmod.ROLE_ADMIN:
                appmod._admin_exists = True
            return user.id

    return _make


@pytest.fixture
def make_car(flask_app):
    def _make(model="Civic", brand="Honda", price=50.0, available=True):
        with flask_app.app_context():
            car = appmod.Car(model=model, brand=brand, price_per_day=price, available=available)
            appmod.db.session.add(car)
            appmod.db.session.commit()
            return car.id

    return _make


@pytest.fixture
def login(flask_app):
    def _login(username, password):
        client = flask_app.test_client()
        client.post(
            "/login",
            data={"username": username, "password": password},
            follow_redirects=True,
        )
        return client

    return _login


@pytest.fixture
def admin_id(make_user):
    """An administrator. Depend on this to get past the first-run setup gate."""
    return make_user("admin", ADMIN_PW, role=appmod.ROLE_ADMIN)


@pytest.fixture
def customer_id(admin_id, make_user):
    return make_user("mallory", CUSTOMER_PW)


@pytest.fixture
def admin_client(admin_id, login):
    return login("admin", ADMIN_PW)


@pytest.fixture
def customer_client(customer_id, login):
    return login("mallory", CUSTOMER_PW)


@pytest.fixture
def anon_client(admin_id, flask_app):
    """Logged-out client, with setup already completed."""
    return flask_app.test_client()
