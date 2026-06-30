from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.models import Truck, User, Order
from app.forms import TruckForm
from app import db
from datetime import datetime, timedelta

owner = Blueprint('owner', __name__)


def _date_range_from_request(default_days=None):
    start_raw = (request.args.get('start_date') or '').strip()
    end_raw = (request.args.get('end_date') or '').strip()

    if default_days and not start_raw and not end_raw:
        start_raw = (datetime.utcnow() - timedelta(days=default_days)).strftime('%Y-%m-%d')
        end_raw = datetime.utcnow().strftime('%Y-%m-%d')

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

@owner.route('/owner/dashboard')
@login_required
def dashboard():
    if current_user.role != 'owner':
        return redirect(url_for('auth.login'))

    trucks = Truck.query.filter_by(owner_id=current_user.id).all()
    total_trucks = len(trucks)
    # Calculate total jobs (completed orders for owner's trucks)
    total_jobs = Order.query.join(Truck, Order.driver_id == Truck.driver_id).filter(Truck.owner_id == current_user.id, Order.status == 'Completed').count()
    # Calculate active jobs (assigned but not completed)
    active_jobs = Order.query.join(Truck, Order.driver_id == Truck.driver_id).filter(Truck.owner_id == current_user.id, Order.status.in_(['Assigned', 'In Progress'])).count()

    return render_template('owner_dashboard.html', total_trucks=total_trucks, total_jobs=total_jobs, active_jobs=active_jobs)


@owner.route('/owner/add_truck', methods=['GET', 'POST'])
@login_required
def add_truck():
    if current_user.role != 'owner':
        flash("Unauthorized access!", "danger")
        return redirect('/')

    form = TruckForm()

    if form.validate_on_submit():
        truck = Truck(
            registration_number=form.registration_number.data,
            owner_id=current_user.id,
            driver_id=None,  # No driver assigned initially
            approval_status='Pending'
        )
        db.session.add(truck)
        db.session.commit()
        flash("Truck added successfully and is pending admin approval.", "success")
        return redirect(url_for('owner.dashboard'))

    return render_template('owner_add_truck.html', form=form)


@owner.route('/owner/trucks')
@login_required
def view_trucks():
    if current_user.role != 'owner':
        flash("Unauthorized access!", "danger")
        return redirect('/')

    trucks = Truck.query.filter_by(owner_id=current_user.id).all()
    return render_template('owner_trucks.html', trucks=trucks)


@owner.route('/owner/reports')
@login_required
def reports():
    if current_user.role != 'owner':
        flash("Unauthorized access!", "danger")
        return redirect('/')

    start_date, end_date, start_dt, end_dt = _date_range_from_request(default_days=7)
    report_date = db.func.coalesce(Order.approved_at, Order.completed_at, Order.assigned_date)

    query = Order.query.join(Truck, Order.driver_id == Truck.driver_id).filter(
        Truck.owner_id == current_user.id,
        Order.status == 'Completed'
    )
    if start_dt:
        query = query.filter(report_date >= start_dt)
    if end_dt:
        query = query.filter(report_date <= end_dt)

    orders = query.order_by(Order.approved_at.desc(), Order.completed_at.desc(), Order.id.desc()).all()

    total_earnings = sum(o.total_price for o in orders)
    report_data = []
    for order in orders:
        order_date = order.approved_at or order.completed_at or order.assigned_date
        report_data.append({
            'date': order_date.date() if order_date else None,
            'material': order.material.name if order.material else 'Unknown Material',
            'amount': order.total_price
        })

    return render_template(
        'owner_reports.html',
        report_data=report_data,
        total_earnings=total_earnings,
        start_date=start_date,
        end_date=end_date
    )
