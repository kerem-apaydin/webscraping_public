import json
import os
import logging

import requests
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import re
from .database import ScrapedData, PriceHistory
from . import db
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from tenacity import retry, stop_after_attempt, wait_fixed
from typing import List, Optional, Dict, Any

# Configure logging
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s - [Product: %(product)s, Link: %(link)s]",
   
)

class Product:
    def __init__(self, title: str, price: float, link: str, image: str, brand: str, product_code: str, prev_price: Optional[float] = None):
        self.title = title
        self.price = price
        self.prev_price = prev_price
        self.link = link
        self.image = image
        self.brand = brand
        self.product_code = product_code

    def to_dict(self) -> Dict[str, Any]:
        """Convert product to dictionary."""
        return {
            "title": self.title,
            "price": self.price,
            "prev_price": self.prev_price,
            "link": self.link,
            "image": self.image,
            "brand": self.brand,
            "product_code": self.product_code
        }

class ProductScraper:
    def __init__(self, start_url: str):
        self.start_url = start_url
        self.base_url = start_url.split('?')[0]
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        self.seen_links = set()

    def fetch_all_products(self) -> List[Product]:
        """Fetch all products from the start URL, handling pagination."""
        all_products = []
        url = self.start_url
        page = 1

        while True:
            logging.info(f"Scraping page {page}...", extra={'product': '', 'link': url})
            try:
                response = requests.get(url, headers=self.headers, timeout=10)
                response.raise_for_status()
            except requests.RequestException as e:
                logging.error(f"Failed to load page {page}: {str(e)}", extra={'product': '', 'link': url})
                break

            soup = BeautifulSoup(response.text, "html.parser")
            products = self._extract_products_from_soup(soup)
            if not products:
                logging.info("No products found on this page, stopping.", extra={'product': '', 'link': url})
                break
            all_products.extend(products)
            logging.info(f"Found {len(products)} products on page {page}.", extra={'product': '', 'link': url})

            next_page_url = self._get_next_page_url(soup, url)
            if not next_page_url:
                logging.info("No next page link found, stopping.", extra={'product': '', 'link': url})
                break

            url = next_page_url
            page += 1

        return all_products

    def _get_next_page_url(self, soup: BeautifulSoup, current_url: str) -> Optional[str]:
        """Extract the next page URL from pagination links."""
        current_page_el = soup.select_one(".pagination .current")
        if not current_page_el:
            return None

        try:
            current_page = int(current_page_el.get_text(strip=True))
        except ValueError:
            logging.error("Invalid current page number, stopping.", extra={'product': '', 'link': current_url})
            return None

        pagination_links = soup.select(".pagination a")
        for link in pagination_links:
            try:
                page_num = int(link.get_text(strip=True))
                if page_num == current_page + 1:
                    return urljoin(current_url, link.get("href"))
            except ValueError:
                continue
        return None

    def _extract_products_from_soup(self, soup: BeautifulSoup) -> List[Product]:
        """Extract product details from the page's soup object."""
        products = []
        product_elements = soup.select(".product-item-holder")
        for el in product_elements:
            try:
                product = self._parse_product_element(el)
                if product and product.price is not None and product.link not in self.seen_links:
                    self.seen_links.add(product.link)
                    products.append(product)
                else:
                    logging.warning(f"Skipping product due to invalid data.", extra={'product': product.title if product else '', 'link': product.link if product else ''})
            except Exception as e:
                logging.warning(f"Error parsing product: {str(e)}", extra={'product': '', 'link': ''})
        return products

    def _parse_product_element(self, el: BeautifulSoup) -> Optional[Product]:
        """Parse a single product element."""
        title_el = el.select_one(".title a")
        if not title_el:
            return None
        title = title_el.get_text(strip=True) or "Unknown"
        link = urljoin("https://www.dmo.gov.tr/", title_el.get("href") or "")

        image_el = el.select_one(".image img")
        image = urljoin("https://www.dmo.gov.tr/", image_el.get("src") or "/static/images/no-image.jpg")

        price_el = el.select_one(".price-current")
        price_text = price_el.get_text(strip=True) if price_el else None
        price = self._parse_price(price_text) if price_text else None

        brand_el = el.select_one(".brand")
        brand_parts = brand_el.get_text(strip=True).split() if brand_el else []
        brand = brand_parts[0] if brand_parts else "Unknown"
        product_code = brand_el.select_one("span").get_text(strip=True) if brand_el and brand_el.select_one("span") else "-"

        return Product(title, price, link, image, brand, product_code) if price else None

    def _parse_price(self, price_text: str) -> Optional[float]:
        """Parse and normalize price text."""
        try:
            price_normalized = price_text.replace(".", "").replace(",", ".")
            price_clean = re.sub(r"[^\d.]", "", price_normalized)
            return float(price_clean) if price_clean else None
        except (ValueError, AttributeError):
            return None

