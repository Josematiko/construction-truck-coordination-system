from datetime import datetime

from sqlalchemy import or_

from app import db
from app.models import DriverAssignmentLog, DriverDispatchState, Order, Truck, User


FINAL_ORDER_STATUSES = ('Completed', 'Rejected')


def get_or_create_dispatch_state():
    state = DriverDispatchState.query.filter_by(key='main').first()
    if not state:
        state = DriverDispatchState(key='main')
        db.session.add(state)
        db.session.flush()
    return state


def _eligible_drivers_with_trucks():
    drivers = (
        User.query
        .filter(User.role == 'driver', User.license_approved.is_(True))
        .filter(or_(User.status.is_(None), User.status != 'Rejected'))
        .order_by(User.id.asc())
        .all()
    )

    approved_trucks = (
        Truck.query
        .filter(Truck.driver_id.isnot(None), Truck.approval_status == 'Approved')
        .order_by(Truck.id.asc())
        .all()
    )

    trucks_by_driver = {}
    for truck in approved_trucks:
        # Keep the first approved truck if bad data has duplicates.
        trucks_by_driver.setdefault(truck.driver_id, truck)

    eligible_drivers = [driver for driver in drivers if driver.id in trucks_by_driver]
    return eligible_drivers, trucks_by_driver


def _driver_has_incomplete_job(driver_id, exclude_order_id=None):
    query = Order.query.filter(
        Order.driver_id == driver_id,
        Order.status.notin_(FINAL_ORDER_STATUSES)
    )
    if exclude_order_id is not None:
        query = query.filter(Order.id != exclude_order_id)
    return query.first() is not None


def get_declined_driver_ids(order_id):
    rows = (
        DriverAssignmentLog.query
        .with_entities(DriverAssignmentLog.driver_id)
        .filter_by(order_id=order_id, status='declined')
        .all()
    )
    return {row[0] for row in rows if row[0] is not None}


def mark_latest_offer_response(order_id, driver_id, status, reason=None):
    log = (
        DriverAssignmentLog.query
        .filter_by(order_id=order_id, driver_id=driver_id, status='offered')
        .order_by(DriverAssignmentLog.created_at.desc())
        .first()
    )
    if log:
        log.status = status
        log.reason = reason
        log.responded_at = datetime.utcnow()
    return log


def assign_order_to_next_driver(order, exclude_driver_ids=None):
    excluded = set(exclude_driver_ids or [])
    drivers, trucks_by_driver = _eligible_drivers_with_trucks()

    if not drivers:
        order.driver_id = None
        order.status = 'Pending'
        return None, None, "No approved drivers with assigned trucks are currently available."

    state = get_or_create_dispatch_state()
    ordered_driver_ids = [driver.id for driver in drivers]
    if state.next_driver_id in ordered_driver_ids:
        start_idx = ordered_driver_ids.index(state.next_driver_id)
    else:
        start_idx = 0

    chosen_idx = None
    for step in range(len(drivers)):
        idx = (start_idx + step) % len(drivers)
        candidate = drivers[idx]
        if candidate.id in excluded:
            continue
        if _driver_has_incomplete_job(candidate.id, exclude_order_id=order.id):
            continue
        chosen_idx = idx
        break

    if chosen_idx is None:
        if state.next_driver_id not in ordered_driver_ids:
            state.next_driver_id = ordered_driver_ids[0]
        order.driver_id = None
        order.status = 'Pending'
        return None, None, "No free drivers are currently available. Your order is waiting for assignment."

    chosen_driver = drivers[chosen_idx]
    chosen_truck = trucks_by_driver.get(chosen_driver.id)

    next_idx = (chosen_idx + 1) % len(drivers)
    state.next_driver_id = ordered_driver_ids[next_idx]

    order.driver_id = chosen_driver.id
    order.status = 'Pending Driver Response'

    log = DriverAssignmentLog(
        order_id=order.id,
        driver_id=chosen_driver.id,
        truck_id=chosen_truck.id if chosen_truck else None,
        status='offered'
    )
    db.session.add(log)

    return chosen_driver, chosen_truck, None


def assign_waiting_orders(limit=25):
    waiting_orders = (
        Order.query
        .filter(Order.status == 'Pending', Order.driver_id.is_(None))
        .order_by(Order.assigned_date.asc(), Order.id.asc())
        .limit(limit)
        .all()
    )

    assigned_count = 0
    for order in waiting_orders:
        declined_driver_ids = get_declined_driver_ids(order.id)
        assigned_driver, _, _ = assign_order_to_next_driver(
            order,
            exclude_driver_ids=declined_driver_ids
        )
        if assigned_driver:
            assigned_count += 1

    return assigned_count
