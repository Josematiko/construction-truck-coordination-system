from app import create_app, db
from app.models import User
from werkzeug.security import generate_password_hash

app = create_app()

with app.app_context():
    # Check if admin already exists
    existing_admin = User.query.filter_by(email='admin@example.com').first()
    if existing_admin:
        print("Admin user already exists!")
    else:
        admin = User(
            first_name='Admin',
            last_name='Admin',
            email='admin@example.com',
            password_hash=generate_password_hash('admin123!'),
            role='admin',
            is_available=True,
            status='Active'
        )
        db.session.add(admin)
        db.session.commit()
        print("Admin user added successfully!")