from datetime import datetime

import json

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import login_required, current_user
from flask_socketio import emit, join_room, leave_room
from app.models import Chat, Location, Material, Order, Payment, PaymentSetting, Rating
from app.forms import OrderForm, PaymentForm, RatingForm
from app import db, socketio, online_users
from app.services.dispatch import assign_order_to_next_driver
from app.services.mpesa import MpesaError, initiate_stk_push, parse_stk_callback

customer = Blueprint('customer', __name__)


def _current_paybill_number():
    setting = PaymentSetting.query.first()
    return (setting.paybill_number or '').strip() if setting else ''


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


def _material_has_active_discount(material, today=None):
    if not material or material.discount_price is None:
        return False

    today = today or datetime.utcnow().date()
    if material.discount_start and material.discount_end:
        return material.discount_start <= today <= material.discount_end

    return True


def _effective_material_price(material, today=None):
    if _material_has_active_discount(material, today=today):
        return material.discount_price
    return material.price

@customer.route('/customer/dashboard')
@login_required
def dashboard():
    if current_user.role != 'customer':
        flash("Unauthorized access!", "danger")
        return redirect('/')

    orders = (
        Order.query
        .filter_by(customer_id=current_user.id)
        .order_by(Order.assigned_date.desc(), Order.id.desc())
        .limit(3)
        .all()
    )
    
    # Count unread messages for this customer
    unread_count = Chat.query.filter_by(receiver_id=current_user.id, is_read=False).count()

    # Get materials for offers
    materials = [m for m in Material.query.all() if _material_has_active_discount(m)]

    return render_template('customer_dashboard.html', orders=orders, unread_count=unread_count, materials=materials)


@customer.route('/customer/chat/<int:order_id>', methods=['GET', 'POST'])
@login_required
def chat(order_id):
    if current_user.role != 'customer':
        flash("Unauthorized access!", "danger")
        return redirect('/')

    order = Order.query.get_or_404(order_id)
    if order.customer_id != current_user.id:
        flash("Unauthorized!", "danger")
        return redirect('/')

    from app.forms import ChatForm
    from app.models import Chat
    form = ChatForm()
    if form.validate_on_submit():
        chat_msg = Chat(
            order_id=order_id,
            sender_id=current_user.id,
            receiver_id=order.driver_id,
            message=form.message.data
        )
        db.session.add(chat_msg)
        db.session.commit()
        flash("Message sent!", "success")
        return redirect(url_for('customer.chat', order_id=order_id))

    # Only allow chat if driver is assigned
    if not order.driver_id or order.status in ['Pending', 'Pending Driver Response']:
        flash("Chat is available once a driver is assigned to your order.", "info")
        return redirect(url_for('customer.my_orders'))
    
    chats = Chat.query.filter_by(order_id=order_id).order_by(Chat.timestamp).all()
    
    # Mark messages as read for this user
    unread_messages = Chat.query.filter_by(order_id=order_id, receiver_id=current_user.id, is_read=False).all()
    for msg in unread_messages:
        msg.is_read = True
    db.session.commit()
    
    return render_template('customer_chat.html', form=form, chats=chats, order=order, online_users=online_users)



