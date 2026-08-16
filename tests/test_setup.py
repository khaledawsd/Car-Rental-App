"""First-run setup: the only route that creates an administrator from the web."""

import app as appmod

GOOD_PASSWORD = "FirstAdminPass1!"


def test_everything_redirects_to_setup_when_there_is_no_admin(flask_app):
    client = flask_app.test_client()
    for path in ("/", "/login", "/register", "/dashboard", "/manage_users"):
        response = client.get(path)
        assert response.status_code == 302, path
        assert response.headers["Location"].endswith("/setup"), path


def test_setup_page_is_reachable_when_there_is_no_admin(flask_app):
    response = flask_app.test_client().get("/setup")
    assert response.status_code == 200
    assert b"no administrator yet" in response.data


def test_creating_the_first_admin_signs_you_in(flask_app):
    client = flask_app.test_client()
    response = client.post(
        "/setup",
        data={
            "username": "owner",
            "password": GOOD_PASSWORD,
            "confirm_password": GOOD_PASSWORD,
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Welcome, owner" in response.data

    with flask_app.app_context():
        user = appmod.db.session.scalar(
            appmod.db.select(appmod.User).filter_by(username="owner")
        )
        assert user.role == appmod.ROLE_ADMIN
        assert user.approved is True


def test_setup_disappears_once_an_admin_exists(admin_id, flask_app):
    client = flask_app.test_client()
    assert client.get("/setup").status_code == 404
    response = client.post(
        "/setup",
        data={
            "username": "second",
            "password": GOOD_PASSWORD,
            "confirm_password": GOOD_PASSWORD,
        },
    )
    assert response.status_code == 404
    with flask_app.app_context():
        assert appmod.db.session.scalar(
            appmod.db.select(appmod.User).filter_by(username="second")
        ) is None


def test_admin_password_must_be_at_least_twelve_characters(flask_app):
    client = flask_app.test_client()
    response = client.post(
        "/setup",
        data={"username": "owner", "password": "Short1!x", "confirm_password": "Short1!x"},
    )
    assert b"at least 12 characters" in response.data
    with flask_app.app_context():
        assert appmod.db.session.scalar(appmod.db.select(appmod.User)) is None


def test_login_works_normally_after_setup(flask_app):
    client = flask_app.test_client()
    client.post(
        "/setup",
        data={
            "username": "owner",
            "password": GOOD_PASSWORD,
            "confirm_password": GOOD_PASSWORD,
        },
    )
    client.get("/logout")
    response = client.post(
        "/login", data={"username": "owner", "password": GOOD_PASSWORD}
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard")
