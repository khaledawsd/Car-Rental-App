# Car Rental System

A comprehensive car rental platform built with Flask, featuring robust security
measures including SQL injection protection, XSS prevention, and secure password
hashing. Implements secure user authentication, rental processing, and
administrative controls.

## Features
- User registration and login with an enforced password policy
- Admin approval workflow for new accounts
- Role-based access control (Admin & Customer)
- Car management (add, view, and list cars)
- Car rental with minimum duration enforcement
- Rental history and user profile with spending summary
- Admin management of users and rentals
- Responsive UI with dark mode

## Security

Each item below is enforced in code and covered by the test suite.

**Injection and output encoding**

- **SQL injection** — every query goes through SQLAlchemy's expression API
  (`select()`, `filter_by()`, `session.get()`), which sends values as bound
  parameters. There is no raw SQL and no query built by string formatting
  anywhere in the application.
- **Cross-site scripting** — Jinja's autoescaping is left on for all templates
  and never bypassed: no `|safe`, no `Markup()`, no `autoescape false`. The two
  places JavaScript assigns `innerHTML` build their markup from fixed constants
  and numbers derived from `Date`, never from user input; anything user-supplied
  is written with `textContent`.

**Authentication**

- Passwords are hashed with **bcrypt** and never stored or logged in plain text.
- A password policy requires 8+ characters with upper and lower case, a digit
  and a symbol; administrators require 12+.
- Login is rate limited to 5 attempts per minute and 30 per hour, keyed on both
  client address and submitted username, so one attacker cannot lock out every
  account.
- Failed logins return a single message whether or not the account exists, and
  an unknown username still runs a hash comparison so response timing does not
  reveal which accounts are real.
- New accounts cannot sign in until an administrator approves them.

**Authorization and sessions**

- Every administrative route is gated by a `roles_required` decorator that wraps
  `login_required`, so authentication can never be omitted by mistake. Hiding a
  navigation link is not treated as access control.
- All state-changing operations are POST and carry a CSRF token; `CSRFProtect`
  is enabled application-wide.
- The post-login `?next=` parameter is validated against the request host, so it
  cannot redirect off-site (CWE-601).
- Session cookies are `HttpOnly`, `SameSite=Lax` and `Secure` outside local
  development, and sessions expire after 12 hours.
- The signing key is read from the environment. The app refuses to start under a
  production WSGI server, or on a non-loopback address, without one.
- Denied access, failed logins, approvals and deletions are all logged.

## Technologies Used
- Python 3.11+
- Flask, Flask-SQLAlchemy, Flask-Login, Flask-Bcrypt
- Flask-Migrate, Flask-WTF / WTForms, Flask-Limiter
- SQLite by default; any SQLAlchemy-supported database via `DATABASE_URL`
- HTML5, CSS3, Jinja2 templates

## Setup

1. **Clone and enter the repository**
   ```bash
   git clone https://github.com/khaledawsd/Car-Rental-App.git
   cd Car-Rental-App
   ```

2. **Create and activate a virtual environment**
   ```bash
   python -m venv venv
   ```
   Then `venv\Scripts\activate` on Windows, or `source venv/bin/activate` on macOS/Linux.

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Run it**
   ```bash
   python app.py
   ```
   Open http://127.0.0.1:5000 and you will be taken to a one-time setup page to
   create the administrator account. That page stops existing as soon as an
   admin does.

   No configuration is needed to try the app: it creates its database on first
   run and generates a temporary signing key, printing a warning that sessions
   will not survive a restart.

### Running tests

```bash
pip install -r requirements-dev.txt
```
```bash
pytest
```

## Hosting it for real

The convenience above is scoped to local runs. As soon as the app could be
reached by someone else, it requires a real signing key, and it enforces this
rather than trusting you to remember:

- it **refuses to start** under gunicorn/uWSGI/waitress without `SECRET_KEY`,
  because each worker would otherwise generate a different key and logins would
  fail at random;
- it **refuses to bind** a non-loopback address with a generated key.

So, to host it:

```bash
cp .env.example .env
```
```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Put that value in `.env` as `SECRET_KEY`, then serve it with a real WSGI server
behind a TLS-terminating reverse proxy:

```bash
waitress-serve --port=8000 --threads=8 app:app
```

Waitress is pure Python and runs on Windows, macOS and Linux, so this is the
same command whatever you develop on. On a Linux host you can use gunicorn
instead if you prefer — `pip install gunicorn`, then:

```bash
gunicorn --bind 0.0.0.0:8000 --workers 4 --worker-class gthread --threads 2 app:app
```

It is not in `requirements.txt` because it cannot run on Windows at all: it
imports `fcntl`, which does not exist there.

Also set `SESSION_COOKIE_SECURE=1`, keep `FLASK_DEBUG=0`, and if you run more
than one worker process, point `RATELIMIT_STORAGE_URI` at Redis so login rate
limits are shared rather than counted per worker.

If you prefer to create the administrator from the command line rather than the
setup page — for scripted installs — use:

```bash
flask --app app create-admin
```

## Maintenance commands

All of these take `--app app`, e.g. `flask --app app clear-rentals`.

| Command | What it does |
| --- | --- |
| `init-db` | Create any missing tables. |
| `create-admin` | Create an administrator from the command line. |
| `clear-rentals` | Delete all rental history and return every car to available. |
| `reset-db` | Drop and recreate every table. Destroys accounts too. |

`clear-rentals` is also the only way to free a car that has been rented, because
availability is currently a boolean that is never reset when a rental ends.

Both destructive commands prompt before acting; pass `--yes` to skip the prompt
in a script.

## How it works

- **First run** has no administrator, so every request redirects to `/setup`
  until one is created. `/setup` returns 404 once it has been used.
- **Registration** creates an unapproved account. It cannot log in until an
  administrator approves it from **Manage Users**.
- **Authorization** is enforced server-side by the `roles_required` decorator on
  every admin route. Hiding a navigation link is not access control; the
  decorator is what actually gates the endpoint.
- **Login** is rate limited to 5 attempts per minute and 30 per hour, keyed on
  both client address and submitted username.
- **Rentals** require a minimum duration of 4 hours and cannot start in the
  past, with a 5-minute grace for clock skew. Price is pro-rated by the hour
  from the car's daily rate.
- **Dates** are shown as day/month/year everywhere. The picker is a custom
  component rather than a native date input, because a native one renders in
  the browser's locale and cannot be forced to a chosen format.

## Known limitations

These are tracked and intentionally not yet addressed:

- `Car.available` is a boolean that is never reset when a rental ends, so a car
  stays out of the catalogue after its first rental. Availability should be
  derived from overlapping rental intervals instead.
- Money is stored as `Float` rather than `Numeric(10, 2)`.
- `/profile` and `/view_rentals` issue N+1 queries and are not paginated.
- Schema is created with `db.create_all()`; Flask-Migrate is installed but no
  migrations have been generated yet. Set `AUTO_CREATE_DB=0` once that changes.
- Output escaping is handled, but there is no Content-Security-Policy yet. The
  templates no longer carry inline styles or scripts, so a strict policy is now
  possible to add; it simply has not been.
- HTTPS is expected to be terminated by a reverse proxy. The app sets `Secure`
  cookies but does not itself redirect HTTP to HTTPS or send HSTS.
- Cars can be added but not edited or deleted from the interface.
- Routes, models, and forms share one module. The next refactor is an
  application factory and blueprints; `tests/conftest.py` documents where the
  current import-time seam is.

## License

This project is for educational purposes.
