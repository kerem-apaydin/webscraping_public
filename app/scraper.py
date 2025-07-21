import json
import time
import os
import logging
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, ElementClickInterceptedException, TimeoutException
from webdriver_manager.chrome import ChromeDriverManager
from .database import ScrapedData, PriceHistory
from . import db
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from tenacity import retry, stop_after_attempt, wait_fixed
import gzip

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
    def __init__(self, start_url, driver=None):
        self.start_url = start_url
        if driver is None:
            options = Options()
            options.add_argument("--headless")
            options.add_argument("--disable-gpu")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-notifications")
            options.add_argument("--log-level=3")
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=options)
        else:
            self.driver = driver
        self.wait = WebDriverWait(self.driver, 10)
        self.seen_links = set()

    def fetch_all_products(self):
        all_products = []
        self.driver.get(self.start_url)
        page = 1

        while True:
            logging.info(f"Scraping page {page}...", extra={'product': '', 'link': ''})
            products = self._extract_products_from_page()
            if not products:
                logging.info("No products found on this page, stopping.", extra={'product': '', 'link': ''})
                break
            all_products.extend(products)
            logging.info(f"Found {len(products)} products on page {page}.", extra={'product': '', 'link': ''})

            try:
                pagination = self.wait.until(EC.presence_of_element_located((By.CLASS_NAME, "pagination")))
                next_page_button = None
                pages = pagination.find_elements(By.TAG_NAME, "li")
                
                for li in pages:
                    try:
                        a = li.find_element(By.TAG_NAME, "a")
                        if a.text.strip() == str(page + 1):
                            next_page_button = a
                            break
                    except NoSuchElementException:
                        continue

                if next_page_button:
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_page_button)
                    time.sleep(1)
                    self.wait.until(EC.element_to_be_clickable(next_page_button)).click()
                    page += 1
                    time.sleep(2)
                else:
                    logging.info("No next page found, stopping.", extra={'product': '', 'link': ''})
                    break
            except (TimeoutException, ElementClickInterceptedException, NoSuchElementException) as e:
                logging.error(f"Error navigating pagination: {str(e)}", extra={'product': '', 'link': ''})
                break

        return all_products

    def _extract_products_from_page(self):
        products = []
        try:
            product_elements = self.wait.until(
                EC.presence_of_all_elements_located((By.CLASS_NAME, "product-item-holder"))
            )
            for el in product_elements:
                try:
                    title_el = el.find_element(By.CLASS_NAME, "title").find_element(By.TAG_NAME, "a")
                    title = title_el.text.strip()
                    link = title_el.get_attribute("href")
                    
                    if link in self.seen_links:
                        continue
                    self.seen_links.add(link)

                    image_el = el.find_element(By.CLASS_NAME, "image").find_element(By.TAG_NAME, "img")
                    image = image_el.get_attribute("src") or "/static/images/no-image.jpg"
                    price = el.find_element(By.CLASS_NAME, "price-current").text.strip()
                    brand_el = el.find_element(By.CLASS_NAME, "brand")
                    brand_text = brand_el.text.split()
                    brand = brand_text[0] if brand_text else "Unknown"
                    product_code = brand_el.find_element(By.TAG_NAME, "span").text.strip() if brand_el.find_elements(By.TAG_NAME, "span") else "-"
                    products.append(Product(title, price, link, image, brand, product_code))
                except NoSuchElementException:
                    logging.warning(f"Skipping product due to missing elements.", extra={'product': title if 'title' in locals() else '', 'link': link if 'link' in locals() else ''})
                    continue
        except TimeoutException:
            logging.error("Failed to load products on this page.", extra={'product': '', 'link': ''})
        return products

class ProductPriceUpdater:
    def __init__(self, product, driver=None):
        self.product = product
        self.previous_price = product.price
        if driver is None:
            options = Options()
            options.add_argument("--headless")
            options.add_argument("--disable gpus")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-notifications")
            options.add_argument("--log-level=3")
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=options)
        else:
            self.driver = driver
        self.link = self.product.link
        self.wait = WebDriverWait(self.driver, 10)

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
    def fetch_current_price(self):
        try:
            self.driver.get(self.link)
            price_element = self.wait.until(
                EC.presence_of_element_located((By.CLASS_NAME, "price-prev"))
            )
            current_price = price_element.text.strip()
            if not current_price:
                logging.warning(f"No price found.", extra={'product': self.product.title, 'link': self.link})
                return None
            return current_price
        except TimeoutException:
            logging.error(f"Timeout while fetching price.", extra={'product': self.product.title, 'link': self.link})
            raise

    def update_product_price(self):
        current_price = self.fetch_current_price()
        prev_price = self.product.price
        if not current_price:
            return None
        
        if current_price and prev_price == current_price:
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
            file_path = os.path.join("..", "data_files", self.filename + '.gz')
            if not os.path.exists(os.path.dirname(file_path)):
                os.makedirs(os.path.dirname(file_path))
            with gzip.open(file_path, "wt", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            logging.info(f"{len(products)} products saved to {self.filename}.gz", extra={'product': '', 'link': ''})
        except Exception as e:
            logging.error(f"Error saving to JSON: {str(e)}", extra={'product': '', 'link': ''})

    def save_to_db(self, products):
        try:
            new_products = []
            price_histories = []
            for product in products:
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
            logging.info(f"Saved {len(products)} products to database.", extra={'product': '', 'link': ''})
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error saving to database: {str(e)}", extra={'product': '', 'link': ''})

def scrape_from_user_url(url):
    try:
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-notifications")
        options.add_argument("--log-level=3")
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        
        scraper = ProductScraper(url, driver=driver)
        products = scraper.fetch_all_products()
        saver = ProductSaver()
        saver.save_to_json(products)
        saver.save_to_db(products)
        
        driver.quit()
        return {"status": "success", "message": f"{len(products)} products scraped and saved successfully."}
    except Exception as e:
        logging.error(f"Error processing URL {url}: {str(e)}", extra={'product': '', 'link': url})
        return {"status": "error", "message": f"Error: {str(e)}"}

def update_product_price():
    products = ScrapedData.query.all()
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-notifications")
    options.add_argument("--log-level=3")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    
    try:
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(ProductPriceUpdater(product, driver=driver).update_product_price) for product in products]
            for future in futures:
                future.result()
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error during price update: {str(e)}", extra={'product': '', 'link': ''})
    finally:
        driver.quit()