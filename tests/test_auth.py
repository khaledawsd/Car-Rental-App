"""Login, registration, redirect safety, rate limiting and enumeration."""

import re

import pytest

import app as appmod
from conftest import ADMIN_PW, CUSTOMER_PW


def test_registration_creates_an_unapproved_customer(anon_client):
    anon_client.post(
        "/register",
        data={
            "username": "newbie",
            "password": "GoodPassword1!",
            "confirm_password": "GoodPassword1!",
        },
    )
    with appmod.app.app_context():
        user = appmod.db.session.scalar(
            appmod.db.select(appmod.User).filter_by(username="newbie")
        )
        assert user is not None
        assert user.approved is False
        assert user.role == appmod.ROLE_CUSTOMER
        assert user.password != "GoodPassword1!"


def test_unapproved_user_cannot_reach_the_dashboard(admin_id, make_user, login):
    make_user("pending", "PendingPass1!", approved=False)
    client = login("pending", "PendingPass1!")
    assert client.get("/dashboard").status_code == 302


def test_approved_user_can_log_in(customer_client):
    assert customer_client.get("/dashboard").status_code == 200


@pytest.mark.parametrize(
    "password",
    ["Ab1!", "nouppercase1!", "NOLOWERCASE1!", "NoDigitsHere!", "NoSpecial1"],
)
def test_weak_passwords_are_rejected_with_a_visible_message(anon_client, password):
    response = anon_client.post(
        "/register",
        data={"username": "weak", "password": password, "confirm_password": password},
    )
    assert b"field-errors" in response.data
    with appmod.app.app_context():
        assert appmod.db.session.scalar(
            appmod.db.select(appmod.User).filter_by(username="weak")
        ) is None


def test_mismatched_confirmation_is_rejected(anon_client):
    response = anon_client.post(
        "/register",
        data={
            "username": "mismatch",
            "password": "GoodPassword1!",
            "confirm_password": "OtherPassword1!",
        },
    )
    assert b"Passwords must match" in response.data


def test_duplicate_username_is_rejected(customer_id, anon_client):
    response = anon_client.post(
        "/register",
        data={
            "username": "mallory",
            "password": "GoodPassword1!",
            "confirm_password": "GoodPassword1!",
        },
    )
    assert b"already" in response.data or b"taken" in response.data


# CWE-601
@pytest.mark.parametrize(
    "target",
    [
        "https://evil.example.com/harvest",
        "//evil.example.com/harvest",
        "http://evil.example.com",
    ],
)
def test_offsite_next_is_ignored(customer_id, flask_app, target):
    client = flask_app.test_client()
    response = client.post(
        f"/login?next={target}", data={"username": "mallory", "password": CUSTOMER_PW}
    )
    assert "evil.example.com" not in response.headers["Location"]
    assert response.headers["Location"].endswith("/dashboard")


def test_same_origin_next_is_honoured(customer_id, flask_app):
    client = flask_app.test_client()
    response = client.post(
        "/login?next=/profile", data={"username": "mallory", "password": CUSTOMER_PW}
    )
    assert response.headers["Location"].endswith("/profile")


def test_unknown_and_unapproved_users_are_indistinguishable(
    admin_id, make_user, flask_app
):
    """A different message for a pending account confirms the username exists."""
    make_user("pending", "PendingPass1!", approved=False)
    client = flask_app.test_client()

    pending = client.post(
        "/login", data={"username": "pending", "password": "PendingPass1!"}
    ).data
    unknown = client.post(
        "/login", data={"username": "nosuchuser", "password": "PendingPass1!"}
    ).data

    # The form echoes the submitted username back; that is not a leak, so
    # normalise it before comparing.
    strip = lambda d: re.sub(rb'value="[^"]*"', b"", d)
    assert strip(pending) == strip(unknown)


def test_login_is_rate_limited(customer_id, flask_app):
    flask_app.config["RATELIMIT_ENABLED"] = True
    appmod.limiter.enabled = True
    try:
        client = flask_app.test_client()
        codes = [
            client.post(
                "/login", data={"username": "mallory", "password": "wrong"}
            ).status_code
            for _ in range(8)
        ]
        assert 429 in codes, f"never throttled: {codes}"
    finally:
        appmod.limiter.enabled = False
        flask_app.config["RATELIMIT_ENABLED"] = False


def test_csrf_token_is_required(customer_id, flask_app):
    flask_app.config["WTF_CSRF_ENABLED"] = True
    try:
        client = flask_app.test_client()
        page = client.get("/login").data.decode()
        token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page).group(1)

        assert client.post(
            "/login", data={"username": "mallory", "password": CUSTOMER_PW}
        ).status_code == 400
        assert client.post(
            "/login",
            data={"username": "mallory", "password": CUSTOMER_PW, "csrf_token": token},
        ).status_code == 302
    finally:
        flask_app.config["WTF_CSRF_ENABLED"] = False


def test_logout_clears_the_session(customer_client):
    customer_client.get("/logout")
    assert customer_client.get("/dashboard").status_code == 302
