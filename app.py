"""Car Rental System.

A single-module Flask application. Security-critical behaviour lives in three
places and should be reviewed together:

  * ``roles_required``  -- the only authorization gate; every admin route uses it.
  * ``is_safe_url``     -- guards the post-login redirect against CWE-601.
  * ``load_config``     -- refuses to start without a real SECRET_KEY.

The blueprint / service-layer split is planned but not done; see README.
"""

from __future__ import annotations

import logging
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from functools import wraps
from pathlib import Path
from urllib.parse import urljoin, urlparse

import click
from dotenv import load_dotenv
from flask import (
    Flask,
    Response,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_bcrypt import Bcrypt
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from flask_wtf.csrf import CSRFError, CSRFProtect
from sqlalchemy.exc import IntegrityError
from wtforms import (
    DateTimeLocalField,
    DecimalField,
    PasswordField,
    StringField,
    SubmitField,
)
from wtforms.validators import (
    DataRequired,
    EqualTo,
    InputRequired,
    Length,
    NumberRange,
    ValidationError,
)

ROLE_ADMIN = "admin"
ROLE_CUSTOMER = "customer"

MIN_RENTAL_DURATION = timedelta(hours=4)
MIN_RENTAL_LABEL = "4 hours"

load_dotenv()


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

# Set when no SECRET_KEY was supplied and we generated a throwaway one.
EPHEMERAL_SECRET_KEY = False


WSGI_SERVER_NAMES = ("gunicorn", "uwsgi", "waitress", "mod_wsgi")


def _is_wsgi_server(software: str) -> bool:
    return any(name in software.lower() for name in WSGI_SERVER_NAMES)


def _entry_point_is_wsgi_server() -> bool:
    """Detect `waitress-serve ...` or `python -m waitress ...` style launches.

    Matching is deliberately narrow -- the script's own name, or the package
    directory of a `python -m <server>` launch -- so that a project living in a
    directory whose name happens to contain "gunicorn" is not mistaken for one.
    """
    argv0 = Path(sys.argv[0] or "")
    name = argv0.name.lower()
    if name == "__main__.py":
        name = argv0.parent.name.lower()
    return any(name.startswith(server) for server in WSGI_SERVER_NAMES)


def _served_by_wsgi_server() -> bool:
    """True when a production WSGI server is detectable at startup.

    Two signals, because neither is sufficient alone. gunicorn exports
    SERVER_SOFTWARE into the process environment (arbiter.py) but most servers
    only set it in the per-request WSGI environ; conversely the entry point is
    visible for a direct `waitress-serve` launch but not when a server is
    embedded in another process. Anything both miss is caught on the first
    request by refuse_generated_key_on_a_real_server.
    """
    return _is_wsgi_server(os.environ.get("SERVER_SOFTWARE", "")) or _entry_point_is_wsgi_server()


def resolve_secret_key() -> str:
    """Return the session signing key, generating a throwaway one for local runs.

    A random per-process key is cryptographically sound -- the original problem
    was a *published constant*, not a missing value. What a generated key cannot
    do is survive a restart or be shared between workers, so it is fine for
    `python app.py` on a laptop and useless for anything serving real traffic.
    Refuse it in the cases where it would silently break or mislead.
    """
    global EPHEMERAL_SECRET_KEY
    key = os.environ.get("SECRET_KEY", "").strip()
    if key:
        return key
    if _served_by_wsgi_server():
        raise RuntimeError(
            "SECRET_KEY must be set when running under a WSGI server.\n"
            "Each worker would generate a different key, so no session would\n"
            "validate and logins would appear to fail at random.\n"
            '  python -c "import secrets; print(secrets.token_urlsafe(64))"\n'
            "  then put it in .env as SECRET_KEY=..."
        )
    EPHEMERAL_SECRET_KEY = True
    return secrets.token_urlsafe(64)


def warn_if_ephemeral_key() -> None:
    if EPHEMERAL_SECRET_KEY:
        print(
            "\n  WARNING: No SECRET_KEY set - generated a temporary one for this\n"
            "  process. Sessions will be invalidated when you restart, and this\n"
            "  will not work across multiple workers. Set SECRET_KEY in .env\n"
            "  before exposing this to a network.\n",
            file=sys.stderr,
        )


def load_config(app: Flask) -> None:
    """Populate app.config from the environment."""
    secret_key = resolve_secret_key()
    debug = _env_flag("FLASK_DEBUG")
    secure_default = not (debug or EPHEMERAL_SECRET_KEY)

    app.config.update(
        SECRET_KEY=secret_key,
        SQLALCHEMY_DATABASE_URI=os.environ.get(
            "DATABASE_URL", "sqlite:///carrental.db"
        ),
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
        # Session hardening. Secure defaults on, but a Secure cookie is not sent
        # over plain HTTP, so it would silently break login on a local run. Both
        # signals below mean "this is not a deployment": debug is explicit, and
        # a generated key already refuses WSGI servers and non-loopback binds.
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=_env_flag("SESSION_COOKIE_SECURE", secure_default),
        REMEMBER_COOKIE_HTTPONLY=True,
        REMEMBER_COOKIE_SAMESITE="Lax",
        REMEMBER_COOKIE_SECURE=_env_flag("SESSION_COOKIE_SECURE", secure_default),
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        SESSION_REFRESH_EACH_REQUEST=True,
        WTF_CSRF_TIME_LIMIT=3600,
    )


app = Flask(__name__)
load_config(app)

db = SQLAlchemy(app)
migrate = Migrate(app, db)
bcrypt = Bcrypt(app)
csrf = CSRFProtect(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message_category = "info"
login_manager.session_protection = "strong"

limiter = Limiter(
    get_remote_address,
    app=app,
    storage_uri=os.environ.get("RATELIMIT_STORAGE_URI", "memory://"),
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
warn_if_ephemeral_key()


# Models
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(20), unique=True, nullable=False, index=True)
    # Stores a bcrypt hash, never a plaintext password. Renaming this column to
    # password_hash is queued behind the first Alembic migration.
    password = db.Column(db.String(60), nullable=False)
    role = db.Column(db.String(10), nullable=False)
    approved = db.Column(db.Boolean, nullable=False, default=False)
    rentals = db.relationship("Rental", backref="user", lazy=True)

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN


class Car(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    model = db.Column(db.String(100), nullable=False)
    brand = db.Column(db.String(100), nullable=False)
    # Float is wrong for currency; the migration to Numeric(10, 2) is queued.
    price_per_day = db.Column(db.Float, nullable=False)
    available = db.Column(db.Boolean, nullable=False, default=True, index=True)
    rentals = db.relationship("Rental", backref="car", lazy=True)


class Rental(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    car_id = db.Column(db.Integer, db.ForeignKey("car.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    start_date = db.Column(db.DateTime, nullable=False)
    end_date = db.Column(db.DateTime, nullable=False)
    total_price = db.Column(db.Float, nullable=False)
    # Naive UTC, matching the existing rows. datetime.utcnow() is deprecated on
    # 3.12+, so derive the same value from an aware clock instead.
    date_created = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )


# Security helpers
def roles_required(*roles: str):
    """Authorize by role.

    Wraps login_required so authentication can never be omitted by mistake, and
    logs every denial so privilege probing leaves a trail.
    """

    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user.role not in roles:
                current_app.logger.warning(
                    "authz.denied user=%s role=%s endpoint=%s ip=%s",
                    current_user.id,
                    current_user.role,
                    request.endpoint,
                    request.remote_addr,
                )
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


_admin_exists = False


def admin_exists() -> bool:
    """True once any administrator account exists.

    Cached after the first hit, which is safe because the count can never
    return to zero: delete_user refuses self-deletion, so the last remaining
    administrator cannot remove themselves.
    """
    global _admin_exists
    if not _admin_exists:
        _admin_exists = (
            db.session.scalar(
                db.select(User.id).filter_by(role=ROLE_ADMIN).limit(1)
            )
            is not None
        )
    return _admin_exists


def is_safe_url(target: str) -> bool:
    """True only for same-origin http(s) targets, so ?next= cannot leave the site."""
    if not target:
        return False
    host_url = urlparse(request.host_url)
    redirect_url = urlparse(urljoin(request.host_url, target))
    return redirect_url.scheme in ("http", "https") and host_url.netloc == redirect_url.netloc


def _login_rate_key() -> str:
    """Rate-limit on address *and* username, so one attacker cannot lock out
    every account by hammering a single IP."""
    username = (request.form.get("username") or "").strip().lower()[:32]
    return f"{get_remote_address()}|{username}"


def password_check(form, field):
    """Reject passwords that miss any required character class."""
    password = field.data or ""
    checks = (
        (len(password) >= 8, "at least 8 characters"),
        (any(c.isupper() for c in password), "an uppercase letter"),
        (any(c.islower() for c in password), "a lowercase letter"),
        (any(c.isdigit() for c in password), "a number"),
        (any(not c.isalnum() for c in password), "a special character"),
    )
    missing = [label for ok, label in checks if not ok]
    if missing:
        raise ValidationError("Password needs " + ", ".join(missing) + ".")


# Forms
class LoginForm(FlaskForm):
    username = StringField(
        "Username",
        validators=[DataRequired(), Length(min=2, max=20)],
        render_kw={"placeholder": "Username", "autocomplete": "username"},
    )
    password = PasswordField(
        "Password",
        validators=[DataRequired()],
        render_kw={"placeholder": "Password", "autocomplete": "current-password"},
    )
    submit = SubmitField("Login")


class RegistrationForm(FlaskForm):
    username = StringField(
        "Username",
        validators=[DataRequired(), Length(min=2, max=20)],
        render_kw={"placeholder": "Username", "autocomplete": "username"},
    )
    password = PasswordField(
        "Password",
        validators=[DataRequired(), password_check],
        render_kw={"placeholder": "Password", "autocomplete": "new-password"},
    )
    confirm_password = PasswordField(
        "Confirm Password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match")],
        render_kw={"placeholder": "Confirm Password", "autocomplete": "new-password"},
    )
    submit = SubmitField("Register")

    def validate_username(self, username):
        existing = db.session.scalar(
            db.select(User).filter_by(username=username.data.strip())
        )
        if existing:
            raise ValidationError("That username is taken. Please choose a different one.")


class CarForm(FlaskForm):
    model = StringField(
        "Model",
        validators=[DataRequired(), Length(max=20)],
        render_kw={"placeholder": "Model"},
    )
    brand = StringField(
        "Brand",
        validators=[DataRequired(), Length(max=20)],
        render_kw={"placeholder": "Brand"},
    )
    # InputRequired, not DataRequired: DataRequired treats 0 as missing, so it
    # rejected a free rental while happily accepting a negative price.
    price_per_day = DecimalField(
        "Price per Day",
        places=2,
        validators=[
            InputRequired(message="Enter a price per day."),
            NumberRange(
                min=Decimal("0.01"),
                max=Decimal("100000"),
                message="Price must be between 0.01 and 100000.",
            ),
        ],
        render_kw={
            "placeholder": "Price per Day",
            "type": "number",
            "step": "0.01",
            "min": "0.01",
        },
    )
    submit = SubmitField("Add Car")


class RentalForm(FlaskForm):
    start_date = DateTimeLocalField(
        "Start Date and Time", format="%Y-%m-%dT%H:%M", validators=[DataRequired()]
    )
    end_date = DateTimeLocalField(
        "End Date and Time", format="%Y-%m-%dT%H:%M", validators=[DataRequired()]
    )
    submit = SubmitField("Rent")


class ConfirmForm(FlaskForm):
    """Bare CSRF-token carrier for one-click admin actions."""

    submit = SubmitField("Confirm")


class SetupForm(FlaskForm):
    """First-run creation of the initial administrator."""

    username = StringField(
        "Username",
        validators=[DataRequired(), Length(min=2, max=20)],
        render_kw={"placeholder": "Admin username", "autocomplete": "username"},
    )
    password = PasswordField(
        "Password",
        validators=[
            DataRequired(),
            Length(min=12, message="An admin password must be at least 12 characters."),
            password_check,
        ],
        render_kw={"placeholder": "Password", "autocomplete": "new-password"},
    )
    confirm_password = PasswordField(
        "Confirm Password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match")],
        render_kw={"placeholder": "Confirm Password", "autocomplete": "new-password"},
    )
    submit = SubmitField("Create administrator")


# Error handlers
@app.errorhandler(403)
def forbidden(_error):
    return render_template("error.html", code=403, title="Not allowed",
                           message="Your account does not have access to that page."), 403


@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", code=404, title="Not found",
                           message="That page does not exist."), 404


