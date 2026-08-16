"""Administrator actions on users."""

import app as appmod
from conftest import in_days


def test_admin_can_approve_a_pending_user(admin_client, make_user, login):
    pending = make_user("pending", "PendingPass1!", approved=False)
    admin_client.post(f"/approve_user/{pending}", follow_redirects=True)

    with appmod.app.app_context():
        assert appmod.db.session.get(appmod.User, pending).approved is True
    assert login("pending", "PendingPass1!").get("/dashboard").status_code == 200


def test_admin_can_delete_a_user_without_rentals(admin_client, customer_id):
    admin_client.post(f"/delete_user/{customer_id}", follow_redirects=True)
    with appmod.app.app_context():
        assert appmod.db.session.get(appmod.User, customer_id) is None


def test_deleting_a_user_with_rentals_is_refused_not_a_500(
    admin_client, customer_client, customer_id, make_car
):
    """Used to null a NOT NULL foreign key and raise IntegrityError."""
    car = make_car()
    customer_client.post(
        "/rent",
        data={"car_id": car, "start_date": in_days(30), "end_date": in_days(34)},
        follow_redirects=True,
    )

    response = admin_client.post(f"/delete_user/{customer_id}", follow_redirects=True)
    assert response.status_code == 200
    assert b"cannot be deleted" in response.data
    with appmod.app.app_context():
        assert appmod.db.session.get(appmod.User, customer_id) is not None


def test_admin_cannot_delete_themselves(admin_client, admin_id):
    """The last administrator must survive, or setup would reopen."""
    response = admin_client.post(f"/delete_user/{admin_id}", follow_redirects=True)
    assert b"cannot delete your own account" in response.data
    with appmod.app.app_context():
        assert appmod.db.session.get(appmod.User, admin_id) is not None


def test_deleting_a_missing_user_is_a_404(admin_client):
    assert admin_client.post("/delete_user/999999").status_code == 404


def test_approving_a_missing_user_is_a_404(admin_client):
    assert admin_client.post("/approve_user/999999").status_code == 404


def test_manage_users_renders_actions_as_post_forms(admin_client, make_user):
    make_user("pending", "PendingPass1!", approved=False)
    html = admin_client.get("/manage_users").data.decode()
    assert 'method="POST"' in html
    assert '<a href="/delete_user' not in html
    assert "This is you" in html  # self-delete suppressed


def test_view_rentals_lists_every_rental(admin_client, customer_client, make_car):
    car = make_car("Civic", "Honda")
    customer_client.post(
        "/rent",
        data={"car_id": car, "start_date": in_days(30), "end_date": in_days(34)},
        follow_redirects=True,
    )
    html = admin_client.get("/view_rentals").data.decode()
    assert "Civic" in html and "mallory" in html
