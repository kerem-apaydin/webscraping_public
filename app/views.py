from flask import Blueprint, render_template, request, flash, redirect, url_for
from .database import ScrapedData, PriceHistory
from .scraper import scrape_from_user_url
from markupsafe import escape
from . import cache

views_bp = Blueprint('views', __name__)

@cache.cached(timeout=3600, key_prefix='brands')
def get_brands():
    brands = ScrapedData.query.with_entities(ScrapedData.brand).distinct().all()
    return [b[0] for b in brands if b[0]]

@views_bp.route('/', methods=['GET', 'POST'])
def home():
    if request.method == 'POST':
        url = request.form.get('scrape_url')
        if url:
            result = scrape_from_user_url(url)
            flash(result['message'], 'success' if result['status'] == 'success' else 'danger')
            return redirect(url_for('views.home'))

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    search = escape(request.args.get('search', '', type=str))
    brand = escape(request.args.get('brand', '', type=str))
    
    query = ScrapedData.query
    if search:
        query = query.filter(ScrapedData.title.ilike(f'%{search}%'))
    if brand:
        query = query.filter(ScrapedData.brand == brand)
    
    products = query.paginate(page=page, per_page=per_page)
    brands = get_brands()
    
    return render_template('index.html', products=products, brands=brands, search=search, brand=brand, per_page=per_page)

@views_bp.route('/toggle_view', methods=['POST'])
def toggle_view():
    toggle_view = request.form.get('toggleView', 'disabled')
    if toggle_view == 'enabled':
        toggle_view = 'disabled'
    else:
        toggle_view = 'enabled'
    
    return redirect(url_for('views.home', toggleView=toggle_view))

@views_bp.route('/product/<int:id>')
def product_detail(id):
    product = ScrapedData.query.get_or_404(id)
    price_history = PriceHistory.query.filter_by(product_id=id).order_by(PriceHistory.timestamp.desc()).all()
    return render_template('product_detail.html', product=product, price_history=price_history)

@views_bp.route('/brand/<string:brand>')
def brand_products(brand):
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    search = escape(request.args.get('search', '', type=str))
    brand = escape(brand)
    
    query = ScrapedData.query.filter_by(brand=brand)
    if search:
        query = query.filter(ScrapedData.title.ilike(f'%{search}%'))
    
    products = query.paginate(page=page, per_page=per_page)
    brands = get_brands()
    
    return render_template('index.html', products=products, brands=brands, search=search, brand=brand, per_page=per_page)