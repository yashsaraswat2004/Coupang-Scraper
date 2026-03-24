# DataHarvest — Universal E-Commerce Scraper

A web-based scraper that extracts product data from any e-commerce website and exports it to a formatted Excel (.xlsx) file with a standardized CSV template format.

## 📁 Folder Structure

```
scraper/
├── app/
│   ├── __init__.py         # Flask app initialization
│   ├── scraper.py          # Core scraping engine (Playwright)
│   ├── excel_utils.py      # Excel export utilities
│   ├── helpers.py          # Helper functions
│   ├── routes.py           # API endpoints
│   └── static/
│       └── index.html      # Frontend web UI
├── outputs/                # Generated Excel files
├── run.py                  # Application entry point
├── verify_scraper.py       # Scraper verification script
├── requirements.txt        # Python dependencies
└── README.md               # This file
```

## 🚀 Setup & Run

### 1. Clone the repository
```bash
git clone <your-repo-url>
cd scraper
```

### 2. Create virtual environment (recommended)
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS/Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Python dependencies
```bash
pip install -r requirements.txt
```

### 4. Install Playwright browser
```bash
python -m playwright install chromium
```

### 5. Start the server
```bash
python run.py
```

### 6. Open in browser
```
http://localhost:5055
```

## 🌐 Supported Websites
- Amazon.in / Amazon.com
- Flipkart
- Nykaa
- Meesho
- Snapdeal
- Ajio
- Myntra
- eBay
- Walmart
- Any generic e-commerce site

## 📊 Output CSV Template (23 Columns)

| Column              | Description                              |
|---------------------|------------------------------------------|
| Category            | Product category                         |
| Product Name        | Full product title                       |
| Brand               | Brand name                               |
| Manufacturer        | Manufacturer name                        |
| Sale Price          | Current selling price                    |
| Discount Base Price | Original / MRP price                     |
| Stock               | Stock quantity (default: 2)              |
| Lead Time           | Lead time in days (default: 12)          |
| Detailed Description| Full product description from PDP        |
| Main Image          | Primary product image URL                |
| Search Keywords     | Auto-generated search keywords           |
| Quantity            | Quantity (default: 1)                    |
| Volume              | Product volume (ml, l)                   |
| Weight              | Product weight (g, kg)                   |
| Adult Only          | Adult only flag (default: N)             |
| Taxable             | Taxable flag (default: N)                |
| Parallel Import     | Parallel import flag (default: N)        |
| Overseas Purchase   | Overseas purchase flag (default: Y)      |
| SKU                 | Stock Keeping Unit (Amazon ASIN)         |
| Model Number        | Model number                             |
| Barcode             | Product barcode                          |
| Additional Image 1  | Secondary product image URL              |
| Additional Image 2  | Tertiary product image URL               |

## ⚙️ API Endpoints

| Method | Endpoint              | Description                    |
|--------|-----------------------|--------------------------------|
| POST   | /api/scrape           | Start a scrape job             |
| GET    | /api/status/<job_id>  | Poll job progress & logs       |
| GET    | /api/download/<job_id>| Download the generated .xlsx   |

### Start Scrape Request
```json
POST /api/scrape
{
  "url": "https://www.amazon.in",
  "keyword": "laptop",
  "max_products": 50
}
```

## 📝 Notes
- Output Excel files are saved to `outputs/` folder
- Max 500 products per scrape
- Polite delay (1.5–3s) between page requests
- Uses Playwright for JavaScript rendering support
- Automatically skips sponsored/ad products
- Deep scrapes product detail pages (PDP) for additional info

## 🔧 Troubleshooting

### "Playwright / Chromium could not load the page"
Run the following command to install the browser:
```bash
python -m playwright install chromium
```

### Module not found errors
Make sure all dependencies are installed:
```bash
pip install -r requirements.txt
```

### CAPTCHA or login required
- Try again later or from a different network
- Some sites may block automated access
