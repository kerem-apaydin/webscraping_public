from . import db
from datetime import datetime, timedelta
from sqlalchemy import Numeric

class ScrapedData(db.Model):
    __tablename__ = 'scraped_data'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    current_price = db.Column(Numeric(10, 2), nullable=False)
    link = db.Column(db.String(500), nullable=False, unique=True, index=True)
    image = db.Column(db.String(500), nullable=True)
    brand = db.Column(db.String(100), nullable=True, index=True)
    product_code = db.Column(db.String(100), nullable=True, index=True)
    last_updated = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    prices = db.relationship('PriceHistory', backref='product', lazy=True)

    def __repr__(self):
        return f"<ScrapedData {self.title}>"

class PriceHistory(db.Model):
    __tablename__ = 'price_history'
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('scraped_data.id'), nullable=False)
    price = db.Column(Numeric(10, 2), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f"<PriceHistory {self.price} at {self.timestamp}>"

def clean_old_data(threshold_days=30):
    threshold = datetime.utcnow() - timedelta(days=threshold_days)
    ScrapedData.query.filter(ScrapedData.last_updated < threshold).delete()
    db.session.commit()