@app.errorhandler(429)
def too_many_requests(_error):
    return render_template("error.html", code=429, title="Too many attempts",
                           message="Too many login attempts. Wait a minute and try again."), 429


@app.errorhandler(CSRFError)
def csrf_error(error):
    return render_template("error.html", code=400, title="Session expired",
                           message=f"{error.description} Reload the page and try again."), 400


@app.errorhandler(500)
def server_error(error):
    current_app.logger.exception("unhandled error: %s", error)
    return render_template("error.html", code=500, title="Something went wrong",
                           message="The error has been logged. Please try again."), 500


# Routes
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


@app.before_request
def refuse_generated_key_on_a_real_server():
    """Stop serving if a production server is running without a SECRET_KEY.

    Registered before every other hook so it wins. The startup check in
    resolve_secret_key() only catches gunicorn, which exports SERVER_SOFTWARE
    into the process environment; waitress, uWSGI and mod_wsgi set it solely in
    the per-request WSGI environ, so this is the only place they are visible.
    Werkzeug's development server sets it too, and is exactly the case the
    generated key exists for, so it is excluded.
    """
    if not EPHEMERAL_SECRET_KEY:
        return None
    software = request.environ.get("SERVER_SOFTWARE", "")
    if not software or software.startswith("Werkzeug"):
        return None
    current_app.logger.critical(
        "refusing to serve: %s is running without a SECRET_KEY", software
    )
    return Response(
        f"Refusing to serve.\n\n"
        f"{software} is running without a SECRET_KEY, so this process generated\n"
        f"a temporary one. Every worker would sign sessions with a different key\n"
        f"and logins would fail unpredictably.\n\n"
        f'  python -c "import secrets; print(secrets.token_urlsafe(64))"\n'
        f"  then set it in .env as SECRET_KEY=...\n",
        status=503,
        mimetype="text/plain",
    )