@customer.route('/customer/order', methods=['GET', 'POST'])
@login_required
def place_order():
    if current_user.role != 'customer':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('auth.home'))

    form = OrderForm()
    materials = Material.query.all()
    locations = Location.query.all()
    paybill_number = _current_paybill_number()
    pricing_today = datetime.utcnow().date()

    form.material.choices = [(0, 'Select Material')] + [(m.id, m.name) for m in materials]
    form.drop_area.choices = [(0, 'Select Drop Area')] + [(l.id, l.name) for l in locations]
    if request.method == 'GET':
        form.phone_number.data = current_user.phone or ''

    if form.validate_on_submit():
        if form.material.data == 0:
            flash("Please select a material", "danger")
            return redirect(url_for('customer.place_order'))
        if form.drop_area.data == 0:
            flash("Please select a drop area", "danger")
            return redirect(url_for('customer.place_order'))

        material = Material.query.get(form.material.data)
        location = Location.query.get(form.drop_area.data)

        unit_price = _effective_material_price(material)
        total_price = unit_price * form.quantity.data

        order = Order(
            customer_id=current_user.id,
            material_id=material.id,
            quantity=form.quantity.data,
            total_price=total_price,
            drop_location_id=location.id,
            status='Awaiting Payment'
        )

        callback_url = current_app.config.get('MPESA_CALLBACK_URL')
        if not callback_url:
            callback_url = url_for('customer.mpesa_callback', _external=True)

        db.session.add(order)
        db.session.flush()

        payment = Payment(
            order_id=order.id,
            amount=order.total_price,
            status='Pending',
            payment_method=form.payment_method.data
        )
        db.session.add(payment)
        db.session.flush()

        if form.payment_method.data == 'Paybill':
            if not paybill_number:
                db.session.rollback()
                flash("Paybill payment is not available yet. Admin has not set a paybill number.", "danger")
                return redirect(url_for('customer.place_order'))

            payment.status = 'Pending Confirmation'
            payment.status_message = "Awaiting admin payment confirmation."
            db.session.commit()
            flash(
                f"Order received. Pay Ksh {order.total_price:.2f} to Paybill {paybill_number}. "
                "Your order will be sent to a driver after admin confirms payment.",
                "info"
            )
            return redirect(url_for('customer.my_orders'))

        try:
            response, normalized_phone = initiate_stk_push(
                amount=order.total_price,
                phone_number=form.phone_number.data,
                account_reference=f"ORDER-{order.id}",
                transaction_desc=f"Order {order.id} payment",
                callback_url=callback_url
            )
            payment.transaction_id = response.get('CheckoutRequestID')
            payment.provider_reference = response.get('MerchantRequestID')
            payment.status_message = response.get('ResponseDescription') or response.get('CustomerMessage')

            if str(response.get('ResponseCode')) != '0':
                db.session.rollback()
                flash(payment.status_message or "Payment request failed. Please try again.", "danger")
                return redirect(url_for('customer.place_order'))

            if normalized_phone and normalized_phone != (current_user.phone or ''):
                current_user.phone = normalized_phone

            db.session.commit()
            flash(
                response.get('CustomerMessage') or
                f"Order received. Payment prompt sent to {normalized_phone}. Complete payment to continue.",
                "success"
            )
            return redirect(url_for('customer.my_orders'))
        except MpesaError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            return redirect(url_for('customer.place_order'))

    return render_template(
        'place_order.html',
        form=form,
        paybill_number=paybill_number,
        material_prices=json.dumps({
            str(m.id): {
                'name': m.name,
                'regular_price': float(m.price or 0),
                'effective_price': float(_effective_material_price(m, today=pricing_today) or 0),
                'discount_active': _material_has_active_discount(m, today=pricing_today),
            }
            for m in materials
        })
    )


@customer.route('/customer/orders')
@login_required
def my_orders():
    if current_user.role != 'customer':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('auth.home'))

    start_date, end_date, start_dt, end_dt = _date_range_from_request()
    query = Order.query.filter_by(customer_id=current_user.id)
    if start_dt:
        query = query.filter(Order.assigned_date >= start_dt)
    if end_dt:
        query = query.filter(Order.assigned_date <= end_dt)

    orders = query.order_by(Order.assigned_date.desc(), Order.id.desc()).all()
    
    order_ids = [order.id for order in orders]
    ratings = Rating.query.filter(Rating.order_id.in_(order_ids)).all() if order_ids else []
    ratings_by_order = {rating.order_id: rating for rating in ratings}

    payments_by_order = {}
    if order_ids:
        payments = (
            Payment.query
            .filter(Payment.order_id.in_(order_ids))
            .order_by(Payment.id.desc())
            .all()
        )
        for payment in payments:
            if payment.order_id not in payments_by_order:
                payments_by_order[payment.order_id] = payment

    for order in orders:
        payment = payments_by_order.get(order.id)
        if order.status == 'Awaiting Payment' and payment and payment.status == 'Pending Confirmation':
            order.display_status = 'Awaiting Admin Payment Confirmation'
        elif order.status == 'Awaiting Payment':
            order.display_status = 'Awaiting M-Pesa Payment'
        elif order.status == 'Payment Failed':
            order.display_status = 'Payment Failed'
        elif order.status == 'Pending' and order.driver_id is None:
            order.display_status = 'Finding Driver...'
        elif order.status == 'Pending Driver Response':
            order.display_status = 'Driver Reviewing Request'
        else:
            order.display_status = order.status

    return render_template(
        'customer_orders.html',
        orders=orders,
        ratings_by_order=ratings_by_order,
        payments_by_order=payments_by_order,
        start_date=start_date,
        end_date=end_date
    )


