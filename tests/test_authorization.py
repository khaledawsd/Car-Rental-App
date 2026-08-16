"""The authorization matrix: every route, every role, expected outcome.

The original audit finding was that admin routes carried @login_required but no
role check, so any customer could approve accounts and delete the
administrator. These tests exist so that cannot return unnoticed.
"""

import pytest

import app as appmod

# Every endpoint must be classified. A new route that is not listed here fails
# test_every_route_is_classified, which forces the author to make a decision
# about who may reach it rather than defaulting to "everyone".
PUBLIC = {"login", "register", "setup", "logout", "static"}
AUTHENTICATED = {"dashboard", "rent", "profile"}
ADMIN_ONLY = {"manage_users", "manage_cars", "view_rentals", "approve_user", "delete_user"}

ADMIN_ROUTES = [
    ("GET", "/manage_users"),
    ("GET", "/manage_cars"),
    ("POST", "/manage_cars"),
    ("GET", "/view_rentals"),
    ("POST", "/approve_user/1"),
    ("POST", "/delete_user/1"),
]


def test_every_route_is_classified(flask_app):
    endpoints = {r.endpoint for r in flask_app.url_map.iter_rules()}
    unclassified = endpoints - PUBLIC - AUTHENTICATED - ADMIN_ONLY
    assert not unclassified, (
        f"Unclassified endpoints: {sorted(unclassified)}. Add each to PUBLIC, "
        "AUTHENTICATED or ADMIN_ONLY in this file and cover it with a test."
    )


@pytest.mark.parametrize("method,path", ADMIN_ROUTES)
def test_customer_is_forbidden_from_admin_routes(customer_client, method, path):
    response = customer_client.open(path, method=method)
    assert response.status_code == 403


@pytest.mark.parametrize("method,path", ADMIN_ROUTES)
def test_anonymous_is_redirected_to_login(anon_client, method, path):
    response = anon_client.open(path, method=method)
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


@pytest.mark.parametrize("path", ["/manage_users", "/manage_cars", "/view_rentals"])
def test_admin_is_allowed(admin_client, path):
    assert admin_client.get(path).status_code == 200


@pytest.mark.parametrize("path", ["/dashboard", "/rent", "/profile"])
def test_authenticated_routes_reject_anonymous(anon_client, path):
    response = anon_client.get(path)
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


@pytest.mark.parametrize("path", ["/dashboard", "/rent", "/profile"])
def test_authenticated_routes_allow_any_logged_in_user(customer_client, path):
    assert customer_client.get(path).status_code == 200


@pytest.mark.parametrize("path", ["/approve_user/1", "/delete_user/1"])
def test_state_changing_routes_reject_get(admin_client, path):
    """A GET route is reachable from <img src>, which is CSRF with no token."""
    assert admin_client.get(path).status_code == 405


def test_customer_cannot_escalate_by_approving_themselves(
    admin_id, make_user, login
):
    pending = make_user("pending", "PendingPass1!", approved=False)
    accomplice = make_user("accomplice", "Accomplice1!")
    client = login("accomplice", "Accomplice1!")

    assert client.post(f"/approve_user/{pending}").status_code == 403
    with appmod.app.app_context():
        assert appmod.db.session.get(appmod.User, pending).approved is False


def test_customer_cannot_delete_the_administrator(customer_client, admin_id):
    assert customer_client.post(f"/delete_user/{admin_id}").status_code == 403
    with appmod.app.app_context():
        assert appmod.db.session.get(appmod.User, admin_id) is not None


def test_customer_cannot_create_inventory(customer_client):
    response = customer_client.post(
        "/manage_cars", data={"model": "Pwned", "brand": "Evil", "price_per_day": "1"}
    )
    assert response.status_code == 403
    with appmod.app.app_context():
        assert appmod.db.session.scalar(
            appmod.db.select(appmod.Car).filter_by(model="Pwned")
        ) is None


def test_denied_access_is_logged(customer_client, caplog):
    """Privilege probing should leave a trail."""
    with caplog.at_level("WARNING"):
        customer_client.get("/manage_users")
    messages = [record.getMessage() for record in caplog.records]
    assert any("authz.denied" in m and "manage_users" in m for m in messages), messages
