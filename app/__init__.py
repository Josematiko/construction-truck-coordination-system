from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_socketio import SocketIO

db = SQLAlchemy()          # ✅ define db first
migrate = Migrate()
login_manager = LoginManager()
socketio = SocketIO()

# Global online session counters keyed by user ID
online_users = {}

def create_app():
    app = Flask(__name__)
    app.config.from_object('config.Config')

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    socketio.init_app(app, async_mode="gevent", cors_allowed_origins="*")
    # Import models here (after db is defined)
    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Import and register blueprints inside the function
    from app.routes.auth import auth
    from app.routes.admin import admin
    from app.routes.driver import driver
    from app.routes.customer import customer
    from app.routes.owner import owner

    app.register_blueprint(auth)
    app.register_blueprint(admin)
    app.register_blueprint(driver)
    app.register_blueprint(customer)
    app.register_blueprint(owner)

    return app