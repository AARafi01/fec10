import os
from datetime import timedelta
from flask import Flask, redirect, url_for
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

from datetime import datetime, timezone

def format_bd_time(value):
    if not value or value == 'N/A':
        return value
    
    dt = None
    if isinstance(value, str):
        try:
            dt = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            try:
                dt = datetime.strptime(value, '%Y-%m-%d %H:%M:%S.%f')
            except ValueError:
                return value
    elif isinstance(value, datetime):
        dt = value
    else:
        return value

    if dt:
        utc_dt = dt.replace(tzinfo=timezone.utc)
        bd_tz = timezone(timedelta(hours=6))
        bd_dt = utc_dt.astimezone(bd_tz)
        return bd_dt.strftime('%Y-%m-%d %I:%M:%S %p')
    return value

app.jinja_env.filters['bd_time'] = format_bd_time

app.register_blueprint(main_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(api_bp)

@app.errorhandler(404)
def page_not_found(e):
    return redirect(url_for('main.index'))
