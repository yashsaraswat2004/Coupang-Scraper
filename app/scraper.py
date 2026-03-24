"""Scraper module for extracting product data from e-commerce websites."""
import json
import os
import re
import random
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .helpers import clean_text, extract_price, build_search_url
from .excel_utils import build_excel

# ─────────────────────────────────────────────────────────────────────────────
# PLAYWRIGHT FETCH  (real browser — handles JS + most bot-checks)
# ─────────────────────────────────────────────────────────────────────────────
def fetch_with_playwright(url, wait_sec=4):
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--window-size=1366,768',
                ]
            )
            ctx = browser.new_context(
                viewport={'width': 1366, 'height': 768},
                user_agent=(
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/122.0.0.0 Safari/537.36'
                ),
                locale='en-IN',
                timezone_id='Asia/Kolkata',
                extra_http_headers={
                    'Accept-Language': 'en-IN,en;q=0.9',
                    'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8',
                }
            )
            # Hide webdriver flag
            ctx.add_init_script("""
                Object.defineProperty(navigator,'webdriver',{get:()=>undefined});
                window.chrome={runtime:{}};
                Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3]});
                Object.defineProperty(navigator,'languages',{get:()=>['en-IN','en']});
            """)
            pg = ctx.new_page()
            pg.goto(url, wait_until='domcontentloaded', timeout=35000)
            pg.wait_for_timeout(wait_sec * 1000)
            # Scroll to trigger lazy-loads
            pg.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.6)")
            pg.wait_for_timeout(1500)
            html = pg.content()
            browser.close()
            return html
    except Exception as e:
        print(f"[Playwright] Error: {e}")
        return None

# ─────────────────────────────────────────────────────────────────────────────
# PRODUCT CONTAINER SELECTORS (Organized by platform for scalability)
# ─────────────────────────────────────────────────────────────────────────────
PLATFORM_SELECTORS = {
    'amazon': [
        'div[data-component-type="s-search-result"]',
        'div[data-asin]',
    ],
    'flipkart': [
        'div._1AtVbE',
        'div._13oc-S',
        'div.tUxRFH',
        'div._2kHMtA',
    ],
    'nykaa': [
        'div.product-list__item',
        'div[class*="productCard"]',
        'div.css-16y7hct',
    ],
    'meesho': [
        'div[class*="ProductCard"]',
    ],
    'snapdeal': [
        'li.product-tuple-listing',
    ],
    'ajio': [
        'div[class*="rilrtl-products-list__item"]',
        'article[class*="product"]',
    ],
    'ebay': [
        'li.s-item',
        'div.s-item__wrapper',
    ],
    'walmart': [
        'div[data-item-id]',
    ],
    'myntra': [
        'li.product-base',
        'div[class*="product-productMetaInfo"]',
    ],
}

GENERIC_SELECTORS = [
    '[class*="product-card"]',
    '[class*="product-item"]',
    '[class*="product-tile"]',
    '[class*="ProductCard"]',
    '[class*="item-card"]',
    '[class*="search-result"]',
    '[class*="listing-item"]',
    '[class*="product_card"]',
    '[class*="goods-item"]',
    '[data-testid*="product"]',
    'li[class*="product"]',
]


def get_selectors_for_url(url):
    """Get ordered list of selectors based on URL domain."""
    url_lower = url.lower()
    selectors = []
    
    # Add platform-specific selectors first
    for platform, platform_sels in PLATFORM_SELECTORS.items():
        if platform in url_lower:
            selectors.extend(platform_sels)
            break
    
    # Add all other platform selectors
    for platform, platform_sels in PLATFORM_SELECTORS.items():
        if platform not in url_lower:
            selectors.extend(platform_sels)
    
    # Add generic selectors last
    selectors.extend(GENERIC_SELECTORS)
    
    return selectors

