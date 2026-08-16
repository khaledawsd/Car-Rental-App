"""Booking rules, pricing, and the tamper vectors on the rent form."""

import pytest

import app as appmod


def _rent(client, car_id, start, end):
    return client.post(
        "/rent",
        data={"car_id": car_id, "start_date": start, "end_date": end},
        follow_redirects=True,
    )


def test_a_valid_rental_is_priced_by_the_hour(customer_client, make_car):
    car = make_car(price=42.50)
    _rent(customer_client, car, "2030-06-01T10:00", "2030-06-03T10:00")
    with appmod.app.app_context():
        rental = appmod.db.session.scalar(
            appmod.db.select(appmod.Rental).filter_by(car_id=car)
        )
        assert rental is not None
        assert rental.total_price == pytest.approx(85.00)  # 2 days x 42.50


def test_end_before_start_is_rejected(customer_client, make_car):
    car = make_car()
    response = _rent(customer_client, car, "2030-06-05T10:00", "2030-06-01T10:00")
    assert b"must be after" in response.data
    with appmod.app.app_context():
        assert appmod.db.session.scalar(appmod.db.select(appmod.Rental)) is None


def test_minimum_duration_is_enforced_and_readable(customer_client, make_car):
    car = make_car()
    response = _rent(customer_client, car, "2030-06-01T10:00", "2030-06-01T11:00")
    assert b"minimum rental duration is 4 hours" in response.data
    assert b"4:00:00" not in response.data  # a raw timedelta repr
    with appmod.app.app_context():
        assert appmod.db.session.scalar(appmod.db.select(appmod.Rental)) is None


def test_unavailable_car_cannot_be_booked_by_tampering_the_hidden_field(
    customer_client, make_car
):
    """car_id arrives in a hidden input, so the client picks it."""
    car = make_car(available=False)
    response = _rent(customer_client, car, "2030-06-01T10:00", "2030-06-05T10:00")
    assert b"no longer available" in response.data
    with appmod.app.app_context():
        assert appmod.db.session.scalar(appmod.db.select(appmod.Rental)) is None


def test_unknown_car_id_does_not_crash(customer_client):
    response = _rent(customer_client, 999999, "2030-06-01T10:00", "2030-06-05T10:00")
    assert response.status_code == 200
    assert b"no longer available" in response.data


def test_empty_dates_do_not_raise(customer_client, make_car):
    """Previously bypassed validation and compared None <= None."""
    car = make_car()
    response = customer_client.post("/rent", data={"car_id": car, "start_date": "", "end_date": ""})
    assert response.status_code == 200


def test_renting_marks_the_car_unavailable(customer_client, make_car):
    car = make_car()
    _rent(customer_client, car, "2030-06-01T10:00", "2030-06-05T10:00")
    with appmod.app.app_context():
        assert appmod.db.session.get(appmod.Car, car).available is False


@pytest.mark.parametrize("price", ["-100", "-0.01"])
def test_negative_price_is_rejected(admin_client, price):
    admin_client.post(
        "/manage_cars", data={"model": "Neg", "brand": "T", "price_per_day": price}
    )
    with appmod.app.app_context():
        assert appmod.db.session.scalar(
            appmod.db.select(appmod.Car).filter_by(model="Neg")
        ) is None


def test_zero_price_is_rejected_with_a_range_message(admin_client):
    response = admin_client.post(
        "/manage_cars", data={"model": "Zero", "brand": "T", "price_per_day": "0"}
    )
    assert b"between 0.01" in response.data
    assert b"required" not in response.data.lower().split(b"field-errors")[-1][:200]


def test_valid_price_is_stored(admin_client):
    admin_client.post(
        "/manage_cars", data={"model": "Corolla", "brand": "Toyota", "price_per_day": "42.50"}
    )
    with appmod.app.app_context():
        car = appmod.db.session.scalar(
            appmod.db.select(appmod.Car).filter_by(model="Corolla")
        )
        assert car is not None and car.price_per_day == pytest.approx(42.50)


def test_profile_totals_the_user_spend(customer_client, make_car):
    first, second = make_car("A", price=10.0), make_car("B", price=20.0)
    _rent(customer_client, first, "2030-06-01T10:00", "2030-06-02T10:00")   # 10.00
    _rent(customer_client, second, "2030-07-01T10:00", "2030-07-03T10:00")  # 40.00
    response = customer_client.get("/profile")
    assert b"50.0" in response.data
