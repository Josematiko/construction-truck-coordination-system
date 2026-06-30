from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.models import (
    Material,
    User,
    Order,
    Location,
    Chat,
    Truck,
    Payment,
    Rating,
    DriverAssignmentLog,
    DriverDispatchState,
    PaymentSetting,
)
from app.forms import (
    MaterialForm,
    RegisterForm,
    LocationForm,
    PaymentSettingsForm,
    ManualPaymentConfirmationForm,
)
from app import db, online_users
from werkzeug.security import generate_password_hash
from datetime import datetime
from app.services.dispatch import assign_waiting_orders, assign_order_to_next_driver

admin = Blueprint('admin', __name__)


def _date_range_from_request():
    start_raw = (request.args.get('start_date') or '').strip()
    end_raw = (request.args.get('end_date') or '').strip()
    start_dt = end_dt = None

    try:
        if start_raw:
            start_dt = datetime.strptime(start_raw, '%Y-%m-%d')
        if end_raw:
            end_dt = datetime.strptime(end_raw, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
    except ValueError:
        flash("Use valid report dates in YYYY-MM-DD format.", "warning")
        return '', '', None, None

    return start_raw, end_raw, start_dt, end_dt


def get_or_create_payment_setting():
    setting = PaymentSetting.query.first()
    if not setting:
        setting = PaymentSetting()
        db.session.add(setting)
        db.session.flush()
    return setting

# ---------------- Admin Dashboard ----------------
@admin.route('/admin/dashboard')
@login_required
def dashboard():
    if current_user.role != 'admin':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('auth.login'))
    
    # Count pending completions
    pending_count = Order.query.filter_by(driver_completed=True, admin_approved=False).count()
    pending_payment_confirmations = Payment.query.filter(
        Payment.status.in_(['Pending', 'Pending Confirmation'])
    ).count()
    pending_review_moderation = Rating.query.filter_by(is_displayed=False).count()

    # Count pending driver approvals
    pending_drivers = User.query.filter_by(role='driver', license_approved=False, status='Pending').count()
    
    # System overview stats
    total_users = User.query.count()
    total_customers = User.query.filter_by(role='customer').count()
    total_drivers = User.query.filter_by(role='driver').count()
    total_owners = User.query.filter_by(role='owner').count()
    total_orders = Order.query.count()
    completed_orders = Order.query.filter_by(status='Completed').count()
    total_trucks = Truck.query.count()
    total_materials = Material.query.count()
    total_locations = Location.query.count()
    pending_trucks = Truck.query.filter_by(approval_status='Pending').count()
    
    return render_template('admin_dashboard.html', 
                         pending_count=pending_count, 
                         pending_payment_confirmations=pending_payment_confirmations,
                         pending_review_moderation=pending_review_moderation,
                         pending_drivers=pending_drivers,
                         total_users=total_users,
                         total_customers=total_customers,
                         total_drivers=total_drivers,
                         total_owners=total_owners,
                         total_orders=total_orders,
                         completed_orders=completed_orders,
                         total_trucks=total_trucks,
                         total_materials=total_materials,
                         total_locations=total_locations,
                         pending_trucks=pending_trucks)


@admin.route('/admin/payment_settings', methods=['GET', 'POST'])
@login_required
def payment_settings():
    if current_user.role != 'admin':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('auth.login'))

    setting = get_or_create_payment_setting()
    form = PaymentSettingsForm()

    if request.method == 'GET':
        form.paybill_number.data = setting.paybill_number or ''

    if form.validate_on_submit():
        setting.paybill_number = (form.paybill_number.data or '').strip() or None
        db.session.commit()
        flash("Payment settings updated successfully.", "success")
        return redirect(url_for('admin.payment_settings'))

    return render_template('admin_payment_settings.html', form=form, setting=setting)


