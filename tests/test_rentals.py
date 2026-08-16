"""Booking rules, pricing, and the tamper vectors on the rent form."""

import pytest

import app as appmod
from conftest import in_days, minutes_from_now


def _rent(client, car_id, start, end):
    return client.post(
        "/rent",
        data={"car_id": car_id, "start_date": start, "end_date": end},
        follow_redirects=True,
    )


def test_a_valid_rental_is_priced_by_the_hour(customer_client, make_car):
    car = make_car(price=42.50)
    _rent(customer_client, car, in_days(30), in_days(32))
    with appmod.app.app_context():
        rental = appmod.db.session.scalar(
            appmod.db.select(appmod.Rental).filter_by(car_id=car)
        )
        assert rental is not None
        assert rental.total_price == pytest.approx(85.00)  # 2 days x 42.50


def test_end_before_start_is_rejected(customer_client, make_car):
    car = make_car()
    response = _rent(customer_client, car, in_days(35), in_days(30))
    assert b"must be after" in response.data
    with appmod.app.app_context():
        assert appmod.db.session.scalar(appmod.db.select(appmod.Rental)) is None


def test_minimum_duration_is_enforced_and_readable(customer_client, make_car):
    car = make_car()
    response = _rent(customer_client, car, in_days(30, 10), in_days(30, 11))
    assert b"minimum rental duration is 4 hours" in response.data
    assert b"4:00:00" not in response.data  # a raw timedelta repr
    with appmod.app.app_context():
        assert appmod.db.session.scalar(appmod.db.select(appmod.Rental)) is None


# A pick-up that has already passed cannot be honoured. The date picker greys
# past days out, but that is a convenience -- the rule has to hold server-side
# for anyone posting the form directly.
@pytest.mark.parametrize("start_days_ago", [1, 30, 365])
def test_a_pick_up_in_the_past_is_rejected(customer_client, make_car, start_days_ago):
    car = make_car()
    response = _rent(
        customer_client, car, in_days(-start_days_ago), in_days(-start_days_ago + 1)
    )
    assert b"Pick-up cannot be in the past" in response.data
    with appmod.app.app_context():
        assert appmod.db.session.scalar(appmod.db.select(appmod.Rental)) is None


def test_a_past_pick_up_leaves_the_car_available(customer_client, make_car):
    """The availability flag must not be flipped by a rejected booking."""
    car = make_car()
    _rent(customer_client, car, in_days(-2), in_days(-1))
    with appmod.app.app_context():
        assert appmod.db.session.get(appmod.Car, car).available is True


def test_a_pick_up_just_now_is_accepted(customer_client, make_car):
    """Within the grace window, so clock skew does not reject a fresh slot."""
    car = make_car()
    _rent(customer_client, car, minutes_from_now(-1), in_days(1))
    with appmod.app.app_context():
        assert appmod.db.session.scalar(appmod.db.select(appmod.Rental)) is not None


def test_a_pick_up_today_but_later_is_accepted(customer_client, make_car):
    car = make_car()
    _rent(customer_client, car, minutes_from_now(60), minutes_from_now(60 + 5 * 60))
    with appmod.app.app_context():
        assert appmod.db.session.scalar(appmod.db.select(appmod.Rental)) is not None


def test_unavailable_car_cannot_be_booked_by_tampering_the_hidden_field(
    customer_client, make_car
):
    """car_id arrives in a hidden input, so the client picks it."""
    car = make_car(available=False)
    response = _rent(customer_client, car, in_days(30), in_days(34))
    assert b"no longer available" in response.data
    with appmod.app.app_context():
        assert appmod.db.session.scalar(appmod.db.select(appmod.Rental)) is None


def test_unknown_car_id_does_not_crash(customer_client):
    response = _rent(customer_client, 999999, in_days(30), in_days(34))
    assert response.status_code == 200
    assert b"no longer available" in response.data


def test_empty_dates_do_not_raise(customer_client, make_car):
    """Previously bypassed validation and compared None <= None."""
    car = make_car()
    response = customer_client.post(
        "/rent", data={"car_id": car, "start_date": "", "end_date": ""}
    )
    assert response.status_code == 200


def test_renting_marks_the_car_unavailable(customer_client, make_car):
    car = make_car()
    _rent(customer_client, car, in_days(30), in_days(34))
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
    _rent(customer_client, first, in_days(30), in_days(31))    # 10.00
    _rent(customer_client, second, in_days(60), in_days(62))   # 40.00
    response = customer_client.get("/profile")
    assert b"50.0" in response.data