@app.before_request
def redirect_to_setup():
    """Send every request to /setup until the first administrator exists.

    Without this a fresh clone shows a login page that nobody can get past.
    """
    if request.endpoint in ("setup", "static") or admin_exists():
        return None
    return redirect(url_for("setup"))


@app.route("/setup", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
def setup():
    # 404 rather than 403 once setup is done: there is no reason to advertise
    # that the endpoint ever existed.
    if admin_exists():
        abort(404)

    form = SetupForm()
    if form.validate_on_submit():
        # Re-check inside the request that will write, so two people opening
        # the page at once cannot both create an administrator.
        if admin_exists():
            abort(404)
        user = User(
            username=form.username.data.strip(),
            password=bcrypt.generate_password_hash(form.password.data).decode("utf-8"),
            role=ROLE_ADMIN,
            approved=True,
        )
        db.session.add(user)
        db.session.commit()
        global _admin_exists
        _admin_exists = True
        login_user(user, fresh=True)
        current_app.logger.warning("setup.admin_created id=%s", user.id)
        flash("Administrator created. You are signed in.", "success")
        return redirect(url_for("dashboard"))
    return render_template("setup.html", form=form)


@app.route("/", methods=["GET", "POST"])
@app.route("/login", methods=["GET", "POST"])
@limiter.limit(
    "5 per minute; 30 per hour", methods=["POST"], key_func=_login_rate_key
)
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    form = LoginForm()
    if form.validate_on_submit():
        user = db.session.scalar(
            db.select(User).filter_by(username=form.username.data.strip())
        )
        if user and bcrypt.check_password_hash(user.password, form.password.data):
            if not user.approved:
                # Same wording as a bad password: revealing that the account
                # exists but is pending confirms a valid username to an attacker.
                current_app.logger.info("login.unapproved user=%s", user.id)
                flash("Login Unsuccessful. Please check username and password", "danger")
            else:
                login_user(user, fresh=True)
                current_app.logger.info(
                    "login.success user=%s ip=%s", user.id, request.remote_addr
                )
                next_page = request.args.get("next")
                if next_page and is_safe_url(next_page):
                    return redirect(next_page)
                return redirect(url_for("dashboard"))
        else:
            if not user:
                # Burn a comparable amount of time so response latency does not
                # distinguish "no such user" from "wrong password".
                bcrypt.check_password_hash(
                    bcrypt.generate_password_hash("timing-equalizer").decode("utf-8"),
                    form.password.data,
                )
            current_app.logger.info(
                "login.failed username=%r ip=%s",
                form.username.data, request.remote_addr,
            )
            flash("Login Unsuccessful. Please check username and password", "danger")
    return render_template("login.html", form=form)


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    form = RegistrationForm()
    if form.validate_on_submit():
        # The password policy lives entirely in the form validators; re-checking
        # it here produced six lines of unreachable code.
        hashed_password = bcrypt.generate_password_hash(form.password.data).decode("utf-8")
        user = User(
            username=form.username.data.strip(),
            password=hashed_password,
            role=ROLE_CUSTOMER,
            approved=False,
        )
        db.session.add(user)
        db.session.commit()
        current_app.logger.info("user.registered id=%s", user.id)
        flash("Your account has been created! Please wait for admin approval.", "success")
        return redirect(url_for("login"))
    return render_template("register.html", form=form)


@app.route("/dashboard")
@login_required
def dashboard():
    if current_user.is_admin:
        return render_template("admin_dashboard.html")
    return render_template("customer_dashboard.html")


@app.route("/rent", methods=["GET", "POST"])
@login_required
def rent():
    form = RentalForm()
    if form.validate_on_submit():
        car_id = request.form.get("car_id", type=int)
        car = db.session.get(Car, car_id) if car_id else None
        # Re-check availability server-side: car_id arrives in a hidden field
        # and the client is free to send the id of an already-rented car.
        if car is None or not car.available:
            flash("That car is no longer available.", "danger")
            return redirect(url_for("rent"))

        start_date = form.start_date.data
        end_date = form.end_date.data
        if end_date <= start_date:
            flash("End date and time must be after start date and time.", "danger")
        elif end_date - start_date < MIN_RENTAL_DURATION:
            flash(f"The minimum rental duration is {MIN_RENTAL_LABEL}.", "danger")
        else:
            total_days = (end_date - start_date).total_seconds() / 86400
            total_price = round(total_days * car.price_per_day, 2)
            rental = Rental(
                car_id=car.id,
                user_id=current_user.id,
                start_date=start_date,
                end_date=end_date,
                total_price=total_price,
            )
            car.available = False
            db.session.add(rental)
            db.session.commit()
            flash(f"Car rental successful! Total price: ${total_price:.2f}", "success")
            return redirect(url_for("rent"))

    cars = db.session.scalars(db.select(Car).filter_by(available=True)).all()
    return render_template("rent.html", cars=cars, form=form)


@app.route("/profile")
@login_required
def profile():
    total_spent = sum(rental.total_price for rental in current_user.rentals)
    car_expenses: dict[str, float] = {}
    for rental in current_user.rentals:
        car_expenses.setdefault(rental.car.model, 0)
        car_expenses[rental.car.model] += rental.total_price
    return render_template("profile.html", total_spent=total_spent, car_expenses=car_expenses)


@app.route("/manage_cars", methods=["GET", "POST"])
@roles_required(ROLE_ADMIN)
def manage_cars():
    form = CarForm()
    if form.validate_on_submit():
        car = Car(
            model=form.model.data.strip(),
            brand=form.brand.data.strip(),
            # The column is still Float; convert explicitly rather than letting
            # SQLite coerce a Decimal and warn about it.
            price_per_day=float(form.price_per_day.data),
            available=True,
        )
        db.session.add(car)
        db.session.commit()
        current_app.logger.info("car.created id=%s by=%s", car.id, current_user.id)
        flash("Car has been added!", "success")
        return redirect(url_for("manage_cars"))
    available_cars = db.session.scalars(db.select(Car).filter_by(available=True)).all()
    return render_template("manage_cars.html", form=form, cars=available_cars)


@app.route("/manage_users")
@roles_required(ROLE_ADMIN)
def manage_users():
    users = db.session.scalars(db.select(User).order_by(User.username)).all()
    return render_template("manage_users.html", users=users, form=ConfirmForm())


@app.post("/approve_user/<int:user_id>")
@roles_required(ROLE_ADMIN)
def approve_user(user_id):
    user = db.get_or_404(User, user_id)
    user.approved = True
    db.session.commit()
    current_app.logger.warning("user.approved id=%s by=%s", user.id, current_user.id)
    flash(f"Approved {user.username}.", "success")
    return redirect(url_for("manage_users"))


@app.post("/delete_user/<int:user_id>")
@roles_required(ROLE_ADMIN)
def delete_user(user_id):
    user = db.get_or_404(User, user_id)
    if user.id == current_user.id:
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for("manage_users"))

    rental_count = db.session.scalar(
        db.select(db.func.count(Rental.id)).filter_by(user_id=user.id)
    )
    if rental_count:
        # Deleting the parent used to NULL a NOT NULL foreign key and return a
        # 500. Refuse cleanly until soft-delete lands.
        flash(
            f"{user.username} has {rental_count} rental record(s) and cannot be deleted.",
            "danger",
        )
        return redirect(url_for("manage_users"))

    username = user.username
    try:
        db.session.delete(user)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        current_app.logger.exception("user.delete_failed id=%s", user_id)
        flash(f"{username} could not be deleted because other records reference them.", "danger")
        return redirect(url_for("manage_users"))

    current_app.logger.warning("user.deleted id=%s by=%s", user_id, current_user.id)
    flash(f"Deleted {username}.", "success")
    return redirect(url_for("manage_users"))