# ---------------- Manage Materials ----------------
@admin.route('/admin/materials', methods=['GET', 'POST'])
@login_required
def manage_materials():
    if current_user.role != 'admin':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('auth.login'))

    materials = Material.query.order_by(Material.name.asc()).all()
    form = MaterialForm()

    if form.is_submitted() and not form.validate():
        flash("Please check the material form values and try again.", "warning")

    if form.validate_on_submit():
        existing = Material.query.filter_by(name=form.name.data).first()
        if existing:
            flash("Material already exists!", "danger")
        else:
            try:
                price = float(form.price.data)
            except (TypeError, ValueError):
                flash("Price must be a valid number.", "danger")
                return render_template('admin_materials.html', form=form, materials=materials, editing_material=None)

            try:
                discount = float(form.discount_price.data) if form.discount_price.data else None
            except (TypeError, ValueError):
                flash("Discount price must be a valid number.", "danger")
                return render_template('admin_materials.html', form=form, materials=materials, editing_material=None)

            discount_start = form.discount_start.data
            discount_end = form.discount_end.data

            if discount is not None and (not discount_start or not discount_end):
                flash("Discount start and end dates are required when setting a limited offer.", "danger")
                return render_template('admin_materials.html', form=form, materials=materials, editing_material=None)

            if discount_start and discount_end and discount_start > discount_end:
                flash("Discount end date must be after start date.", "danger")
                return render_template('admin_materials.html', form=form, materials=materials, editing_material=None)

            material = Material(
                name=form.name.data,
                price=price,
                discount_price=discount,
                discount_start=discount_start,
                discount_end=discount_end
            )
            db.session.add(material)
            db.session.commit()
            flash("Material added successfully!", "success")
            return redirect(url_for('admin.manage_materials'))

    return render_template('admin_materials.html', form=form, materials=materials, editing_material=None)


# ---------------- Edit Material ----------------
@admin.route('/admin/edit_material/<int:material_id>', methods=['GET', 'POST'])
@login_required
def edit_material(material_id):
    if current_user.role != 'admin':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('auth.login'))

    material = Material.query.get_or_404(material_id)
    form = MaterialForm(obj=material)
    materials = Material.query.order_by(Material.name.asc()).all()

    if form.is_submitted() and not form.validate():
        flash("Please check the material form values and try again.", "warning")
    
    if form.validate_on_submit():
        # Check if name changed and conflicts
        if form.name.data != material.name:
            existing = Material.query.filter_by(name=form.name.data).first()
            if existing:
                flash("Material name already exists!", "danger")
                return render_template('admin_materials.html', form=form, materials=materials, editing_material=material)
        
        try:
            price = float(form.price.data)
        except (TypeError, ValueError):
            flash("Price must be a valid number.", "danger")
            return render_template('admin_materials.html', form=form, materials=materials, editing_material=material)

        try:
            discount = float(form.discount_price.data) if form.discount_price.data else None
        except (TypeError, ValueError):
            flash("Discount price must be a valid number.", "danger")
            return render_template('admin_materials.html', form=form, materials=materials, editing_material=material)

        discount_start = form.discount_start.data
        discount_end = form.discount_end.data

        if discount is not None and (not discount_start or not discount_end):
            flash("Discount start and end dates are required when setting a limited offer.", "danger")
            return render_template('admin_materials.html', form=form, materials=materials, editing_material=material)

        if discount_start and discount_end and discount_start > discount_end:
            flash("Discount end date must be after start date.", "danger")
            return render_template('admin_materials.html', form=form, materials=materials, editing_material=material)

        material.name = form.name.data
        material.price = price
        material.discount_price = discount
        material.discount_start = discount_start
        material.discount_end = discount_end
        db.session.commit()
        flash("Material updated successfully!", "success")
        return redirect(url_for('admin.manage_materials'))

    return render_template('admin_materials.html', form=form, materials=materials, editing_material=material)


# ---------------- Delete Material ----------------
@admin.route('/admin/delete_material/<int:material_id>')
@login_required
def delete_material(material_id):
    if current_user.role != 'admin':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('auth.login'))

    material = Material.query.get_or_404(material_id)
    db.session.delete(material)
    db.session.commit()
    flash("Material deleted successfully!", "success")
    return redirect(url_for('admin.manage_materials'))


# ---------------- Manage Drop Areas ----------------
@admin.route('/admin/locations', methods=['GET', 'POST'])
@login_required
def manage_locations():
    if current_user.role != 'admin':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('auth.login'))

    form = LocationForm()
    if form.validate_on_submit():
        existing = Location.query.filter_by(name=form.name.data.strip()).first()
        if existing:
            flash("Drop area already exists!", "danger")
        else:
            location = Location(name=form.name.data.strip())
            db.session.add(location)
            db.session.commit()
            flash("Drop area added successfully!", "success")
            return redirect(url_for('admin.manage_locations'))

    locations = Location.query.all()
    return render_template('admin_locations.html', form=form, locations=locations)


