from flask import Blueprint, render_template, redirect, url_for, flash, request
from app.forms import RegisterForm, LoginForm, ChangePasswordForm, ForgotPasswordForm, ResetPasswordForm
from app.models import User, Material, Truck, Order, Rating
from app import db
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import login_user, logout_user, login_required, current_user
from datetime import datetime
import secrets
import os

auth = Blueprint('auth', __name__)

# ---------------- REGISTER ----------------
@auth.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()  

    if form.is_submitted() and not form.validate():
        flash("Please fill in all the required details below!", "warning")
    
    if form.validate_on_submit():

        # Check role selected
        if not form.role.data:
            flash("Please select a role!", "danger")
            return render_template('register.html', form=form)

        # For drivers, require license details
        if form.role.data == 'driver':
            if not form.license_number.data:
                flash("License number is required for drivers!", "danger")
                return render_template('register.html', form=form)
            if not form.license_photo.data:
                flash("License photo is required for drivers!", "danger")
                return render_template('register.html', form=form)

        # Check if user exists
        existing_user = User.query.filter_by(email=form.email.data).first()
        if existing_user:
            flash("User already exists!", "danger")
            return render_template('register.html', form=form)

        # Hash password
        hashed_password = generate_password_hash(form.password.data)

        # Handle license photo upload for drivers
        license_photo_path = None
        if form.role.data == 'driver' and form.license_photo.data:
            # Create uploads directory if not exists
            upload_dir = os.path.join('app', 'static', 'uploads')
            os.makedirs(upload_dir, exist_ok=True)
            # Save file
            filename = f"{secrets.token_hex(8)}_{form.license_photo.data.filename}"
            filepath = os.path.join(upload_dir, filename)
            form.license_photo.data.save(filepath)
            license_photo_path = f"uploads/{filename}"

        # Create user
        user = User(
            first_name=form.first_name.data,
            middle_name=form.middle_name.data,
            last_name=form.last_name.data,
            email=form.email.data,
            phone=form.phone.data,
            password_hash=hashed_password,
            role=form.role.data,
            license_number=form.license_number.data if form.role.data == 'driver' else None,
            license_photo=license_photo_path,
            license_approved=False if form.role.data == 'driver' else None
        )

        db.session.add(user)
        db.session.commit()

        # Auto login
        login_user(user)
        if form.role.data == 'driver':
            flash(f"Welcome {user.first_name}! Your driver registration is pending admin approval. You will be notified once approved. 🎉", "success")
        else:
            flash(f"Welcome {user.first_name}! Account created successfully 🎉", "success")

        return redirect(url_for('auth.home'))

    return render_template('register.html', form=form)


# ---------------- LOGIN ----------------
@auth.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()  

    if form.is_submitted() and not form.validate():
        flash("Please fill in all the required details below!", "warning")

    if form.validate_on_submit():

        # Find user
        user = User.query.filter_by(email=form.email.data).first()

        if not user:
            flash("User does not exist!", "danger")
            return render_template('login.html', form=form)

        if not check_password_hash(user.password_hash, form.password.data):
            flash("Incorrect password!", "danger")
            return render_template('login.html', form=form)

        # Success
        login_user(user)
        flash(f"Welcome back {user.first_name}! 👋", "success")
        return redirect(url_for('auth.home'))

    return render_template('login.html', form=form)


# ---------------- LOGOUT ----------------
@auth.route('/logout')
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for('auth.login'))


# ---------------- HOME ----------------
@auth.route('/')
def index():
    """Public landing page"""
    today = datetime.utcnow().date()
    discounted_materials = Material.query.filter(Material.discount_price.isnot(None)).all()
    valid_discounted_materials = [m for m in discounted_materials if m.discount_start and m.discount_end and m.discount_start <= today <= m.discount_end]

    # Real statistics
    total_trucks = Truck.query.count()
    total_customers = User.query.filter_by(role='customer').count()
    total_orders = Order.query.filter_by(status='Completed').count()
    avg_rating = db.session.query(db.func.avg(Rating.rating)).filter(Rating.is_displayed == True).scalar()
    if avg_rating:
        avg_rating = round(avg_rating, 1)
    else:
        avg_rating = 4.8  # default

    return render_template('index.html', 
                         discounted_materials=valid_discounted_materials,
                         total_trucks=total_trucks,
                         total_customers=total_customers,
                         total_orders=total_orders,
                         avg_rating=avg_rating)


@auth.route('/home')
@login_required
def home():
    """Redirect users to dashboards with welcome flash messages"""
    if current_user.role == 'admin':
        flash(f"Welcome back, Admin {current_user.first_name}!", "success")
        return redirect(url_for('admin.dashboard'))
    elif current_user.role == 'driver':
        flash(f"Welcome back, Driver {current_user.first_name}!", "success")
        return redirect(url_for('driver.dashboard'))
    elif current_user.role == 'owner':
        flash(f"Welcome back, Owner {current_user.first_name}!", "success")
        return redirect(url_for('owner.dashboard'))
    elif current_user.role == 'customer':
        flash(f"Welcome back, {current_user.first_name}!", "success")
        return redirect(url_for('customer.dashboard'))
    else:
        flash("Role not recognized!", "danger")
        return redirect(url_for('auth.index'))