@customer.route('/customer/rate_order/<int:order_id>', methods=['GET', 'POST'])
@login_required
def rate_order(order_id):
    if current_user.role != 'customer':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('auth.home'))

    order = Order.query.get_or_404(order_id)
    if order.customer_id != current_user.id or order.status != 'Completed':
        flash("Cannot rate this order!", "danger")
        return redirect(url_for('customer.my_orders'))

    # Check if already rated
    existing_rating = Rating.query.filter_by(order_id=order_id).first()
    if existing_rating:
        flash("Order already rated!", "info")
        return redirect(url_for('customer.my_orders'))

    form = RatingForm()
    if form.validate_on_submit():
        rating = Rating(
            order_id=order_id,
            customer_id=current_user.id,
            rating=form.rating.data,
            comment=form.comment.data
        )
        db.session.add(rating)
        db.session.commit()
        flash("Thank you for your rating!", "success")
        return redirect(url_for('customer.my_orders'))

    return render_template('rate_order.html', form=form, order=order)


@customer.route('/customer/pay/<int:order_id>', methods=['GET', 'POST'])
@login_required
def pay_order(order_id):
    if current_user.role != 'customer':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('auth.home'))

    order = Order.query.get_or_404(order_id)
    if order.customer_id != current_user.id:
        flash("You can only pay for your own order.", "danger")
        return redirect(url_for('customer.my_orders'))

    existing_completed = (
        Payment.query
        .filter_by(order_id=order.id, status='Completed')
        .order_by(Payment.id.desc())
        .first()
    )
    if existing_completed:
        flash("This order has already been paid.", "info")
        return redirect(url_for('customer.my_orders'))

    form = PaymentForm()
    paybill_number = _current_paybill_number()
    if request.method == 'GET':
        form.phone_number.data = current_user.phone or ''

    if form.validate_on_submit():
        callback_url = current_app.config.get('MPESA_CALLBACK_URL')
        if not callback_url:
            callback_url = url_for('customer.mpesa_callback', _external=True)

        previous_pending = (
            Payment.query
            .filter(
                Payment.order_id == order.id,
                Payment.status.in_(['Pending', 'Pending Confirmation'])
            )
            .order_by(Payment.id.desc())
            .first()
        )
        if previous_pending:
            previous_pending.status = 'Failed'
            previous_pending.status_message = 'Replaced by a newer payment request.'

        payment = Payment(
            order_id=order.id,
            amount=order.total_price,
            status='Pending',
            payment_method=form.payment_method.data
        )
        db.session.add(payment)
        db.session.flush()

        if form.payment_method.data == 'Paybill':
            if not paybill_number:
                db.session.rollback()
                flash("Paybill payment is not available yet. Admin has not set a paybill number.", "danger")
                return redirect(url_for('customer.pay_order', order_id=order.id))

            order.status = 'Awaiting Payment'
            payment.status = 'Pending Confirmation'
            payment.status_message = "Awaiting admin payment confirmation."
            db.session.commit()
            flash(
                f"Pay Ksh {order.total_price:.2f} to Paybill {paybill_number}. "
                "Order will be assigned after admin confirms payment.",
                "info"
            )
            return redirect(url_for('customer.my_orders'))

        db.session.commit()

        try:
            response, normalized_phone = initiate_stk_push(
                amount=order.total_price,
                phone_number=form.phone_number.data,
                account_reference=f"ORDER-{order.id}",
                transaction_desc=f"Order {order.id} payment",
                callback_url=callback_url
            )

            payment.transaction_id = response.get('CheckoutRequestID')
            payment.provider_reference = response.get('MerchantRequestID')
            payment.status_message = response.get('ResponseDescription') or response.get('CustomerMessage')

            if str(response.get('ResponseCode')) != '0':
                payment.status = 'Failed'
                db.session.commit()
                flash(payment.status_message or "Payment request failed.", "danger")
                return redirect(url_for('customer.my_orders'))

            db.session.commit()
            flash(
                response.get('CustomerMessage') or
                f"Payment prompt sent to {normalized_phone}. Complete it on your phone.",
                "success"
            )
            return redirect(url_for('customer.my_orders'))
        except MpesaError as exc:
            payment.status = 'Failed'
            payment.status_message = str(exc)
            db.session.commit()
            flash(str(exc), "danger")
            return redirect(url_for('customer.pay_order', order_id=order.id))

    return render_template(
        'customer_pay_order.html',
        form=form,
        order=order,
        paybill_number=paybill_number
    )


