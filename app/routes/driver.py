from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from flask_socketio import emit, join_room
from app.models import Order, Truck, Chat
from app.forms import DriverResponseForm, TruckStatusForm, ChatForm
from app import db, socketio, online_users
from datetime import datetime
from app.services.dispatch import (
    FINAL_ORDER_STATUSES,
    assign_order_to_next_driver,
    get_declined_driver_ids,
    mark_latest_offer_response,
)

driver = Blueprint('driver', __name__)


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
        flash("Use valid order dates in YYYY-MM-DD format.", "warning")
        return '', '', None, None
    return start_raw, end_raw, start_dt, end_dt

@driver.route('/driver/dashboard')
@login_required
def dashboard():
    if current_user.role != 'driver':
        return redirect(url_for('auth.login'))

    if not current_user.license_approved:
        flash("Your driver registration is pending admin approval. You will be notified once approved.", "warning")
        return redirect(url_for('auth.index'))

    truck = Truck.query.filter_by(driver_id=current_user.id, approval_status='Approved').first()
    all_orders = (
        Order.query
        .filter_by(driver_id=current_user.id)
        .order_by(Order.assigned_date.desc(), Order.id.desc())
        .all()
    )
    orders = [
        order for order in all_orders
        if order.status not in ['Completed', 'Pending Driver Response']
    ]
    pending_orders = [
        order for order in all_orders
        if order.status == 'Pending Driver Response'
    ]
    active_order = (
        Order.query
        .filter(
            Order.driver_id == current_user.id,
            Order.status.notin_(FINAL_ORDER_STATUSES)
        )
        .first()
    )
    
    # Count unread messages for this driver
    unread_count = Chat.query.filter_by(receiver_id=current_user.id, is_read=False).count()

    return render_template(
        'driver_dashboard.html',
        truck=truck,
        orders=orders,
        pending_orders=pending_orders,
        active_order=active_order,
        unread_count=unread_count,
        completed_count=len([order for order in all_orders if order.status == 'Completed'])
    )


@driver.route('/driver/respond_order/<int:order_id>', methods=['GET', 'POST'])
@login_required
def respond_order(order_id):
    if current_user.role != 'driver':
        flash("Unauthorized access!", "danger")
        return redirect('/')

    if not current_user.license_approved:
        flash("Your driver registration is pending admin approval.", "warning")
        return redirect(url_for('auth.index'))

    order = Order.query.get_or_404(order_id)
    if order.driver_id != current_user.id or order.status != 'Pending Driver Response':
        flash("This job request is no longer available for your response.", "warning")
        return redirect(url_for('driver.dashboard'))

    form = DriverResponseForm()

    if form.validate_on_submit():
        if form.response.data == 'accept':
            assigned_truck = Truck.query.filter_by(driver_id=current_user.id, approval_status='Approved').first()
            if not assigned_truck:
                mark_latest_offer_response(
                    order_id=order.id,
                    driver_id=current_user.id,
                    status='declined',
                    reason='Driver has no approved truck assignment.'
                )
                order.driver_id = None
                order.status = 'Pending'
                declined_driver_ids = get_declined_driver_ids(order.id)
                next_driver, _, dispatch_error = assign_order_to_next_driver(
                    order,
                    exclude_driver_ids=declined_driver_ids
                )
                db.session.commit()
                if next_driver:
                    flash("You are not assigned to an approved truck. Request moved to the next available driver.", "warning")
                elif dispatch_error:
                    flash(dispatch_error, "warning")
                else:
                    flash("No eligible driver was available. The request is waiting for assignment.", "warning")
                return redirect(url_for('driver.dashboard'))

            active_order = (
                Order.query
                .filter(
                    Order.driver_id == current_user.id,
                    Order.id != order.id,
                    Order.status.notin_(FINAL_ORDER_STATUSES)
                )
                .first()
            )
            if active_order:
                flash("You must complete your current order before accepting another one.", "warning")
                return redirect(url_for('driver.dashboard'))

            mark_latest_offer_response(
                order_id=order.id,
                driver_id=current_user.id,
                status='accepted'
            )
            order.status = 'In Transit'
            db.session.commit()
            flash("Order accepted!", "success")
        else:
            decline_reason = (form.reason.data or "").strip()
            if not decline_reason:
                flash("Please provide a reason before declining this request.", "danger")
                return render_template('driver_respond_order.html', form=form, order=order)

            mark_latest_offer_response(
                order_id=order.id,
                driver_id=current_user.id,
                status='declined',
                reason=decline_reason
            )
            order.driver_id = None
            order.status = 'Pending'

            declined_driver_ids = get_declined_driver_ids(order.id)
            next_driver, _, dispatch_error = assign_order_to_next_driver(
                order,
                exclude_driver_ids=declined_driver_ids
            )
            db.session.commit()

            if next_driver:
                flash("Order declined. Request sent to the next available driver.", "info")
            elif dispatch_error:
                flash(f"Order declined. {dispatch_error}", "warning")
            else:
                flash("Order declined. We are finding another driver.", "warning")
        return redirect(url_for('driver.dashboard'))

    return render_template('driver_respond_order.html', form=form, order=order)


