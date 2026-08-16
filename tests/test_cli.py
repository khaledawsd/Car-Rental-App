"""Maintenance commands. These destroy data, so their guards are tested too."""

import app as appmod
from conftest import in_days


def run(flask_app, *args):
    return flask_app.test_cli_runner().invoke(args=list(args))


def test_clear_rentals_deletes_history_and_frees_cars(
    flask_app, customer_client, make_car
):
    car = make_car()
    customer_client.post(
        "/rent",
        data={"car_id": car, "start_date": in_days(30), "end_date": in_days(34)},
        follow_redirects=True,
    )
    with flask_app.app_context():
        assert appmod.db.session.get(appmod.Car, car).available is False

    result = run(flask_app, "clear-rentals", "--yes")
    assert result.exit_code == 0, result.output
    assert "Deleted 1 rental" in result.output

    with flask_app.app_context():
        assert appmod.db.session.scalar(appmod.db.select(appmod.Rental)) is None
        # The only way to un-stick a car while availability is a boolean.
        assert appmod.db.session.get(appmod.Car, car).available is True


def test_clear_rentals_without_yes_aborts_rather_than_deleting(
    flask_app, customer_client, make_car
):
    car = make_car()
    customer_client.post(
        "/rent",
        data={"car_id": car, "start_date": in_days(30), "end_date": in_days(34)},
        follow_redirects=True,
    )
    result = run(flask_app, "clear-rentals")  # no --yes, no tty to confirm on
    assert result.exit_code != 0
    with flask_app.app_context():
        assert appmod.db.session.scalar(appmod.db.select(appmod.Rental)) is not None


def test_clear_rentals_on_an_empty_database_is_harmless(flask_app):
    result = run(flask_app, "clear-rentals")
    assert result.exit_code == 0, result.output
    assert "No rentals to clear" in result.output


def test_seed_fleet_adds_cars(flask_app):
    result = run(flask_app, "seed-fleet")
    assert result.exit_code == 0, result.output
    with flask_app.app_context():
        cars = appmod.db.session.scalars(appmod.db.select(appmod.Car)).all()
        assert len(cars) == len(appmod.DEMO_FLEET)
        assert all(c.available for c in cars)
        assert all(c.price_per_day > 0 for c in cars)


def test_seed_fleet_is_idempotent(flask_app):
    run(flask_app, "seed-fleet")
    result = run(flask_app, "seed-fleet")
    assert "Added 0 car(s)" in result.output
    with flask_app.app_context():
        assert appmod.db.session.scalar(
            appmod.db.select(appmod.db.func.count(appmod.Car.id))
        ) == len(appmod.DEMO_FLEET)


def test_seed_fleet_names_fit_the_add_car_form(flask_app):
    """Anything seeded should also have been typeable into the UI."""
    for brand, model, _ in appmod.DEMO_FLEET:
        assert len(brand) <= 20, brand
        assert len(model) <= 20, model


def test_seed_fleet_replace_refuses_while_rentals_reference_cars(
    flask_app, customer_client, make_car
):
    """car_id is NOT NULL, so deleting the parent would raise instead."""
    car = make_car()
    customer_client.post(
        "/rent",
        data={"car_id": car, "start_date": in_days(30), "end_date": in_days(34)},
        follow_redirects=True,
    )
    result = run(flask_app, "seed-fleet", "--replace")
    assert result.exit_code != 0
    assert "clear-rentals" in result.output
    with flask_app.app_context():
        assert appmod.db.session.get(appmod.Car, car) is not None


def test_seed_fleet_replace_works_once_rentals_are_cleared(flask_app, make_car):
    make_car("Placeholder", "Unbranded", price=25.0)
    run(flask_app, "clear-rentals", "--yes")
    result = run(flask_app, "seed-fleet", "--replace")
    assert result.exit_code == 0, result.output
    with flask_app.app_context():
        assert appmod.db.session.scalar(
            appmod.db.select(appmod.Car).filter_by(model="Placeholder")
        ) is None
        assert appmod.db.session.scalar(
            appmod.db.select(appmod.Car).filter_by(model="Corolla")
        ) is not None


def test_reset_db_requires_confirmation(flask_app, admin_id):
    result = run(flask_app, "reset-db")
    assert result.exit_code != 0
    with flask_app.app_context():
        assert appmod.db.session.get(appmod.User, admin_id) is not None


def test_reset_db_wipes_everything_and_reopens_setup(flask_app, admin_id):
    result = run(flask_app, "reset-db", "--yes")
    assert result.exit_code == 0, result.output
    with flask_app.app_context():
        assert appmod.db.session.scalar(appmod.db.select(appmod.User)) is None
    assert appmod._admin_exists is False
    # With no administrator, the app must send visitors back to setup.
    response = flask_app.test_client().get("/login")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/setup")
