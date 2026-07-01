from app import db
from flask_login import UserMixin
from datetime import datetime

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(50))
    middle_name = db.Column(db.String(50))
    last_name = db.Column(db.String(50))
    email = db.Column(db.String(120), unique=True)
    password_hash = db.Column(db.String(200))
    phone = db.Column(db.String(20), nullable=True)  # Contact phone number
    role = db.Column(db.String(20))
    is_primary_admin = db.Column(db.Boolean, default=False)

    is_available = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(20), default='Pending')

    # For drivers
    license_number = db.Column(db.String(50), nullable=True)
    license_photo = db.Column(db.String(200), nullable=True)  # Path to uploaded photo
    license_approved = db.Column(db.Boolean, default=False)

    # For password reset
    reset_token = db.Column(db.String(100), nullable=True)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)

    def full_name(self):
        if self.middle_name:
            return f"{self.first_name} {self.middle_name} {self.last_name}"
        return f"{self.first_name} {self.last_name}"
    
    
class Material(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    price = db.Column(db.Float, nullable=False)
    discount_price = db.Column(db.Float, nullable=True)
    discount_start = db.Column(db.Date, nullable=True)
    discount_end = db.Column(db.Date, nullable=True)
    
    def __repr__(self):
        return f"<Material {self.name} - {self.price}>"
     
    
class Location(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    def __repr__(self):
        return f"<Location {self.name}>"


class Truck(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    registration_number = db.Column(db.String(20), unique=True, nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    driver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    status = db.Column(db.String(20), default='good')  # good, need_service, bad
    approval_status = db.Column(db.String(20), default='Pending')  # Pending, Approved, Rejected

    owner = db.relationship('User', foreign_keys=[owner_id], backref='owned_trucks')
    driver = db.relationship('User', foreign_keys=[driver_id], backref='assigned_truck')
class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    customer_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    driver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    material_id = db.Column(db.Integer, db.ForeignKey('material.id'))

    quantity = db.Column(db.Integer, nullable=False)
    total_price = db.Column(db.Float, nullable=False)

    status = db.Column(db.String(50), default='Pending')
    drop_location_id = db.Column(db.Integer, db.ForeignKey('location.id'), nullable=False)
    assigned_date = db.Column(db.DateTime, default=datetime.utcnow)
    driver_completed = db.Column(db.Boolean, default=False)  # Driver clicked complete
    completed_at = db.Column(db.DateTime, nullable=True)  # When driver marked complete
    admin_approved = db.Column(db.Boolean, default=False)  # Admin approved completion
    approved_at = db.Column(db.DateTime, nullable=True)  # When admin approved

    #  FIXED RELATIONSHIPS
    customer = db.relationship('User', foreign_keys=[customer_id], backref='customer_orders')
    driver = db.relationship('User', foreign_keys=[driver_id], backref='driver_orders')
    drop_location = db.relationship('Location')
    material = db.relationship('Material')


class DriverDispatchState(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(30), unique=True, nullable=False, default='main')
    next_driver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    next_driver = db.relationship('User', foreign_keys=[next_driver_id])


class DriverAssignmentLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    driver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    truck_id = db.Column(db.Integer, db.ForeignKey('truck.id'), nullable=True)
    status = db.Column(db.String(30), nullable=False, default='offered')  # offered, accepted, declined
    reason = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    responded_at = db.Column(db.DateTime, nullable=True)

    order = db.relationship('Order', backref='driver_assignment_logs')
    driver = db.relationship('User', foreign_keys=[driver_id])
    truck = db.relationship('Truck', foreign_keys=[truck_id])


class PaymentSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    paybill_number = db.Column(db.String(30), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(30), default='Pending')  # Pending, Pending Confirmation, Completed, Failed
    payment_method = db.Column(db.String(50), nullable=True)  # e.g., M-Pesa, Card
    transaction_id = db.Column(db.String(100), nullable=True)
    provider_reference = db.Column(db.String(120), nullable=True)  # e.g. MpesaReceiptNumber
    status_message = db.Column(db.String(255), nullable=True)
    paid_at = db.Column(db.DateTime, nullable=True)
    confirmed_by_admin_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    confirmed_at = db.Column(db.DateTime, nullable=True)

    order = db.relationship('Order', backref='payment')
    confirmed_by_admin = db.relationship('User', foreign_keys=[confirmed_by_admin_id])


class Chat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False)

    sender = db.relationship('User', foreign_keys=[sender_id])
    receiver = db.relationship('User', foreign_keys=[receiver_id])


class Rating(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)  # 1-5 stars
    comment = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_displayed = db.Column(db.Boolean, default=False)

    order = db.relationship('Order', backref='ratings')
    customer = db.relationship('User', backref='ratings')
     
     
     