# ---------------- Manage Users ----------------
@admin.route('/admin/manage_users', methods=['GET', 'POST'])
@login_required
def manage_users():
    if current_user.role != 'admin':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('auth.home'))

    form = RegisterForm()
    default_roles = [
        ('', 'Select role...'),
        ('customer', 'Customer'),
        ('driver', 'Driver'),
        ('owner', 'Truck Owner')
    ]
    if current_user.is_primary_admin:
        form.role.choices = default_roles + [('admin', 'Admin')]
    else:
        form.role.choices = default_roles

    search_query = request.args.get('search', '').strip()
    
    if search_query:
        users = User.query.filter(
            (User.first_name.ilike(f'%{search_query}%')) |
            (User.last_name.ilike(f'%{search_query}%')) |
            (User.email.ilike(f'%{search_query}%'))
        ).all()
    else:
        users = User.query.all()

    if form.is_submitted() and not form.validate():
        flash("Please correct the highlighted fields. Names cannot contain numbers.", "warning")

    if form.validate_on_submit():
        # Only primary admin can create admin users
        if form.role.data == 'admin' and not current_user.is_primary_admin:
            flash("Only the primary admin can create other admins!", "danger")
            return redirect(url_for('admin.manage_users'))

        existing_user = User.query.filter_by(email=form.email.data).first()
        if existing_user:
            flash("User already exists!", "danger")
        else:
            is_primary_admin = False
            if form.role.data == 'admin':
                is_primary_admin = User.query.filter_by(role='admin', is_primary_admin=True).first() is None

            user = User(
                first_name=form.first_name.data,
                middle_name=form.middle_name.data,
                last_name=form.last_name.data,
                email=form.email.data,
                phone=form.phone.data,
                password_hash=generate_password_hash(form.password.data),
                role=form.role.data,
                status='Active' if form.role.data == 'admin' else 'Pending',
                is_primary_admin=is_primary_admin
            )
            db.session.add(user)
            db.session.commit()
            flash(f"User {user.first_name} added successfully!", "success")
            return redirect(url_for('admin.manage_users'))

    return render_template('admin_manage_users.html', 
                           form=form, 
                           users=users,
                           search_query=search_query,
                           is_primary_admin=current_user.is_primary_admin,
                           total_customers=User.query.filter_by(role='customer').count(),
                           total_drivers=User.query.filter_by(role='driver').count(),
                           total_owners=User.query.filter_by(role='owner').count(),
                           total_trucks=Truck.query.count())


# ---------------- Edit User ----------------
@admin.route('/admin/edit_user/<int:user_id>', methods=['GET', 'POST'])
@login_required
def edit_user(user_id):
    if current_user.role != 'admin':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('auth.home'))

    user = User.query.get_or_404(user_id)
    form = RegisterForm(obj=user)
    default_roles = [
        ('', 'Select role...'),
        ('customer', 'Customer'),
        ('driver', 'Driver'),
        ('owner', 'Truck Owner')
    ]
    if current_user.is_primary_admin or user.role == 'admin':
        form.role.choices = default_roles + [('admin', 'Admin')]
    else:
        form.role.choices = default_roles

    # Make password optional for editing
    form.password.validators = []
    form.confirm_password.validators = []

    if form.is_submitted() and not form.validate():
        flash("Please correct the highlighted fields. Names cannot contain numbers.", "warning")

    if form.validate_on_submit():
        if form.role.data == 'admin' and not current_user.is_primary_admin and user.role != 'admin':
            flash("Only the primary admin can promote a user to admin!", "danger")
            return redirect(url_for('admin.manage_users'))

        user.first_name = form.first_name.data
        user.middle_name = form.middle_name.data
        user.last_name = form.last_name.data
        user.email = form.email.data
        user.phone = form.phone.data
        if form.password.data:
            user.password_hash = generate_password_hash(form.password.data)
        user.role = form.role.data
        if user.role == 'admin' and User.query.filter(User.role == 'admin', User.is_primary_admin == True, User.id != user.id).first() is None:
            user.is_primary_admin = True
        db.session.commit()
        flash(f"User {user.first_name} updated successfully!", "success")
        return redirect(url_for('admin.manage_users'))

    return render_template('admin_manage_users.html', form=form, users=User.query.all(), editing_user=user)