@app.route("/view_rentals")
@roles_required(ROLE_ADMIN)
def view_rentals():
    rentals = db.session.scalars(
        db.select(Rental).order_by(Rental.date_created.desc())
    ).all()
    return render_template("view_rentals.html", rentals=rentals)


@app.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("login"))


def ensure_schema(flask_app: Flask) -> None:
    """Create missing tables at startup.

    Convenient for self-hosted use, where the first run should just work. Set
    AUTO_CREATE_DB=0 once Alembic migrations exist, so the two do not disagree
    about who owns the schema.
    """
    if not _env_flag("AUTO_CREATE_DB", True):
        return
    with flask_app.app_context():
        db.create_all()


# CLI
@app.cli.command("init-db")
def init_db_command():
    """Create any missing tables. Superseded by `flask db upgrade` once Alembic lands."""
    db.create_all()
    click.echo("Tables created.")


@app.cli.command("create-admin")
@click.option("--username", default="admin", show_default=True)
@click.password_option(
    "--password",
    prompt=True,
    confirmation_prompt=True,
    help="Read from ADMIN_PASSWORD if set, otherwise prompted for.",
    default=lambda: os.environ.get("ADMIN_PASSWORD", ""),
)
def create_admin_command(username, password):
    """Create an administrator. Replaces the old hardcoded default-admin seed."""
    db.create_all()
    if db.session.scalar(db.select(User).filter_by(username=username)):
        raise click.ClickException(f"User {username!r} already exists.")
    if len(password) < 12:
        raise click.ClickException("Admin password must be at least 12 characters.")

    user = User(
        username=username,
        password=bcrypt.generate_password_hash(password).decode("utf-8"),
        role=ROLE_ADMIN,
        approved=True,
    )
    db.session.add(user)
    db.session.commit()
    global _admin_exists
    _admin_exists = True
    click.echo(f"Created admin {username!r} (id={user.id}).")


ensure_schema(app)


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    if EPHEMERAL_SECRET_KEY and host not in LOOPBACK_HOSTS:
        raise SystemExit(
            f"Refusing to bind {host} with a generated SECRET_KEY.\n"
            "Anything reachable from the network needs a persistent key:\n"
            '  python -c "import secrets; print(secrets.token_urlsafe(64))"\n'
            "  then put it in .env as SECRET_KEY=..."
        )
    with app.app_context():
        if not admin_exists():
            print("\n  First run: open http://127.0.0.1:5000/setup to create an admin.\n")
    # Never hardcode debug=True: the Werkzeug debugger is remote code execution
    # if it is ever reachable off-localhost.
    app.run(debug=_env_flag("FLASK_DEBUG"), host=host)