@customer.route('/payments/mpesa/callback', methods=['POST'])
def mpesa_callback():
    payload = request.get_json(silent=True) or {}
    callback = parse_stk_callback(payload)

    checkout_request_id = callback.get('checkout_request_id')
    if not checkout_request_id:
        return jsonify({'ResultCode': 0, 'ResultDesc': 'Accepted'}), 200

    payment = (
        Payment.query
        .filter_by(transaction_id=checkout_request_id)
        .order_by(Payment.id.desc())
        .first()
    )

    if not payment:
        return jsonify({'ResultCode': 0, 'ResultDesc': 'Accepted'}), 200

    if payment.status == 'Completed':
        return jsonify({'ResultCode': 0, 'ResultDesc': 'Already processed'}), 200

    result_code = callback.get('result_code')
    result_desc = callback.get('result_desc') or ''

    if str(result_code) == '0':
        payment.status = 'Completed'
        payment.paid_at = datetime.utcnow()
        payment.status_message = 'Payment completed successfully.'
        receipt = callback.get('metadata', {}).get('MpesaReceiptNumber')
        if receipt:
            payment.provider_reference = str(receipt)
        order = payment.order
        if order and order.status in ['Awaiting Payment', 'Payment Failed']:
            assigned_driver, _, dispatch_error = assign_order_to_next_driver(order)
            if not assigned_driver:
                order.status = 'Pending'
                if dispatch_error:
                    payment.status_message = f"Payment successful. {dispatch_error}"[:255]
    else:
        payment.status = 'Failed'
        payment.status_message = f"{result_code}: {result_desc}"[:255]
        order = payment.order
        if order and order.status == 'Awaiting Payment':
            order.status = 'Payment Failed'
            order.driver_id = None

    db.session.commit()
    return jsonify({'ResultCode': 0, 'ResultDesc': 'Accepted'}), 200


# SocketIO events for real-time chat
@socketio.on('join_chat')
def handle_join_chat(data):
    order_id = data['order_id']
    room = f"order_{order_id}"
    join_room(room)
    emit('status', {'msg': f'{current_user.first_name} joined the chat'}, room=room)


@socketio.on('send_message')
def handle_send_message(data):
    order_id = data['order_id']
    message = data['message']
    room = f"order_{order_id}"
    
    # Get the order to determine receiver
    order = Order.query.get(order_id)
    if not order:
        return
    
    # Determine receiver based on sender's role
    if current_user.role == 'customer':
        receiver_id = order.driver_id
    else:  # driver
        receiver_id = order.customer_id
    
    # Save to database
    chat = Chat(order_id=order_id, sender_id=current_user.id, receiver_id=receiver_id, message=message)
    db.session.add(chat)
    db.session.commit()
    
    # Emit to room
    emit('receive_message', {
        'sender': current_user.first_name,
        'message': message,
        'timestamp': chat.timestamp.strftime('%H:%M')
    }, room=room)


@socketio.on('connect')
def handle_connect():
    if current_user.is_authenticated:
        online_users[current_user.id] = online_users.get(current_user.id, 0) + 1
        # Update last_seen
        current_user.last_seen = db.func.now()
        db.session.commit()
        
        # Broadcast online status once per user when they first appear online
        if online_users[current_user.id] == 1:
            if current_user.role == 'customer':
                orders = Order.query.filter_by(customer_id=current_user.id).all()
            else:
                orders = Order.query.filter_by(driver_id=current_user.id).all()
            for order in orders:
                room = f"order_{order.id}"
                socketio.emit('user_status_changed', {
                    'user_id': current_user.id,
                    'status': 'online',
                    'user_name': current_user.first_name
                }, room=room)
        
        print(f"User {current_user.first_name} connected. Online session count: {online_users[current_user.id]}")


@socketio.on('disconnect')
def handle_disconnect():
    if current_user.is_authenticated:
        current_count = online_users.get(current_user.id, 0)
        if current_count <= 1:
            online_users.pop(current_user.id, None)
            # Broadcast offline status when user has no remaining open sessions
            if current_user.role == 'customer':
                orders = Order.query.filter_by(customer_id=current_user.id).all()
            else:
                orders = Order.query.filter_by(driver_id=current_user.id).all()
            for order in orders:
                room = f"order_{order.id}"
                socketio.emit('user_status_changed', {
                    'user_id': current_user.id,
                    'status': 'offline',
                    'user_name': current_user.first_name
                }, room=room)
        else:
            online_users[current_user.id] = current_count - 1
        
        print(f"User {current_user.first_name} disconnected. Remaining sessions: {online_users.get(current_user.id, 0)}")