@admin.route('/admin/approve_driver/<int:user_id>')
@login_required
def approve_driver(user_id):
    if current_user.role != 'admin':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('auth.home'))

    user = User.query.get_or_404(user_id)
    if user.role == 'driver':
        user.license_approved = True
        user.status = 'Active'  # Set status to Active when approved
        db.session.commit()
        newly_assigned = assign_waiting_orders()
        if newly_assigned:
            db.session.commit()
        flash(f"Driver {user.full_name()} approved!", "success")
        if newly_assigned:
            flash(f"{newly_assigned} waiting order(s) were assigned automatically.", "info")
    return redirect(url_for('admin.manage_users'))


@admin.route('/admin/reject_driver/<int:user_id>')
@login_required
def reject_driver(user_id):
    if current_user.role != 'admin':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('auth.home'))

    user = User.query.get_or_404(user_id)
    if user.role == 'driver':
        user.status = 'Rejected'
        db.session.commit()
        flash(f"Driver {user.full_name()} rejected!", "warning")
    return redirect(url_for('admin.manage_users'))


@admin.route('/admin/approve_truck/<int:truck_id>')
@login_required
def approve_truck(truck_id):
    if current_user.role != 'admin':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('auth.home'))

    truck = Truck.query.get_or_404(truck_id)
    truck.approval_status = 'Approved'
    db.session.commit()
    newly_assigned = assign_waiting_orders()
    if newly_assigned:
        db.session.commit()
    flash(f"Truck {truck.registration_number} approved and is now available for assignment.", "success")
    if newly_assigned:
        flash(f"{newly_assigned} waiting order(s) were assigned automatically.", "info")
    return redirect(url_for('admin.approve_trucks'))


@admin.route('/admin/reject_truck/<int:truck_id>')
@login_required
def reject_truck(truck_id):
    if current_user.role != 'admin':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('auth.home'))

    truck = Truck.query.get_or_404(truck_id)
    truck.approval_status = 'Rejected'
    db.session.commit()
    flash(f"Truck {truck.registration_number} has been rejected.", "warning")
    return redirect(url_for('admin.approve_trucks'))


@admin.route('/admin/approve_trucks')
@login_required
def approve_trucks():
    if current_user.role != 'admin':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('auth.home'))

    trucks = Truck.query.order_by(Truck.approval_status.asc(), Truck.registration_number.asc()).all()
    return render_template('admin_approve_trucks.html', trucks=trucks)


@admin.route('/admin/reviews')
@login_required
def manage_reviews():
    if current_user.role != 'admin':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('auth.home'))

    reviews = Rating.query.order_by(Rating.created_at.desc()).all()
    return render_template('admin_reviews.html', reviews=reviews)


@admin.route('/admin/review_action/<int:rating_id>/<string:action>')
@login_required
def review_action(rating_id, action):
    if current_user.role != 'admin':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('auth.home'))

    review = Rating.query.get_or_404(rating_id)
    if action == 'approve':
        review.is_displayed = True
        flash("Review marked for display.", "success")
    elif action == 'hide':
        review.is_displayed = False
        flash("Review hidden from public pages.", "info")
    else:
        flash("Invalid action.", "danger")
        return redirect(url_for('admin.manage_reviews'))

    db.session.commit()
    return redirect(url_for('admin.manage_reviews'))


@admin.route('/admin/confirm_order/<int:order_id>')
@login_required
def confirm_order(order_id):
    if current_user.role != 'admin':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('auth.home'))

    order = Order.query.get_or_404(order_id)
    if order.status == 'Completed (Pending Admin Approval)':
        order.status = 'Completed'
        db.session.commit()
        flash("Order confirmed as completed!", "success")
    return redirect(url_for('admin.dashboard'))


