from . import db
from datetime import datetime, timedelta
from sqlalchemy import Numeric
from typing import Optional

class ScrapedData(db.Model):
    __tablename__ = 'scraped_data'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False, index=True)
    current_price = db.Column(Numeric(10, 2), nullable=False)
    # prev_price = db.Column(Numeric(10, 2), nullable=True)
    link = db.Column(db.String(500), nullable=False, unique=True, index=True)
    image = db.Column(db.String(500), nullable=True)
    brand = db.Column(db.String(100), nullable=True, index=True)
    product_code = db.Column(db.String(100), nullable=True, index=True)
    last_updated = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    prices = db.relationship('PriceHistory', backref='product', lazy='dynamic')

    def __repr__(self) -> str:
        return f"<ScrapedData {self.title}>"

class PriceHistory(db.Model):
    __tablename__ = 'price_history'
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('scraped_data.id'), nullable=False, index=True)
    price = db.Column(Numeric(10, 2), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    def __repr__(self) -> str:
        return f"<PriceHistory {self.price} at {self.timestamp}>"

def clean_old_data(threshold_seconds: int = 3) -> None:
    """Remove records older than the specified threshold."""
    try:
        threshold = datetime.utcnow() - timedelta(seconds=threshold_seconds)
        deleted = ScrapedData.query.filter(ScrapedData.last_updated < threshold).delete()
        db.session.commit()
        if deleted:
            print(f"Deleted {deleted} old records.")
    except Exception as e:
        db.session.rollback()
        print(f"Error cleaning old data: {str(e)}")