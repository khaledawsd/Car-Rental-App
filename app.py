from flask import Flask, render_template, redirect, url_for, flash, request
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, current_user, logout_user, login_required
from flask_migrate import Migrate
from datetime import datetime, timedelta
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, IntegerField, FloatField, DateTimeLocalField
from wtforms.validators import DataRequired, Length, ValidationError, EqualTo
import re

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///carrental.db'
db = SQLAlchemy(app)
migrate = Migrate(app, db)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'

# Models
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(20), unique=True, nullable=False)
    password = db.Column(db.String(60), nullable=False)
    role = db.Column(db.String(10), nullable=False)
    approved = db.Column(db.Boolean, nullable=False, default=False)
    rentals = db.relationship('Rental', backref='user', lazy=True)

class Car(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    model = db.Column(db.String(100), nullable=False)
    brand = db.Column(db.String(100), nullable=False)
    price_per_day = db.Column(db.Float, nullable=False)
    available = db.Column(db.Boolean, nullable=False, default=True)
    rentals = db.relationship('Rental', backref='car', lazy=True)

class Rental(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    car_id = db.Column(db.Integer, db.ForeignKey('car.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    start_date = db.Column(db.DateTime, nullable=False)
    end_date = db.Column(db.DateTime, nullable=False)
    total_price = db.Column(db.Float, nullable=False)
    date_created = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

# Custom password validator
def password_check(form, field):
    password = field.data
    if len(password) < 8:
        raise ValidationError('Password must be at least 8 characters long.')
    if not re.search(r'[A-Z]', password):
        raise ValidationError('Password must contain at least one uppercase letter.')
    if not re.search(r'[a-z]', password):
        raise ValidationError('Password must contain at least one lowercase letter.')
    if not re.search(r'\d', password):
        raise ValidationError('Password must contain at least one number.')
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        raise ValidationError('Password must contain at least one special character.')

# Forms
class LoginForm(FlaskForm):
    username = StringField('Username', 
                           validators=[DataRequired(), Length(min=2, max=20)],
                           render_kw={"placeholder": "Username"})
    password = PasswordField('Password', 
                             validators=[DataRequired()],
                             render_kw={"placeholder": "Password"})
    submit = SubmitField('Login')

class RegistrationForm(FlaskForm):
    username = StringField('Username', 
                           validators=[DataRequired(), Length(min=2, max=20)],
                           render_kw={"placeholder": "Username"})
    password = PasswordField('Password', 
                             validators=[DataRequired(), password_check],
                             render_kw={"placeholder": "Password"})
    confirm_password = PasswordField('Confirm Password', 
                                     validators=[DataRequired(), EqualTo('password', message='Passwords must match')],
                                     render_kw={"placeholder": "Confirm Password"})
    submit = SubmitField('Register')
    
    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError('That username is taken. Please choose a different one.')


class CarForm(FlaskForm):
    model = StringField('Model', validators=[DataRequired(), Length(max=20)],
                        render_kw={"placeholder": "Model"})
    brand = StringField('Brand', validators=[DataRequired(), Length(max=20)],
                        render_kw={"placeholder": "Brand"})
    price_per_day = FloatField('Price per Day', validators=[DataRequired()],
                               render_kw={"placeholder": "Price per Day", "type": "number", "step": "0.01"})
    submit = SubmitField('Add Car')

class RentalForm(FlaskForm):
    start_date = DateTimeLocalField('Start Date and Time', format='%Y-%m-%dT%H:%M', validators=[DataRequired()])
    end_date = DateTimeLocalField('End Date and Time', format='%Y-%m-%dT%H:%M', validators=[DataRequired()])
    submit = SubmitField('Rent')

# Routes
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route("/", methods=['GET', 'POST'])
@app.route("/login", methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and bcrypt.check_password_hash(user.password, form.password.data):
            if user.approved:
                login_user(user)
                next_page = request.args.get('next')
                return redirect(next_page) if next_page else redirect(url_for('dashboard'))
            else:
                flash('Account not approved yet. Please wait for admin approval.', 'warning')
        else:
            flash('Login Unsuccessful. Please check username and password', 'danger')
    return render_template('login.html', form=form)

@app.route("/register", methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    form = RegistrationForm()
    if form.validate_on_submit():
        if len(form.password.data) < 8:
            flash('Your password must be at least 8 characters long.', 'danger')
        elif not re.search(r'[A-Za-z]', form.password.data) or not re.search(r'\d', form.password.data) or not re.search(r'[!@#$%^&*(),.?":{}|<>]', form.password.data):
            flash('Your password must include a mix of letters, numbers, and symbols.', 'danger')
        elif form.password.data != form.confirm_password.data:
            flash('The passwords entered do not match. Please try again.', 'danger')
        else:
            hashed_password = bcrypt.generate_password_hash(form.password.data).decode('utf-8')
            user = User(username=form.username.data, password=hashed_password, role='customer', approved=False)
            db.session.add(user)
            db.session.commit()
            flash('Your account has been created! Please wait for admin approval.', 'success')
            return redirect(url_for('login'))
    return render_template('register.html', form=form)

@app.route("/dashboard")
@login_required
def dashboard():
    if current_user.role == 'admin':
        return render_template('admin_dashboard.html')
    else:
        return render_template('customer_dashboard.html')

@app.route("/rent", methods=['GET', 'POST'])
@login_required
def rent():
    cars = Car.query.filter_by(available=True).all()
    form = RentalForm()
    if request.method == 'POST':
        car_id = request.form.get('car_id')
        car = Car.query.get(car_id)
        if car:
            start_date = form.start_date.data
            end_date = form.end_date.data
            min_duration = timedelta(hours=4)  # Minimum rental duration

            if end_date <= start_date:
                flash('End date and time must be after start date and time.', 'danger')
            elif end_date - start_date < min_duration:
                flash(f'The minimum rental duration is {min_duration}.', 'danger')
            else:
                total_hours = (end_date - start_date).total_seconds() / 3600
                total_days = total_hours / 24
                total_price = round(total_days * car.price_per_day, 2)
                rental = Rental(car_id=car.id, user_id=current_user.id, start_date=start_date, end_date=end_date, total_price=total_price)
                car.available = False
                db.session.add(rental)
                db.session.commit()
                flash(f'Car rental successful! Total price: ${total_price:.2f}', 'success')
                return redirect(url_for('rent'))
    return render_template('rent.html', cars=cars, form=form)

@app.route("/profile")
@login_required
def profile():
    total_spent = sum(rental.total_price for rental in current_user.rentals)
    car_expenses = {}
    for rental in current_user.rentals:
        if rental.car.model not in car_expenses:
            car_expenses[rental.car.model] = 0
        car_expenses[rental.car.model] += rental.total_price
    return render_template('profile.html', total_spent=total_spent, car_expenses=car_expenses)

@app.route("/manage_cars", methods=['GET', 'POST'])
@login_required
def manage_cars():
    form = CarForm()
    if form.validate_on_submit():
        car = Car(model=form.model.data, brand=form.brand.data, price_per_day=form.price_per_day.data, available=True)
        db.session.add(car)
        db.session.commit()
        flash('Car has been added!', 'success')
        return redirect(url_for('manage_cars'))
    available_cars = Car.query.filter_by(available=True).all()
    return render_template('manage_cars.html', form=form, cars=available_cars)

@app.route("/manage_users")
@login_required
def manage_users():
    users = User.query.all()
    return render_template('manage_users.html', users=users)

@app.route("/approve_user/<int:user_id>")
@login_required
def approve_user(user_id):
    user = User.query.get(user_id)
    user.approved = True
    db.session.commit()
    return redirect(url_for('manage_users'))

@app.route("/delete_user/<int:user_id>")
@login_required
def delete_user(user_id):
    user = User.query.get(user_id)
    db.session.delete(user)
    db.session.commit()
    return redirect(url_for('manage_users'))

@app.route("/view_rentals")
@login_required
def view_rentals():
    rentals = Rental.query.all()
    return render_template('view_rentals.html', rentals=rentals)

@app.route("/logout")
def logout():
    logout_user()
    return redirect(url_for('login'))

def create_default_admin():
    hashed_password = bcrypt.generate_password_hash('admin123').decode('utf-8')
    admin = User(username='admin', password=hashed_password, role='admin', approved=True)
    db.session.add(admin)
    db.session.commit()

if __name__ == "__main__":
    with app.app_context():
        db.create_all()  # Create database tables
        if not User.query.filter_by(username='admin').first():
            create_default_admin()
    app.run(debug=True)
