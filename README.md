# Yerevan Rentals Map

Interactive map of rental listings in Yerevan, Armenia — scraped from [besthouse.am](https://besthouse.am), geocoded, and displayed on a filterable Leaflet map.

**Live site:** [jdorrance.github.io/yerevan-real-estate](https://jdorrance.github.io/yerevan-real-estate/) *(GitHub Pages)*

![Vite](https://img.shields.io/badge/Vite-6-646CFF?logo=vite&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white)
![Leaflet](https://img.shields.io/badge/Leaflet-1.9-199900?logo=leaflet&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)

---

## What it does

1. **Scrapes** rental listings from besthouse.am (Arabkir, Center, Nor Norq — $2,000–$5,000/mo, 200+ m²)
2. **Geocodes** addresses to lat/lng via Nominatim (OpenStreetMap)
3. **Generates** structured CSV and GeoJSON exports
4. **Renders** an interactive map with per-listing popups, photo gallery, sortable table, and district/price/area filters

Listings data (`data/listings.json`) is committed to the repo — no scraping happens during CI/CD.

---

## Project structure

```
├── scraper.py              # Fetches + parses search/detail pages from besthouse.am
├── geocode.py              # Geocodes addresses via Nominatim
├── output.py               # Generates CSV + GeoJSON
├── main.py                 # Orchestrates the full pipeline
├── requirements.txt        # Python dependencies
│
├── data/
│   ├── listings.json       # Canonical scraped data (committed)
│   ├── raw/                # Cached HTML pages (gitignored)
│   └── output/             # CSV + GeoJSON exports
│
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── .nvmrc              # Node 22
│   ├── public/data/        # listings.json + config.json (copied by pipeline)
│   └── src/
│       ├── main.ts         # App entry point
│       ├── types.ts        # Interfaces (Listing, AppConfig, FilterValues)
│       ├── converters.ts   # Raw JSON → typed Listing normalization
│       ├── config.ts       # Constants (EU coords, price brackets)
│       ├── dom.ts          # Shared DOM utilities (escapeHtml, formatters)
│       ├── sort.ts         # Typed sort comparator
│       ├── map.ts          # Leaflet map + marker clustering
│       ├── table.ts        # Sortable listings table
│       ├── filters.ts      # Filter controls + logic
│       ├── gallery.ts      # Photo lightbox
│       └── styles/         # Modular CSS with custom properties
│           ├── index.css
│           ├── base.css
│           ├── header.css
│           ├── controls.css
│           ├── map.css
│           ├── table.css
│           └── gallery.css
│
└── .github/workflows/
    └── deploy.yml          # Build + deploy to GitHub Pages (no scraping)
```

---

## Getting started

### Prerequisites

- Python 3.11+
- Node 22+ (see `frontend/.nvmrc`)

### Run the scraper pipeline

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

This scrapes listings, geocodes them, and copies the data into `frontend/public/data/`.

### Run the frontend

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173).

### Build for production

```bash
cd frontend
npm run deploy   # builds with base path /yerevan-real-estate/ for GitHub Pages
```

Static output lands in `frontend/dist/` — ready to serve from any static host.

---

## Deployment

Pushing to `main` triggers the GitHub Actions workflow which:

1. Installs Node dependencies
2. Runs `npm run deploy` (Vite build with `/armenia/` base path)
3. Deploys `frontend/dist/` to GitHub Pages

No Python or scraping runs in CI. The listings JSON is committed to the repo and consumed at build time.

---

## License

MIT