@auth.route('/reviews')
def reviews():
    reviews = Rating.query.filter_by(is_displayed=True).order_by(Rating.created_at.desc()).all()
    return render_template('reviews.html', reviews=reviews)


@auth.route('/help')
def help():
    support_contacts = [
        {
            'title': 'General Support',
            'description': 'Use this for login problems, account access, order questions, and payment follow-up.',
            'action': 'Visit the contacts page',
            'url': url_for('auth.contacts')
        },
        {
            'title': 'Customer Help',
            'description': 'Need help placing an order, paying by M-Pesa or Paybill, or checking delivery status.',
            'action': 'Open customer dashboard',
            'url': url_for('customer.dashboard') if current_user.is_authenticated and current_user.role == 'customer' else url_for('auth.login')
        },
        {
            'title': 'Admin Help',
            'description': 'For payment confirmation, review moderation, driver approval, and truck approval tasks.',
            'action': 'Open admin dashboard',
            'url': url_for('admin.dashboard') if current_user.is_authenticated and current_user.role == 'admin' else url_for('auth.login')
        }
    ]

    role_guides = [
        {
            'title': 'Customers',
            'items': [
                'Place multiple orders whenever needed without waiting for older orders to complete.',
                'Choose a material, quantity, drop area, and payment method before submitting the order.',
                'Pay discounted prices automatically whenever a material has an active discount.',
                'Use My Orders to track payment, driver assignment, delivery progress, and completed jobs.'
            ]
        },
        {
            'title': 'Drivers',
            'items': [
                'Accept or decline assigned orders from the driver dashboard.',
                'Update delivery progress and mark the trip complete when the job is finished.',
                'Chat with customers only after the order has been assigned to you.'
            ]
        },
        {
            'title': 'Truck Owners',
            'items': [
                'Register trucks and wait for admin approval before they can be used.',
                'Work with admin to assign approved drivers to approved trucks.',
                'Review truck activity and operational status from the owner dashboard.'
            ]
        },
        {
            'title': 'Admins',
            'items': [
                'Confirm paybill payments from Orders and Payments before dispatch.',
                'Moderate customer reviews so only approved reviews appear publicly.',
                'Approve drivers, trucks, and completed deliveries from the admin dashboard.'
            ]
        }
    ]

    faqs = [
        {
            'question': 'How do I place a new order if I already have another one in progress?',
            'answer': 'You can place a new order at any time. The system now allows multiple orders per customer, and each order keeps its own payment and delivery status.'
        },
        {
            'question': 'How is the amount to pay calculated when a material is discounted?',
            'answer': 'If the material has an active discount, the system charges the discount price. If there is no active discount, it charges the normal material price.'
        },
        {
            'question': 'Why does my order say Awaiting Admin Payment Confirmation?',
            'answer': 'That status appears when you choose Paybill. After you pay manually, an admin must confirm the payment before the order is sent for driver assignment.'
        },
        {
            'question': 'Why am I not receiving an M-Pesa prompt?',
            'answer': 'Check that your Safaricom number is entered in 07XXXXXXXX or 2547XXXXXXXX format, and make sure the app has valid M-Pesa credentials configured.'
        },
        {
            'question': 'Can I pay for an old order later?',
            'answer': 'No.Orders are paid for before delivery.'
        },
        {
            'question': 'Why can’t I chat on some orders?',
            'answer': 'Chat becomes available after a driver has been assigned. Orders that are still waiting for payment or waiting for driver response will not allow chat yet.'
        },
        {
            'question': 'What should an admin do after a customer pays by till or paybill?',
            'answer': 'The admin should open Orders and Payments, find the payment marked Pending Confirmation, and confirm it so the order can continue through dispatch.'
        }
    ]

    return render_template(
        'help.html',
        support_contacts=support_contacts,
        role_guides=role_guides,
        faqs=faqs
    )


@auth.route('/about')
def about():
    return render_template('about.html')


@auth.route('/contacts')
def contacts():
    return render_template('contacts.html')


# ---------------- Change Password ----------------
@auth.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not check_password_hash(current_user.password_hash, form.current_password.data):
            flash("Current password is incorrect!", "danger")
            return render_template('change_password.html', form=form)
        
        current_user.password_hash = generate_password_hash(form.new_password.data)
        db.session.commit()
        flash("Password changed successfully!", "success")
        return redirect(url_for('auth.home'))
    
    return render_template('change_password.html', form=form)


# ---------------- Forgot Password ----------------
@auth.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user:
            # Generate reset token
            token = secrets.token_urlsafe(32)
            user.reset_token = token
            db.session.commit()
            
            # In a real app, send email with reset link
            reset_link = url_for('auth.reset_password', token=token, _external=True)
            flash(f"Reset link sent to {user.email}. For demo: {reset_link}", "info")
        else:
            flash("If an account with that email exists, a reset link has been sent.", "info")
    
    return render_template('forgot_password.html', form=form)


# ---------------- Reset Password ----------------
@auth.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    user = User.query.filter_by(reset_token=token).first()
    if not user:
        flash("Invalid or expired reset token!", "danger")
        return redirect(url_for('auth.login'))
    
    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.password_hash = generate_password_hash(form.password.data)
        user.reset_token = None
        db.session.commit()
        flash("Password reset successfully! Please login.", "success")
        return redirect(url_for('auth.login'))
    
    return render_template('reset_password.html', form=form)