# ---------------- Delete User ----------------
@admin.route('/admin/delete_user/<int:user_id>')
@login_required
def delete_user(user_id):
    if current_user.role != 'admin':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('auth.login'))

    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("You cannot delete your own account!", "danger")
        return redirect(url_for('admin.manage_users'))

    if user.is_primary_admin:
        flash("The original admin cannot be deleted!", "danger")
        return redirect(url_for('admin.manage_users'))

    # Delete associated records first
    order_ids = [
        row[0] for row in
        db.session.query(Order.id).filter((Order.customer_id == user_id) | (Order.driver_id == user_id)).all()
    ]

    if order_ids:
        DriverAssignmentLog.query.filter(
            DriverAssignmentLog.order_id.in_(order_ids)
        ).delete(synchronize_session=False)
        Payment.query.filter(Payment.order_id.in_(order_ids)).delete(synchronize_session=False)

    # Delete logs where the user was an offered/declining driver
    DriverAssignmentLog.query.filter_by(driver_id=user_id).delete(synchronize_session=False)

    # Reset dispatch pointer if it references this driver
    DriverDispatchState.query.filter_by(next_driver_id=user_id).update(
        {'next_driver_id': None},
        synchronize_session=False
    )

    # Delete orders where user is customer or driver
    Order.query.filter((Order.customer_id == user_id) | (Order.driver_id == user_id)).delete(synchronize_session=False)
    # Delete chats where user is sender or receiver
    Chat.query.filter((Chat.sender_id == user_id) | (Chat.receiver_id == user_id)).delete(synchronize_session=False)
    # Delete trucks where user is owner or driver
    Truck.query.filter((Truck.owner_id == user_id) | (Truck.driver_id == user_id)).delete(synchronize_session=False)

    db.session.delete(user)
    db.session.commit()
    flash("User and all associated records deleted successfully!", "success")
    return redirect(url_for('admin.manage_users'))


# ---------------- Manage Truck Assignments ----------------
@admin.route('/admin/assign_trucks', methods=['GET', 'POST'])
@login_required
def assign_trucks():
    if current_user.role != 'admin':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('auth.home'))

    if request.method == 'POST':
        truck_id = request.form.get('truck_id')
        driver_id = request.form.get('driver_id')
        
        truck = Truck.query.get_or_404(truck_id)
        if driver_id:
            driver = User.query.get_or_404(driver_id)
            if driver.role == 'driver' and driver.license_approved:
                # Check if driver already has a truck
                existing_truck = Truck.query.filter_by(driver_id=driver_id).first()
                if existing_truck:
                    flash(f"Driver {driver.full_name()} is already assigned to another truck!", "danger")
                else:
                    truck.driver_id = driver_id
                    db.session.commit()
                    newly_assigned = assign_waiting_orders()
                    if newly_assigned:
                        db.session.commit()
                    flash(f"Truck {truck.registration_number} assigned to {driver.full_name()}!", "success")
                    if newly_assigned:
                        flash(f"{newly_assigned} waiting order(s) were assigned automatically.", "info")
            else:
                flash("Selected user is not an approved driver!", "danger")
        else:
            # Unassign
            truck.driver_id = None
            db.session.commit()
            flash(f"Truck {truck.registration_number} unassigned!", "success")
        
        return redirect(url_for('admin.assign_trucks'))

    # Get all approved trucks and approved drivers
    trucks = Truck.query.filter_by(approval_status='Approved').all()
    drivers = User.query.filter_by(role='driver', license_approved=True).all()
    
    return render_template('admin_assign_trucks.html', trucks=trucks, drivers=drivers)


# ---------------- Approve/Reject Drivers ----------------
@admin.route('/admin/driver_action/<int:driver_id>/<string:action>')
@login_required
def driver_action(driver_id, action):
    if current_user.role != 'admin':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('auth.home'))

    driver = User.query.get_or_404(driver_id)

    if action == 'approve':
        driver.is_available = True
        driver.status = 'Approved'
        flash(f"{driver.first_name} has been approved ✅", "success")
    elif action == 'reject':
        driver.is_available = False
        driver.status = 'Rejected'
        flash(f"{driver.first_name} has been rejected ❌", "danger")
    else:
        flash("Invalid action!", "danger")
        return redirect(url_for('admin.approve_drivers'))

    db.session.commit()
    return redirect(url_for('admin.approve_drivers'))


# ---------------- Approve Drivers Page ----------------
@admin.route('/admin/approve_drivers')
@login_required
def approve_drivers():
    if current_user.role != 'admin':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('auth.home'))

    drivers = User.query.filter_by(role='driver').all()
    return render_template('admin_approve_drivers.html', drivers=drivers)


