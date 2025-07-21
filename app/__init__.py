import os
import logging
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_caching import Cache
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import atexit

logging.basicConfig(level=logging.INFO)

db = SQLAlchemy()
cache = Cache(config={'CACHE_TYPE': 'simple'})

def create_app():
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('SECRET_KEY', os.urandom(24).hex()),
        SQLALCHEMY_DATABASE_URI='sqlite:///' + os.path.join(app.instance_path, 'flaskr.sqlite'),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        CACHE_TYPE='simple'
    )

    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    db.init_app(app)
    cache.init_app(app)

    from .views import views_bp
    app.register_blueprint(views_bp)

    with app.app_context():
        db.create_all()

        scheduler = BackgroundScheduler()
        from .scraper import update_product_price
        def safe_update_product_price():
            try:
                update_product_price()
                logging.info("Price update completed successfully.", extra={'product': '', 'link': ''})
            except Exception as e:
                logging.error(f"Error during price update: {str(e)}", extra={'product': '', 'link': ''})

        scheduler.add_job(
            func=safe_update_product_price,
            trigger='interval',
            hours=24,
            next_run_time=datetime.now()
        )
        scheduler.start()
        atexit.register(lambda: scheduler.shutdown())

    return app