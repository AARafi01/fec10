import os
from datetime import timedelta
from flask import Flask
from flask_compress import Compress

from app.extensions import config_service

# Import blueprints
from app.routes.main import main_bp
from app.routes.admin import admin_bp
from app.routes.api import api_bp

app = Flask(__name__, template_folder='../templates', static_folder='../static')
Compress(app)

app.secret_key = os.environ.get('SECRET_KEY') or config_service.get('SETTINGS', 'SECRET_KEY', 'rafi-sama-secret-key-2026-ducmc-scraper')
app.permanent_session_lifetime = timedelta(hours=24)

# Register blueprints
app.register_blueprint(main_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(api_bp)
