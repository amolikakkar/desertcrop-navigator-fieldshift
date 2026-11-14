# DesertCrop Navigator

**What should I grow next?** A simple, bilingual (English and Hindi) phone app that helps farmers in three dry
districts of Rajasthan, India (Jodhpur, Barmer and Sikar) choose their next crop and compare crop-rotation plans,
using NASA Earth observation data.

Built for the **NASA Space Apps Challenge 2026**, challenge **"Field Shift: Adapting Farms with NASA Data"**.
Team DesertCrop Navigator (Amoli Kakkar), Local Event: Jaipur, India.

**▶ Try the live app (no install needed): https://ephemeral-kheer-3e80c6.netlify.app**
Open it on a phone or computer. To run the same code on your own computer, see
[Run it on your computer](#run-it-on-your-computer) below.

---

## What the app does

A farmer answers four short questions with big picture buttons:

1. **Where is your field?** "Use my location" (rounded to about 10 km and only sent to NASA POWER to ask for the
   weather there) or tap a district.
2. **What do you usually grow?** The usual monsoon (kharif) crop and winter (rabi) crop. Only crops that can suit
   the area this year are shown first; the rest are under "Other", marked "Poor fit" with the main reason.
3. **Water for this field?** Rain only, some irrigation, or enough irrigation.
4. **What is your soil like?** Sandy, loamy or heavy (clay), and whether a white salt crust is seen.

The app then shows:

- **Best crops for next season**: the top 3 crops for the coming season, with reasons, warnings and the usual
  district yield from Government of India crop statistics.
- **Three rotation plans compared** (as the challenge asks): *what you grow now*, *crops which save water* and
  *crops which build soil*. Each plan shows why it was suggested, the evidence, benefits, what we don't know, and
  what to check with the local Krishi Vigyan Kendra (KVK, the farm science centre).
- **What NASA sees near you**: this year's rain against a usual year, days of 40 °C or more, the usual soil
  moisture by month, and field greenness by month (when fields are usually green or bare).
- **A map** of the district and of the 10 km farmland areas where the NASA data is read.
- **Crop rules** shown as pictures, so every rating can be explained.
- **My farm report**: one page with everything above, to print or share as a PDF.
- Everything works in **Hindi or English**, on low-cost Android phones, and keeps working without internet using
  the last saved data.

The app supports farmers' own judgement; it does not replace it or local agricultural advice.

---

## Run it on your computer

You need **Python 3** (any recent version) and a web browser. Nothing else needs installing.

```bash
git clone https://github.com/amolikakkar/desertcrop-navigator-fieldshift.git
cd desertcrop-navigator-fieldshift/app
python -m http.server 8000
```

(On Windows you can use `py -m http.server 8000`; on macOS or Linux, `python3 -m http.server 8000`.)

Then open **http://localhost:8000** in your browser. To see it as a farmer would, use the browser's phone view
(for example Chrome: F12, then the phone icon).

Notes:
- Open it through the small server as above. Opening `index.html` by double-clicking will not load the data file.
- With internet, the app asks NASA POWER for the newest days of weather each time it opens, and loads the map.
  Without internet it uses the bundled `data.json`.
- "Use my location" works on `localhost` (browsers allow location only on https or localhost).
- Switch language with the **English / हिन्दी** buttons at the top.

---

## NASA data used

| Data | What we use it for | Period |
|---|---|---|
| **NASA POWER** daily data: rainfall (`PRECTOTCORR`), maximum and minimum temperature (`T2M_MAX`, `T2M_MIN`), root-zone soil wetness (`GWETROOT`) | Rain this year vs a usual year, rain by month, days of 40 °C or more, usual soil moisture by month, dry-year rule | 1 Jan 2021 to today (refreshed live in the app) |
| **HLS v2.0** (Harmonized Landsat Sentinel-2) surface reflectance, products `HLSL30` and `HLSS30`, from NASA LP DAAC via NASA Earthdata | NDVI greenness: when fields are green or bare, and how green they were after this year's monsoon | 1 Jan 2024 to early Nov 2026 (1,704 pictures; 1 could not be read) |

How the data is read:
- Each district has one **farmland sample point**, a 0.1-degree square (about 10 km) of mostly fields, chosen with
  ESA WorldCover 2021 land cover so the readings show farms, not towns: Jodhpur 26.59 N, 72.97 E; Barmer 26.15 N,
  71.35 E; Sikar 27.46 N, 74.94 E.
- For HLS, clouds, cloud shadows and snow are removed pixel by pixel with the Fmask quality layer (bits 1-4).
- NASA POWER values are computer-model estimates, not rain-gauge readings, so the app always compares a year with
  the usual year *from the same NASA source*.

What the data shows (Jan to Oct 2026, against the same months of 2021-2025):

| District | Rain so far | Days of 40 °C or more | Greenness after the monsoon |
|---|---|---|---|
| Jodhpur | 278 of 462 mm (60%) | 71 (usual 60) | 27% less green than 2024-25 |
| Barmer | 259 of 425 mm (61%) | 84 (usual 62) | 31% less green |
| Sikar | 524 of 744 mm (70%) | 41 (usual 44) | about 6% less green |

More detail, charts and caveats are in [RESULTS_REPORT.md](RESULTS_REPORT.md).

---

## How a crop is rated

Every crop gets points from simple rules that can be explained in one line and checked by local experts:

- water need against the farmer's water; salt tolerance against the soil; the crop grown before (legumes add
  nitrogen, the same crop family twice in a row rates lower);