def extract_products_from_soup(soup, base_url):
    """Extract product containers from page HTML."""
    containers = []
    selectors = get_selectors_for_url(base_url)
    
    for sel in selectors:
        found = [f for f in soup.select(sel) if len(f.get_text(strip=True)) > 20]
        if len(found) >= 2:
            containers = found
            break

    # Fallback: frequency-based detection
    if not containers:
        price_re = re.compile(r'[\$₹€£¥]\s*\d+|\bprice\b', re.I)
        freq = {}
        for tag in soup.find_all(['div', 'li', 'article'], class_=True):
            txt = tag.get_text()
            if price_re.search(txt) and 30 < len(txt.strip()) < 1200:
                key = tuple(sorted(tag.get('class', [])))
                freq.setdefault(key, []).append(tag)
        if freq:
            best = max(freq.values(), key=len)
            if len(best) >= 2:
                containers = best[:100]

    products = []
    for c in containers[:100]:
        p = extract_single_product(c, base_url)
        if p and p.get('Product Name'):
            products.append(p)
    return products

def _pick(container, selectors, transform=None):
    """Pick first matching selector value from container."""
    for sel in selectors:
        el = container.select_one(sel)
        if el:
            val = clean_text(el.get_text()) if transform is None else transform(el)
            if val:
                return val
    return ''

def extract_single_product(c, base_url):
    """Extract product data from a single product container."""
    # Skip sponsored/ad products
    sponsored_selectors = [
        '.s-sponsored-label-text',
        '.s-sponsored-info-icon',
        '.puis-sponsored-label-text',
        '.ad-label',
        'span:-soup-contains("Sponsored")',
    ]
    for sel in sponsored_selectors:
        if c.select_one(sel):
            return None

    # Generic text check for sponsored badges
    badges = c.select('.a-badge-text, [class*="badge"], [class*="label"], [class*="tag"], span')
    for badge in badges:
        btxt = badge.get_text().strip()
        if btxt.lower() in ('sponsored', 'ad') or 'sponsored' in btxt.lower():
            if len(btxt) < 20:
                return None

    # Initialize product with exact CSV template schema
    p = {
        'Category': '',
        'Product Name': '',
        'Brand': '',
        'Manufacturer': '',
        'Sale Price': '',
        'Discount Base Price': '',
        'Stock': 2,
        'Lead Time': 12,
        'Detailed Description': '',
        'Main Image': '',
        'Search Keywords': '',
        'Quantity': 1,
        'Volume': '',
        'Weight': '',
        'Adult Only': 'N',
        'Taxable': 'N',
        'Parallel Import': 'N',
        'Overseas Purchase': 'Y',
        'SKU': '',
        'Model Number': '',
        'Barcode': '',
        'Additional Image 1': '',
        'Additional Image 2': '',
        '_product_url': '',  # Internal use only, not exported
    }

    # Extract Product Name
    name = _pick(c, [
        'span.a-text-normal', 'h2 a span', 'h2 a', 'h3 a', 'h4 a',
        '[class*="product-title"]', '[class*="ProductName"]', '[class*="product-name"]',
        '[class*="product_name"]', '[class*="title"]', '._4rR01T', '._2Tpdn3',
        '[data-testid*="title"]', '[data-testid*="name"]', 'h2', 'h3', 'h4',
    ])
    if not name:
        a = c.find('a', title=True)
        if a:
            name = clean_text(a['title'])
    if name:
        p['Product Name'] = name[:220]

    # Extract Sale Price
    price = _pick(c, [
        'span.a-price-whole', 'span.a-offscreen',
        '._30jeq3', '._1_WHN1', '._16Jk6d',
        '[class*="selling-price"]', '[class*="sale-price"]', '[class*="current-price"]',
        '[class*="offer-price"]', '[class*="discounted"]',
        '[class*="price"]', '[class*="Price"]', '[data-testid*="price"]',
    ], lambda el: extract_price(el.get_text()))
    if price and re.search(r'\d', price):
        p['Sale Price'] = price

    # Extract Discount Base Price (MRP)
    mrp = _pick(c, [
        'span.a-price.a-text-price span.a-offscreen', '._3I9_wc',
        '[class*="original-price"]', '[class*="old-price"]', '[class*="mrp"]',
        '[class*="was-price"]', '[class*="compare-price"]', 'del', 's', 'strike',
    ], lambda el: extract_price(el.get_text()))
    if mrp and re.search(r'\d', mrp):
        p['Discount Base Price'] = mrp

    # Extract Brand
    brand = _pick(c, [
        '#bylineInfo', 'a#bylineInfo', '._2Wk9S9',
        '[class*="brand"]', '[class*="Brand"]', '[data-testid*="brand"]',
    ])
    if not brand and name:
        brand = name.split(' ')[0]
    if brand and len(brand) < 80:
        p['Brand'] = brand

    # Extract Product URL (internal use for PDP scraping)
    a = c.find('a', href=True)
    if a:
        href = a['href']
        p['_product_url'] = href if href.startswith('http') else urljoin(base_url, href)

    # Extract Main Image
    for sel in ['img.s-image', 'img[class*="product"]', 'img[class*="Product"]', 'img']:
        el = c.select_one(sel)
        if el:
            src = el.get('data-a-dynamic-image') or el.get('srcset') or el.get('src') or ''
            if src.startswith('{'):
                try:
                    urls = json.loads(src)
                    src = max(urls.items(), key=lambda x: x[1][0])[0] if urls else ''
                except (json.JSONDecodeError, ValueError):
                    pass
            if ',' in src:
                src = src.split(',')[-1].strip().split(' ')[0]
            if src and 'http' in src:
                if src.startswith('//'):
                    src = 'https:' + src
                p['Main Image'] = src
                break

    return p

