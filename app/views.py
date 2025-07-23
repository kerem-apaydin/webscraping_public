from flask import Blueprint, render_template, request, flash, redirect, url_for
from .database import ScrapedData, PriceHistory
from .scraper import scrape_from_user_url
from markupsafe import escape
from . import cache
from typing import List, Optional

views_bp = Blueprint('views', __name__)

@cache.cached(timeout=3600, key_prefix='brands')
def get_brands() -> List[str]:
    """Retrieve distinct brands from the database."""
    brands = ScrapedData.query.with_entities(ScrapedData.brand).distinct().all()
    return [b[0] for b in brands if b[0]]

def clear_brands_cache() -> None:
    """Clear the brands cache."""
    cache.delete('brands')

@views_bp.route('/', methods=['GET', 'POST'])
def home():
    """Handle the homepage with product listing and URL scraping."""
    if request.method == 'POST':
        url = request.form.get('scrape_url', '').strip()
        if not url.startswith(('http://', 'https://')):
            flash('Invalid URL provided.', 'danger')
            return redirect(url_for('views.home'))
        try:
            result = scrape_from_user_url(url)
            clear_brands_cache()
            flash(result['message'], 'success' if result['status'] == 'success' else 'danger')
        except Exception as e:
            flash(f'Error processing URL: {str(e)}', 'danger')
        return redirect(url_for('views.home'))

    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 10, type=int), 100)  # Limit max per_page
    search = escape(request.args.get('search', '', type=str).strip())
    brand = escape(request.args.get('brand', '', type=str).strip())
    toggle_view = request.args.get('toggleView', 'disabled')

    query = ScrapedData.query
    if search:
        query = query.filter(ScrapedData.title.ilike(f'%{search}%'))
    if brand:
        query = query.filter(ScrapedData.brand == brand)

    products = query.select_from(ScrapedData).paginate(page=page, per_page=per_page, error_out=False)
    brands = get_brands()

    return render_template(
        'index.html',
        products=products,
        brands=brands,
        search=search,
        brand=brand,
        per_page=per_page,
        toggle_view=toggle_view
    )

@views_bp.route('/toggle_view', methods=['POST'])
def toggle_view():
    """Toggle the view mode between enabled and disabled."""
    toggle_view = request.form.get('toggleView', 'disabled')
    toggle_view = 'disabled' if toggle_view == 'enabled' else 'enabled'
    return redirect(url_for(
        'views.home',
        toggleView=toggle_view,
        search=request.args.get('search', ''),
        brand=request.args.get('brand', ''),
        per_page=request.args.get('per_page', 10)
    ))

@views_bp.route('/product/<int:id>')
def product_detail(id: int):
    """Display product details and price history."""
    product = ScrapedData.query.get_or_404(id)
    price_history = PriceHistory.query.filter_by(product_id=id).order_by(PriceHistory.timestamp.desc()).all()
    return render_template('product_detail.html', product=product, price_history=price_history)

@views_bp.route('/brand/<string:brand>')
def brand_products(brand: str):
    """Display products filtered by brand."""
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 10, type=int), 100)
    search = escape(request.args.get('search', '', type=str).strip())
    brand = escape(brand.strip())
    toggle_view = request.args.get('toggleView', 'disabled')

    query = ScrapedData.query.filter_by(brand=brand)
    if search:
        query = query.filter(ScrapedData.title.ilike(f'%{search}%'))

    products = query.paginate(page=page, per_page=per_page, error_out=False)
    brands = get_brands()

    return render_template(
        'index.html',
        products=products,
        brands=brands,
        search=search,
        brand=brand,
        per_page=per_page,
        toggle_view=toggle_view
    )