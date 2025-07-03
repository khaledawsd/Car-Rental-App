# Car Rental System

A modern, secure, and user-friendly car rental management system built with Flask.

## Features
- User registration and login with password validation
- Admin approval for new users
- Role-based dashboards (Admin & Customer)
- Car management (add, view, and list cars)
- Car rental with minimum duration enforcement
- Rental history and user profile with spending summary
- Admin management of users and rentals
- Responsive, modern UI with dark mode

## Technologies Used
- Python 3
- Flask
- Flask-SQLAlchemy
- Flask-Bcrypt
- Flask-Login
- Flask-Migrate
- Flask-WTF & WTForms
- SQLite (default, can be swapped for other DBs)
- HTML5, CSS3, Jinja2 Templates

## Setup Instructions

1. **Clone the repository**
   ```bash
   git clone https://github.com/khaledawsd/Car-Rental-App.git
   cd "Car rental Assigment code"
   ```

2. **Create and activate a virtual environment**
   ```bash
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On Mac/Linux:
   source venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the application**
   ```bash
   python app.py
   ```

5. **Access the app**
   Open your browser and go to [http://127.0.0.1:5000](http://127.0.0.1:5000)

## Default Admin Login
- **Username:** admin
- **Password:** admin123

## Notes
- New users must be approved by the admin before they can log in.
- You can customize the database URI and secret key in `app.py`.

## Screenshots
_Add screenshots of the UI here if desired._

## License
This project is for educational purposes. 