# ---------------- View Orders ----------------
@admin.route('/admin/view_orders')
@login_required
def view_orders():
    if current_user.role != 'admin':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('auth.login'))

    orders = (
        Order.query
        .order_by(Order.assigned_date.desc(), Order.id.desc())
        .all()
    )

    latest_payments = {}
    order_ids = [order.id for order in orders]
    if order_ids:
        payments = (
            Payment.query
            .filter(Payment.order_id.in_(order_ids))
            .order_by(Payment.id.desc())
            .all()
        )
        for payment in payments:
            if payment.order_id not in latest_payments:
                latest_payments[payment.order_id] = payment

    return render_template(
        'admin_orders.html',
        orders=orders,
        online_users=online_users,
        latest_payments=latest_payments
    )


@admin.route('/admin/confirm_payment/<int:payment_id>', methods=['GET', 'POST'])
@login_required
def confirm_payment(payment_id):
    if current_user.role != 'admin':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('auth.login'))

    payment = Payment.query.get_or_404(payment_id)
    order = payment.order
    if not order:
        flash("Payment is not linked to a valid order.", "danger")
        return redirect(url_for('admin.view_orders'))

    if payment.status == 'Completed':
        flash("This payment is already confirmed.", "info")
        return redirect(url_for('admin.view_orders'))

    form = ManualPaymentConfirmationForm()
    if request.method == 'GET':
        form.provider_reference.data = payment.provider_reference or ''
        form.status_message.data = payment.status_message or ''

    if form.validate_on_submit():
        payment.status = 'Completed'
        payment.paid_at = datetime.utcnow()
        payment.confirmed_at = datetime.utcnow()
        payment.confirmed_by_admin_id = current_user.id
        payment.provider_reference = (form.provider_reference.data or '').strip() or payment.provider_reference
        note = (form.status_message.data or '').strip()
        payment.status_message = (note or "Payment manually confirmed by admin.")[:255]

        if order.status in ['Awaiting Payment', 'Payment Failed', 'Pending']:
            assigned_driver, _, dispatch_error = assign_order_to_next_driver(order)
            if not assigned_driver:
                order.status = 'Pending'
                if dispatch_error:
                    payment.status_message = (
                        f"{payment.status_message} {dispatch_error}"
                    )[:255]

        db.session.commit()
        flash(
            f"Payment confirmed for Order #{order.id}. Amount Ksh {payment.amount:.2f}.",
            "success"
        )
        return redirect(url_for('admin.view_orders'))

    return render_template(
        'admin_confirm_payment.html',
        form=form,
        payment=payment,
        order=order
    )