def fetch_product_details(url, existing_p):
    """Visits the Product Detail Page (PDP) to extract deep information."""
    html = fetch_with_playwright(url, wait_sec=2)
    if not html:
        return existing_p

    soup = BeautifulSoup(html, 'lxml')
    p = existing_p.copy()

    # Extract Detailed Description
    desc_el = soup.select_one(
        '#feature-bullets, #productDescription, '
        '[class*="description"], [class*="Description"]'
    )
    if desc_el:
        p['Detailed Description'] = clean_text(desc_el.get_text())[:2000]

    # Extract Manufacturer / Brand Details
    manu = soup.select_one(
        'a#bylineInfo, #detailBullets_feature_div, '
        '[class*="manufacturer"], [class*="Manufacturer"]'
    )
    if manu:
        txt = clean_text(manu.get_text())
        if 'brand' in txt.lower() or 'visit the' in txt.lower():
            p['Brand'] = txt.replace('Visit the ', '').replace(' Store', '').strip()[:80]
        p['Manufacturer'] = txt[:120]

    # Extract Additional Images
    add_images = []
    for img in soup.select('#altImages img, .imageThumbnail img, [class*="thumbnail"] img'):
        src = img.get('src') or img.get('data-src') or ''
        if src and 'http' in src and 'GIF' not in src.upper():
            # Get high-res by removing resizing suffix (Amazon specific _AC_...)
            hi_res = re.sub(r'\._AC_.*_\.', '.', src)
            if hi_res not in add_images and hi_res != p.get('Main Image'):
                add_images.append(hi_res)

    if add_images:
        p['Additional Image 1'] = add_images[0]
    if len(add_images) > 1:
        p['Additional Image 2'] = add_images[1]

    # Extract SKU / Model Number (Amazon ASIN)
    asin_m = re.search(r'/dp/([A-Z0-9]{10})', url)
    if asin_m:
        p['SKU'] = asin_m.group(1)
        p['Model Number'] = f"{p['SKU']}-1"

    # Extract Volume / Weight from specs
    specs = soup.get_text()
    weight_m = re.search(r'(\d+(?:\.\d+)?\s*(?:kg|g|gm|ml|l|oz|lb))', specs, re.I)
    if weight_m:
        val = weight_m.group(1)
        # Assign to Weight or Volume based on unit
        if re.search(r'(ml|l)$', val, re.I):
            p['Volume'] = val
        else:
            p['Weight'] = val

    # Generate Search Keywords from product name
    if p.get('Product Name'):
        words = p['Product Name'].lower().replace(',', '').split()
        unique_words = []
        for w in words:
            if w not in unique_words and len(w) > 2:
                unique_words.append(w)
        p['Search Keywords'] = ', '.join(unique_words[:15])

    return p

