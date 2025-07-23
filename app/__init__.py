import os
import logging
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_caching import Cache
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import atexit
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        
    ]
)

db = SQLAlchemy()
cache = Cache(config={'CACHE_TYPE': 'simple'})

def create_app() -> Flask:
    """Initialize and configure the Flask application."""
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('SECRET_KEY', os.urandom(24).hex()),
        SQLALCHEMY_DATABASE_URI=os.environ.get('DATABASE_URL', f'sqlite:///{os.path.join(app.instance_path, "flaskr.sqlite")}'),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        CACHE_TYPE='simple',
        DEBUG=os.environ.get('FLASK_ENV', 'production') == 'development',
        PORT=int(os.environ.get('PORT', 5000))
    )

    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except OSError as e:
        logging.error(f"Failed to create instance path: {str(e)}")

    db.init_app(app)
    cache.init_app(app)

    from .views import views_bp
    app.register_blueprint(views_bp)

    with app.app_context():
        db.create_all()

        scheduler = BackgroundScheduler()
        from .scraper import update_product_price
        from .database import clean_old_data

        def safe_update_product_price():
            """Safely update product prices and log outcomes."""
            with app.app_context():
                try:
                    update_product_price()
                    logging.info("Price update job completed successfully.")
                    clean_old_data()  # Clean old data after updating
                except Exception as e:
                    logging.error(f"Error during price update job: {str(e)}")

        if not scheduler.running:
            scheduler.add_job(
                func=safe_update_product_price,
                trigger='interval',
                hours=24,
                next_run_time=datetime.now(),
                max_instances=1
            )
            scheduler.start()
            atexit.register(lambda: scheduler.shutdown())

    return app