@driver.route('/driver/complete_order/<int:order_id>')
@login_required
def complete_order(order_id):
    if current_user.role != 'driver':
        flash("Unauthorized access!", "danger")
        return redirect('/')

    if not current_user.license_approved:
        flash("Your driver registration is pending admin approval.", "warning")
        return redirect(url_for('auth.index'))

    order = Order.query.get_or_404(order_id)
    if order.driver_id == current_user.id and order.status == 'In Transit':
        from datetime import datetime
        order.status = 'Completed (Pending Admin Approval)'
        order.driver_completed = True
        order.completed_at = datetime.utcnow()
        db.session.commit()
        flash("Order marked as completed. Waiting for admin approval.", "success")
    elif order.driver_id == current_user.id:
        flash("Only in-transit orders can be marked complete.", "warning")
    return redirect(url_for('driver.dashboard'))


@driver.route('/driver/update_truck_status', methods=['GET', 'POST'])
@login_required
def update_truck_status():
    if current_user.role != 'driver':
        flash("Unauthorized access!", "danger")
        return redirect('/')

    if not current_user.license_approved:
        flash("Your driver registration is pending admin approval.", "warning")
        return redirect(url_for('auth.index'))

    truck = Truck.query.filter_by(driver_id=current_user.id, approval_status='Approved').first()
    if not truck:
        flash("No approved truck assigned!", "danger")
        return redirect(url_for('driver.dashboard'))

    form = TruckStatusForm()
    if form.validate_on_submit():
        truck.status = form.status.data
        db.session.commit()
        flash("Truck status updated!", "success")
        return redirect(url_for('driver.dashboard'))

    return render_template('driver_update_status.html', form=form)


@driver.route('/driver/chat/<int:order_id>', methods=['GET', 'POST'])
@login_required
def chat(order_id):
    if current_user.role != 'driver':
        flash("Unauthorized access!", "danger")
        return redirect('/')

    if not current_user.license_approved:
        flash("Your driver registration is pending admin approval.", "warning")
        return redirect(url_for('auth.index'))

    order = Order.query.get_or_404(order_id)
    if order.driver_id != current_user.id:
        flash(f"Unauthorized: order.driver_id={order.driver_id}, current_user.id={current_user.id}", "danger")
        return redirect('/')

    form = ChatForm()
    if form.validate_on_submit():
        chat_msg = Chat(
            order_id=order_id,
            sender_id=current_user.id,
            receiver_id=order.customer_id,
            message=form.message.data
        )
        db.session.add(chat_msg)
        db.session.commit()
        flash("Message sent!", "success")
        return redirect(url_for('driver.chat', order_id=order_id))

    chats = Chat.query.filter_by(order_id=order_id).order_by(Chat.timestamp).all()
    
    # Mark messages as read for this user
    unread_messages = Chat.query.filter_by(order_id=order_id, receiver_id=current_user.id, is_read=False).all()
    for msg in unread_messages:
        msg.is_read = True
    db.session.commit()
    
    return render_template('driver_chat.html', form=form, chats=chats, order=order, online_users=online_users)


@driver.route('/driver/completed_orders')
@login_required
def completed_orders():
    if current_user.role != 'driver':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('auth.login'))

    if not current_user.license_approved:
        flash("Your driver registration is pending admin approval.", "warning")
        return redirect(url_for('auth.index'))

    start_date, end_date, start_dt, end_dt = _date_range_from_request()
    report_date = db.func.coalesce(Order.completed_at, Order.assigned_date)

    query = Order.query.filter(
        Order.driver_id == current_user.id,
        Order.status.in_(['Completed', 'Completed (Pending Admin Approval)'])
    )
    if start_dt:
        query = query.filter(report_date >= start_dt)
    if end_dt:
        query = query.filter(report_date <= end_dt)

    completed = query.order_by(Order.completed_at.desc(), Order.id.desc()).all()
    return render_template(
        'driver_completed_orders.html',
        orders=completed,
        start_date=start_date,
        end_date=end_date
    )


# SocketIO events are handled in customer.py to avoid duplicates