@admin.route('/admin/delivery_reports')
@login_required
def delivery_reports():
    if current_user.role != 'admin':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('auth.login'))

    start_date, end_date, start_dt, end_dt = _date_range_from_request()
    report_date = db.func.coalesce(Order.approved_at, Order.completed_at, Order.assigned_date)

    completed_query = Order.query.filter_by(status='Completed')
    if start_dt:
        completed_query = completed_query.filter(report_date >= start_dt)
    if end_dt:
        completed_query = completed_query.filter(report_date <= end_dt)

    completed_orders = completed_query.order_by(
        Order.approved_at.desc(),
        Order.completed_at.desc(),
        Order.id.desc()
    ).all()

    accepted_logs = (
        DriverAssignmentLog.query
        .filter_by(status='accepted')
        .order_by(DriverAssignmentLog.id.desc())
        .all()
    )
    accepted_by_order = {}
    for log in accepted_logs:
        if log.order_id not in accepted_by_order:
            accepted_by_order[log.order_id] = log

    trucks_by_driver = {}
    for truck in Truck.query.filter(Truck.driver_id.isnot(None)).order_by(Truck.id.asc()).all():
        trucks_by_driver.setdefault(truck.driver_id, truck)

    delivery_details = []
    summary_index = {}

    for order in completed_orders:
        accepted_log = accepted_by_order.get(order.id)
        truck = accepted_log.truck if accepted_log and accepted_log.truck else trucks_by_driver.get(order.driver_id)
        driver = order.driver if order.driver else (accepted_log.driver if accepted_log else None)

        delivery_time = order.approved_at or order.completed_at or order.assigned_date
        delivery_date = delivery_time.date() if delivery_time else None

        driver_name = driver.full_name() if driver else 'N/A'
        truck_reg = truck.registration_number if truck else 'Untracked'
        material_name = order.material.name if order.material else 'Unknown'

        detail = {
            'date': delivery_date,
            'order_id': order.id,
            'truck': truck_reg,
            'driver': driver_name,
            'material': material_name,
            'quantity': order.quantity,
            'price': order.total_price or 0,
        }
        delivery_details.append(detail)

        key = (delivery_date, truck_reg, driver_name)
        if key not in summary_index:
            summary_index[key] = {
                'date': delivery_date,
                'truck': truck_reg,
                'driver': driver_name,
                'deliveries': 0,
                'total_price': 0,
            }
        summary_index[key]['deliveries'] += 1
        summary_index[key]['total_price'] += (order.total_price or 0)

    daily_summary = sorted(
        summary_index.values(),
        key=lambda row: (row['date'] or datetime.min.date(), row['truck'], row['driver']),
        reverse=True
    )

    declined_date = db.func.coalesce(DriverAssignmentLog.responded_at, DriverAssignmentLog.created_at)
    declined_query = DriverAssignmentLog.query.filter_by(status='declined')
    if start_dt:
        declined_query = declined_query.filter(declined_date >= start_dt)
    if end_dt:
        declined_query = declined_query.filter(declined_date <= end_dt)

    declined_logs = declined_query.order_by(
        DriverAssignmentLog.responded_at.desc(),
        DriverAssignmentLog.created_at.desc()
    ).all()

    return render_template(
        'admin_delivery_reports.html',
        daily_summary=daily_summary,
        delivery_details=delivery_details,
        declined_logs=declined_logs,
        start_date=start_date,
        end_date=end_date
    )


# ---------------- Update Order Status ----------------
@admin.route('/admin/update_order/<int:order_id>/<string:status>')
@login_required
def update_order(order_id, status):
    if current_user.role != 'admin':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('auth.login'))

    order = Order.query.get_or_404(order_id)
    if status not in ['Approved', 'Rejected']:
        flash("Invalid status!", "danger")
        return redirect(url_for('admin.view_orders'))

    order.status = status
    db.session.commit()
    flash(f"Order {status} successfully!", "success")
    return redirect(url_for('admin.view_orders'))

@admin.route('/admin/assign_driver/<int:order_id>', methods=['GET', 'POST'])
@login_required
def assign_driver(order_id):
    if current_user.role != 'admin':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('auth.login'))

    order = Order.query.get_or_404(order_id)
    drivers = User.query.filter_by(role='driver', status='Approved').all()

    if request.method == 'POST':
        driver_id = request.form.get('driver_id')

        order.driver_id = driver_id
        order.status = 'Assigned'

        db.session.commit()

        flash("Driver assigned successfully! 🚚", "success")
        return redirect(url_for('admin.view_orders'))

    return render_template('assign_driver.html', order=order, drivers=drivers)


# -------- Pending Order Completions --------
@admin.route('/admin/pending_completions')
@login_required
def pending_completions():
    if current_user.role != 'admin':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('auth.login'))

    pending_orders = Order.query.filter_by(driver_completed=True, admin_approved=False).all()
    return render_template('admin_pending_completions.html', pending_orders=pending_orders, online_users=online_users)


# -------- Approve Order Completion --------
@admin.route('/admin/approve_completion/<int:order_id>')
@login_required
def approve_completion(order_id):
    if current_user.role != 'admin':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('auth.login'))

    order = Order.query.get_or_404(order_id)
    if order.driver_completed and not order.admin_approved:
        from datetime import datetime
        order.admin_approved = True
        order.approved_at = datetime.utcnow()
        order.status = 'Completed'
        db.session.commit()
        newly_assigned = assign_waiting_orders()
        if newly_assigned:
            db.session.commit()
        flash(f"Order completion approved! Driver: {order.driver.first_name} {order.driver.last_name}", "success")
        if newly_assigned:
            flash(f"{newly_assigned} waiting order(s) were assigned automatically.", "info")
    return redirect(url_for('admin.pending_completions'))