- **three NASA rules**:
  - **Dry year**: rain so far below 80% of usual (the India Meteorological Department's "deficient" definition):
    low-water crops +1, thirsty crops -1.
  - **Arid zone**: Jodhpur and Barmer are in the official Arid Western Zone (NARP zone RJ-1). On rain-fed fields,
    winter crops needing medium water rate lower.
  - **Rain swing**: if yearly rain changes by 30% or more between years, the risk is flagged.
- **3 points or more = Good fit, 1 to 2 = Possible, 0 or less = Poor fit.**

We chose clear rules instead of a black-box model so a farmer can see why, and an expert can correct any rule.

---

## Project structure

```
app/                     the app (one HTML file, no build step)
  index.html             all screens, crop rules, ratings and the Hindi translations
  data.json              NASA POWER weather and HLS greenness for the three districts
  districts.json         district outlines for the map (OpenStreetMap, simplified)
  sw.js                  offline support (service worker)
  service-worker.js      clean-up file for phones that had an older version
  manifest.webmanifest   lets the app be installed on a phone
  icon-192.png, icon-512.png, icon.svg
pipeline/                scripts that build app/data.json from NASA data
  fetch_nasa_data.py     NASA POWER and HLS helpers (reading, cloud masking, NDVI)
  update_data.py         collects weather and greenness, one year at a time, and saves app/data.json
  update_weather.py      refreshes only the NASA POWER weather (no login needed)
  parameter_register.csv list of the data sources and parameters used
RESULTS_REPORT.md        what the NASA data shows for each district, with charts
report-charts/           chart pictures used in the report
```

---

## Updating the data (optional)

The app already includes the data. To rebuild it from NASA:

```bash
cd pipeline
pip install earthaccess rasterio numpy requests
python update_weather.py                 # NASA POWER weather only, no login needed
python update_data.py all                # weather + HLS greenness for all districts
```

`update_data.py` needs a free **NASA Earthdata** account (https://urs.earthdata.nasa.gov); it asks for the login
when it starts and does not save it. Other forms, for example one district or a date range:

```bash
python update_data.py Jodhpur
python update_data.py all 2026-11-09 2024-01-01
```

It saves progress after each year, and if a reading program crashes it restarts from the last saved year.

---

## Sources and references

- NASA POWER (power.larc.nasa.gov); NASA HLS v2.0 via NASA LP DAAC and Earthdata; Landsat (NASA/USGS) and
  Sentinel-2 (ESA/Copernicus) inside HLS.
- ESA WorldCover 2021: used only to choose the farmland sample points.
- OpenStreetMap contributors: map tiles and district outlines (via Nominatim), shown with the Leaflet map library.
- India Meteorological Department: definition of a "deficient" rainfall season (20% or more below normal).
- ICAR / NARP agro-climatic zones of Rajasthan (Arid Western Zone, RJ-1); ICAR-CRIDA district contingency plan
  for Jodhpur.
- Government of India, Directorate of Economics and Statistics: district crop area, production and yield,
  2018-19 to 2022-23 (data.desagri.gov.in).
- ICAR-IISS: Soil Health Card ratings (EC above 4 dS/m = saline).
- Font: Bricolage Grotesque (Google Fonts).

---

## Limitations

- The crop rules are **starter rules** and have not yet been checked by agriculture experts (KVK, CAZRI).
- NASA POWER rain is a model estimate. For Jodhpur, NASA's usual rain (about 469 mm a year) is higher than the
  official normal (263 mm, ICAR-CRIDA). Because the app compares with NASA's own usual year, a steady difference
  does not change the dry-year signal, but absolute amounts should be read with care.
- Each district's data comes from one 10 km farmland area, not the farmer's own field.
- Greenness is refreshed with the pipeline (it needs a NASA Earthdata login), not live on the phone.
- The Hindi text was drafted with an AI assistant and still needs review by a native speaker for farm terms.

## Use of AI (Super Intelligence) tools

Claude (Anthropic), a large language model, was used as a coding and writing assistant: to help write and fix the
app code and the Python data scripts, draft the Hindi translation, look up official sources, and draft text such
as this README. The design decisions, data choices and testing were done by the team. No AI-generated images,
video or audio are used.