# ─────────────────────────────────────────────────────────────────────────────
# BACKGROUND JOB
# ─────────────────────────────────────────────────────────────────────────────
def scrape_job(job_id, jobs, base_url, keyword, max_products, outputs_dir):
    job = jobs[job_id]
    job['status'] = 'running'

    def log(msg, level='info'):
        job['log'].append({'msg': msg, 'level': level})
        job['last_message'] = msg
        print(f"[{job_id}] {msg}")

    try:
        all_products, page = [], 1

        log(f"🌐 Site   : {base_url}")
        log(f"🔑 Keyword: '{keyword}'  |  Max: {max_products}")
        log("🚀 Launching Chromium browser...")

        while len(all_products) < max_products:
            url = build_search_url(base_url, keyword, page)
            log(f"📄 Fetching page {page} …")

            html = fetch_with_playwright(url, wait_sec=5)

            if not html:
                msg = ("Playwright / Chromium could not load the page.\n"
                       "Run this command once to install the browser:\n"
                       "  playwright install chromium")
                log(f"❌ {msg}", 'error')
                job['status'] = 'error'; job['error'] = msg; return

            soup = BeautifulSoup(html, 'lxml')
            for tag in soup(['script','style','noscript','iframe']): tag.decompose()

            products = extract_products_from_soup(soup, base_url)

            if not products:
                text_low = soup.get_text()[:600].lower()
                if any(w in text_low for w in ['captcha','robot','verify','are you human']):
                    msg = "Site is showing a CAPTCHA. Try again later or from a different network."
                elif any(w in text_low for w in ['sign in','log in','login']):
                    msg = "Site requires you to log in before showing products."
                elif page == 1:
                    msg = ("No products detected on page 1.\n"
                           "Possible reasons: keyword has no results, site structure changed,\n"
                           "or the site needs a different URL format.")
                else:
                    log("ℹ️ No more products. Stopping.", 'warn'); break

                if page == 1:
                    log(f"⚠️ {msg}", 'warn')
                    job['status'] = 'error'; job['error'] = msg; return
                break

            added = 0
            for prod in products:
                if len(all_products) >= max_products:
                    break

                # Enrich with PDP data
                product_url = prod.get('_product_url')
                if product_url:
                    pname = prod.get('Product Name', 'Unknown Product')
                    log(f"🔎 Deep scraping: {pname[:40]}...")
                    prod = fetch_product_details(product_url, prod)
                    time.sleep(random.uniform(1.2, 2.5))

                # Remove internal field before adding to results
                prod.pop('_product_url', None)
                all_products.append(prod)
                added += 1

            log(f"✅ Page {page}: +{added} products  (total {len(all_products)}/{max_products})", 'success')
            job['progress'] = int(min(len(all_products) / max_products * 85, 85))
            job['found']    = len(all_products)

            if added == 0: break
            page += 1
            time.sleep(random.uniform(2.0, 3.5))

        if not all_products:
            job['status'] = 'error'; job['error'] = "No products were scraped."; return

        log(f"📊 Building Excel for {len(all_products)} products …")
        job['progress'] = 90
        fp = build_excel(all_products, keyword, base_url, outputs_dir)
        log(f"✅ Excel saved → {os.path.basename(fp)}", 'success')

        job.update({'status':'done','progress':100,'filepath':fp,'total':len(all_products)})

    except Exception as e:
        import traceback
        job['status'] = 'error'; job['error'] = str(e)
        log(f"💥 {e}", 'error')
        print(traceback.format_exc())
