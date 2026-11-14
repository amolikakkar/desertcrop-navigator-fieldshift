# DesertCrop Navigator

**What should I grow next?** A bilingual (English/Hindi) phone app that helps farmers in Jodhpur, Barmer and Sikar
(Rajasthan, India) choose their next crop using NASA Earth data.

NASA Space Apps Challenge 2026 · **Field Shift: Adapting Farms with NASA Data** · Team DesertCrop Navigator (Amoli Kakkar), Jaipur

**▶ Live app (no install): https://ephemeral-kheer-3e80c6.netlify.app**

## What it does
A farmer answers 4 picture questions (field location, usual crops, water, soil) and gets:
- **Top 3 crops for next season**, with reasons and the usual district yield
- **3 rotation plans compared**: what you grow now, crops that save water, crops that build soil, each with why,
  evidence, benefits, gaps and what to check with the local farm science centre (KVK)
- **What NASA sees**: rain this year vs usual, hot days, soil moisture, field greenness, and a map
- Optional **farm details** (farming system, investment, credit, market, labour, risk), **Soil Health Card numbers**
  (organic carbon, pH, EC) and a **money calculator** using the farmer's own figures (no outside data)
- A shareable **PDF farm report** with all of the above, in Hindi or English, working offline after the first visit

## Run it locally
```bash
git clone https://github.com/amolikakkar/desertcrop-navigator-fieldshift.git
cd desertcrop-navigator-fieldshift/app
python -m http.server 8000      # Windows: py -m http.server 8000
```
Open **http://localhost:8000** (use the browser's phone view to see it as a farmer would). Needs only Python 3.
Don't open `index.html` directly; the data file loads only through the server.

## NASA data
| Data | Used for |
|---|---|
| **NASA POWER** daily rain, max/min temperature, root-zone soil wetness (2021 to today, refreshed live) | Dry-year check, rain by month, days ≥ 40 °C, soil moisture |
| **HLS v2.0** (Landsat + Sentinel-2) NDVI, cloud-masked (2024 to Nov 2026) | When fields are green or bare; greenness after the monsoon |

Each district is read at one 10 km farmland square. Jan–Oct 2026 rain was **60–70% of usual** in all three
districts, and fields in Jodhpur and Barmer were **27–31% less green** after the monsoon. Details: [RESULTS_REPORT.md](RESULTS_REPORT.md).

## How crops are rated
Simple, explainable points: water need vs the farmer's water, salt tolerance, previous crop (legumes add nitrogen),
plus three NASA rules: **dry year** (rain below 80% of usual), **arid zone** (Jodhpur, Barmer) and **rain swing**
(≥ 30% between years). Optional farm details and soil test numbers adjust points too (e.g. EC above 4 dS/m = salty
soil, per the Soil Health Card rating). 3+ points = Good fit, 1–2 = Possible, 0 or less = Poor fit.

## Repository
```
app/          the app: index.html (single file, no build), data.json, districts.json, offline files, icons
pipeline/     Python scripts that rebuild data.json from NASA (update_weather.py needs no login;
              update_data.py needs a free NASA Earthdata account)
RESULTS_REPORT.md, report-charts/   what the data shows, with charts
```

## Limitations
- Crop rules are starter rules, not yet checked by agriculture experts (KVK, CAZRI).
- NASA POWER rain is a model estimate, so the app compares each year with NASA's own usual year.
- Data comes from one farmland area per district, not the farmer's own field. Hindi needs a native-speaker review.

## Sources
NASA POWER; NASA HLS v2.0 (LP DAAC/Earthdata); ESA WorldCover 2021 (choosing farmland points); OpenStreetMap
(map and district outlines) with Leaflet; IMD rainfall definitions; ICAR/NARP agro-climatic zones; Government of
India DES crop yields (2018-19 to 2022-23); ICAR-IISS Soil Health Card ratings.

## Use of AI
Claude (Anthropic) was used as a coding and writing assistant (app and script code, Hindi draft, this README).
Design decisions, data choices and testing were done by the team. No AI-generated images, video or audio.