class ProductPriceUpdater:
    def __init__(self, product: Product):
        self.product = product
        self.link = product.link
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
    def fetch_current_price(self) -> Optional[float]:
        """Fetch the current price of a product."""
        try:
            response = requests.get(self.link, headers=self.headers, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            price_element = soup.select_one(".price-current")
            price_text = price_element.get_text(strip=True) if price_element else None
            logging.info(f"Raw price text (update): {price_text}", extra={'product': self.product.title, 'link': self.link})

            return ProductScraper(self.link)._parse_price(price_text)
        except requests.RequestException as e:
            logging.error(f"Error fetching price: {str(e)}", extra={'product': self.product.title, 'link': self.link})
            raise

    def update_product_price(self) -> Optional[float]:
        """Update the product price and return the new price."""
        current_price = self.fetch_current_price()
        prev_price = self.product.price
        if current_price is None or prev_price == current_price:
            logging.info(f"No price change.", extra={'product': self.product.title, 'link': self.link})
            return None

        self.product.price = current_price
        self.product.prev_price = prev_price
        logging.info(f"Price updated. New price: {current_price}", extra={'product': self.product.title, 'link': self.link})
        return current_price

def update_product_price() -> None:
    """Update prices for all products in the database."""
    products = ScrapedData.query.all()
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(ProductPriceUpdater(Product(
            title=p.title,
            price=p.current_price,
            link=p.link,
            image=p.image,
            brand=p.brand,
            product_code=p.product_code,
            prev_price=p.prev_price
        )).update_product_price) for p in products]
        for future in futures:
            future.result()  # Wait for completion

class ProductSaver:
    def __init__(self, filename: str = "products.json"):
        self.filename = filename

    def save_to_json(self, products: List[Product]) -> None:
        """Save products to a JSON file."""
        try:
            file_path = os.path.join("data_files", self.filename)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump([p.to_dict() for p in products], f, ensure_ascii=False)
            logging.info(f"{len(products)} products saved to {self.filename}", extra={'product': '', 'link': ''})
        except Exception as e:
            logging.error(f"Error saving to JSON: {str(e)}", extra={'product': '', 'link': ''})

    def save_to_db(self, products: List[Product]) -> None:
        """Save products and their price histories to the database."""
        try:
            new_products = []
            price_histories = []
            for product in products:
                if product.price is None:
                    logging.warning(f"Skipping product due to invalid price: {product.title}", extra={'product': product.title, 'link': product.link})
                    continue
                existing_product = ScrapedData.query.filter_by(link=product.link).first()
                if existing_product:
                    if existing_product.current_price != product.price:
                        price_histories.append(
                            PriceHistory(
                                product_id=existing_product.id,
                                price=existing_product.current_price
                            )
                        )
                        existing_product.current_price = product.price
                        existing_product.prev_price = existing_product.current_price
                        existing_product.last_updated = datetime.utcnow()
                else:
                    new_products.append(
                        ScrapedData(
                            title=product.title,
                            current_price=product.price,
                            prev_price=product.prev_price,
                            link=product.link,
                            image=product.image,
                            brand=product.brand,
                            product_code=product.product_code,
                            last_updated=datetime.utcnow()
                        )
                    )
            db.session.add_all(new_products + price_histories)
            db.session.commit()
            logging.info(f"Saved {len(new_products)} new products and {len(price_histories)} price histories to database.", extra={'product': '', 'link': ''})
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error saving to database: {str(e)}", extra={'product': '', 'link': ''})

def scrape_from_user_url(url: str) -> Dict[str, str]:
    """Scrape products from the given URL and save them."""
    try:
        scraper = ProductScraper(url)
        products = scraper.fetch_all_products()
        saver = ProductSaver()
        saver.save_to_json(products)
        saver.save_to_db(products)
        return {"status": "success", "message": f"{len(products)} products scraped and saved successfully."}
    except Exception as e:
        logging.error(f"Error processing URL {url}: {str(e)}", extra={'product': '', 'link': url})
        return {"status": "error", "message": f"Error: {str(e)}"}