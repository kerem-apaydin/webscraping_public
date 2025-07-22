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

# Configure logging
logging.basicConfig(
    filename="scraper.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s - [Product: %(product)s, Link: %(link)s]",
    encoding="utf-8"
)

class Product:
    def __init__(self, title, price, link, image, brand, product_code, prev_price=None):
        self.title = title
        self.price = price
        self.prev_price = prev_price
        self.link = link
        self.image = image
        self.brand = brand
        self.product_code = product_code

    def to_dict(self):
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
    def __init__(self, start_url):
        self.start_url = start_url
        self.base_url = start_url.split('?')[0]
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        self.seen_links = set()

    def fetch_all_products(self):
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

            current_page_el = soup.select_one(".pagination .current")
            if not current_page_el:
                logging.info("No current page element found, stopping.", extra={'product': '', 'link': url})
                break

            try:
                current_page = int(current_page_el.get_text(strip=True))
            except ValueError:
                logging.error("Invalid current page number, stopping.", extra={'product': '', 'link': url})
                break

            pagination_links = soup.select(".pagination a")
            next_page_url = None
            for link in pagination_links:
                try:
                    page_num = int(link.get_text(strip=True))
                    if page_num == current_page + 1:
                        next_page_url = link.get("href")
                        break
                except ValueError:
                    continue

            if not next_page_url:
                logging.info("No next page link found, stopping.", extra={'product': '', 'link': url})
                break

            next_page_url = urljoin(url, next_page_url)
            url = next_page_url
            page += 1

        return all_products

    def _extract_products_from_soup(self, soup):
        products = []
        product_elements = soup.select(".product-item-holder")
        for el in product_elements:
            try:
                title_el = el.select_one(".title a")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True) or "Unknown"
                link = title_el.get("href")
                if not link:
                    logging.warning(f"Skipping product due to missing link.", extra={'product': title, 'link': ''})
                    continue
                link = urljoin("https://www.dmo.gov.tr/", link)  

                if link in self.seen_links:
                    continue
                self.seen_links.add(link)

                image_el = el.select_one(".image img")
                image = image_el.get("src") if image_el else "/static/images/no-image.jpg"
                image = urljoin("https://www.dmo.gov.tr/", image)  # Resolve relative image URL

                price_el = el.select_one(".price-current")
                price_text = price_el.get_text(strip=True) if price_el else None
                price_normalized = price_text.replace(".", "").replace(",", ".") if price_text else ""
                price_clean = re.sub(r"[^\d.]", "", price_normalized)
                price = float(price_clean) if price_clean else None

                brand_el = el.select_one(".brand")
                brand_parts = brand_el.get_text(strip=True).split() if brand_el else []
                brand = brand_parts[0] if brand_parts else "Unknown"
                product_code = brand_el.select_one("span").get_text(strip=True) if brand_el and brand_el.select_one("span") else "-"

                if price is not None:
                    products.append(Product(title, price, link, image, brand, product_code))
                else:
                    logging.warning(f"Skipping product due to invalid price.", extra={'product': title, 'link': link})
            except Exception as e:
                logging.warning(f"Error parsing product: {str(e)}", extra={'product': title if 'title' in locals() else '', 'link': link if 'link' in locals() else ''})
                continue
        return products

class ProductPriceUpdater:
    def __init__(self, product):
        self.product = product
        self.previous_price = product.price
        self.link = product.link
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
    def fetch_current_price(self):
        try:
            response = requests.get(self.link, headers=self.headers, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            price_element = soup.select_one(".price-current")
            price_text = price_element.get_text(strip=True) if price_element else None
            logging.info(f"Raw price text (update): {price_text}", extra={'product': self.product.title, 'link': self.link})

            if not price_text:
                logging.warning(f"No price found.", extra={'product': self.product.title, 'link': self.link})
                return None
            price_normalized = price_text.replace(".", "").replace(",", ".") if price_text else ""
            price_clean = re.sub(r"[^\d.]", "", price_normalized)
            price = float(price_clean) if price_clean else None
            return price
        except requests.RequestException as e:
            logging.error(f"Error fetching price: {str(e)}", extra={'product': self.product.title, 'link': self.link})
            raise

    def update_product_price(self):
        current_price = self.fetch_current_price()
        prev_price = self.product.price
        if current_price is None:
            logging.info(f"No price change (no valid price found).", extra={'product': self.product.title, 'link': self.link})
            return None

        if prev_price == current_price:
            logging.info(f"No price change.", extra={'product': self.product.title, 'link': self.link})
            return None

        self.product.price = current_price
        self.product.prev_price = prev_price
        logging.info(f"Price updated. New price: {current_price}", extra={'product': self.product.title, 'link': self.link})
        return current_price

class ProductSaver:
    def __init__(self, filename="products.json"):
        self.filename = filename

    def save_to_json(self, products):
        data = [p.to_dict() for p in products]
        try:
            file_path = os.path.join("data_files", self.filename)
            if not os.path.exists(os.path.dirname(file_path)):
                os.makedirs(os.path.dirname(file_path))
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            logging.info(f"{len(products)} products saved to {self.filename}", extra={'product': '', 'link': ''})
        except Exception as e:
            logging.error(f"Error saving to JSON: {str(e)}", extra={'product': '', 'link': ''})

    def save_to_db(self, products):
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
                        existing_product.last_updated = datetime.utcnow()
                else:
                    new_products.append(
                        ScrapedData(
                            title=product.title,
                            current_price=product.price,
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

def scrape_from_user_url(url):
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

def update_product_price():
    def update_single_product(product):
        try:
            updater = ProductPriceUpdater(product)
            updated_price = updater.update_product_price()
            if updated_price is not None:
                existing_product = ScrapedData.query.filter_by(link=product.link).first()
                if existing_product:
                    if existing_product.current_price != updated_price:
                        price_history = PriceHistory(
                            product_id=existing_product.id,
                            price=existing_product.current_price
                        )
                        existing_product.current_price = updated_price
                        existing_product.last_updated = datetime.utcnow()
                        db.session.add(price_history)
        except Exception as e:
            logging.error(f"Error updating product price: {str(e)}", extra={'product': product.title, 'link': product.link})

    try:
        products = ScrapedData.query.all()
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(update_single_product, product) for product in products]
            for future in futures:
                future.result()
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error during price update: {str(e)}", extra={'product': '', 'link': ''})