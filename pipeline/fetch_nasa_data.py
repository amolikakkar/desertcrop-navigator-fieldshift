"""DesertCrop Navigator - Phase 1 NASA climate + HLS NDVI data pipeline.

Install (Windows Command Prompt):
    py -m pip install earthaccess rasterio numpy requests

Run from the folder containing this file:
    py fetch_nasa_data.py

The script prompts for NASA Earthdata authentication and writes data.json.
Important: locations are sample points with a roughly 10 km box, NOT district-wide averages.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import PurePosixPath
from typing import Any

import earthaccess
import numpy as np
import requests
import rasterio
from rasterio.windows import from_bounds
from rasterio.warp import transform_bounds

# Farmland sample points, approved 11 Nov 2026. Each 0.1 x 0.1 degree box sits fully inside today's district
# and has the most cropland nearby (ESA WorldCover 2021, used only to choose the place; district checked with
# OpenStreetMap). The old town-centre points were Jodhpur 26.24,73.02 / Barmer 25.75,71.40 / Sikar 27.61,75.14.
SITES = {
    "Jodhpur": (26.59, 72.97),
    "Barmer": (26.15, 71.35),
    "Sikar": (27.46, 74.94),
}
START, END = "2021-01-01", "2025-12-31"
HALF_DEGREES = 0.05  # about 10 km north-south; approximate box, not an administrative boundary

# HLS v2.0 Fmask bits (0 = least significant): 0 cirrus (reserved, not used), 1 cloud,
# 2 adjacent to cloud/shadow, 3 cloud shadow, 4 snow/ice, 5 water, 6-7 aerosol level.
# Excluded here: bits 1-4. Water (5) and aerosol level (6-7) are kept on purpose.
# Confirm against the HLS v2.0 User Guide.
FMASK_BAD = (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4)


def annual_power(lat: float, lon: float) -> dict[str, dict[str, Any]]:
    """Fetch daily NASA POWER point data and summarize by calendar year.

    Besides the yearly totals and means, each year also gets 12 monthly values (January first; None for a
    month with no data yet): rain_month_mm (sum), days_40c_month (days with a daytime high of 40 C or more)
    and soil_wet_month (mean root-zone soil wetness GWETROOT, 0 = dry to 1 = saturated). GWETROOT is a
    MERRA-2 model value supplied by NASA POWER, not a SMAP satellite measurement.
    """
    params = {
        "parameters": "PRECTOTCORR,T2M_MAX,T2M_MIN,GWETROOT",
        "community": "AG",
        "latitude": lat,
        "longitude": lon,
        "start": START.replace("-", ""),
        "end": END.replace("-", ""),
        "format": "JSON",
    }
    response = requests.get(
        "https://power.larc.nasa.gov/api/temporal/daily/point",
        params=params,
        timeout=120,
    )
    response.raise_for_status()
    payload = response.json()
    parameters = payload.get("properties", {}).get("parameter", {})
    required = ("PRECTOTCORR", "T2M_MAX", "T2M_MIN")
    missing = [key for key in required if key not in parameters]
    if missing:
        raise ValueError(f"NASA POWER response is missing parameters: {', '.join(missing)}")

    rain = parameters["PRECTOTCORR"]
    tmax = parameters["T2M_MAX"]
    tmin = parameters["T2M_MIN"]
    wet = parameters.get("GWETROOT")  # optional: the yearly figures do not depend on it
    result: dict[str, dict[str, Any]] = {}
    for year in range(int(START[:4]), int(END[:4]) + 1):
        year_keys = sorted(k for k in rain if k.startswith(str(year)))
        valid_rain = [float(rain[k]) for k in year_keys if _valid_power_value(rain[k])]
        valid_max = [float(tmax[k]) for k in year_keys if k in tmax and _valid_power_value(tmax[k])]
        valid_min = [float(tmin[k]) for k in year_keys if k in tmin and _valid_power_value(tmin[k])]
        valid_rain_keys = [k for k in year_keys if _valid_power_value(rain[k])]
        result[str(year)] = {
            # Last day of the year with a rainfall value (YYYY-MM-DD); shows how far a partial year goes.
            "last_day": f"{valid_rain_keys[-1][:4]}-{valid_rain_keys[-1][4:6]}-{valid_rain_keys[-1][6:8]}" if valid_rain_keys else None,
            "rain_mm": round(sum(valid_rain), 1) if valid_rain else None,
            "mean_tmax_c": round(float(np.mean(valid_max)), 1) if valid_max else None,
            "mean_tmin_c": round(float(np.mean(valid_min)), 1) if valid_min else None,
            "valid_rain_days": len(valid_rain),
            "valid_tmax_days": len(valid_max),
            "valid_tmin_days": len(valid_min),
        }
        rain_month, hot_month, wet_month = [], [], []
        for month in range(1, 13):
            keys = [k for k in year_keys if k[4:6] == f"{month:02d}"]
            r = [float(rain[k]) for k in keys if _valid_power_value(rain[k])]
            x = [float(tmax[k]) for k in keys if k in tmax and _valid_power_value(tmax[k])]
            rain_month.append(round(sum(r), 1) if r else None)
            hot_month.append(sum(1 for v in x if v >= 40) if x else None)
            if wet is not None:
                w = [float(wet[k]) for k in keys if k in wet and _valid_power_value(wet[k])]
                wet_month.append(round(float(np.mean(w)), 3) if w else None)
        result[str(year)]["rain_month_mm"] = rain_month
        result[str(year)]["days_40c_month"] = hot_month
        result[str(year)]["days_40c"] = sum(v for v in hot_month if v is not None)
        if wet is not None:
            result[str(year)]["soil_wet_month"] = wet_month
    return result


def _valid_power_value(value: Any) -> bool:
    try:
        value = float(value)
        return np.isfinite(value) and value > -900
    except (TypeError, ValueError):
        return False


def _granule_id(granule: Any) -> str:
    try:
        return str(granule["meta"].get("concept-id", "unknown-granule"))
    except Exception:
        return str(getattr(granule, "concept_id", "unknown-granule"))


def _beginning_date(granule: Any) -> str:
    """Get the observation date from Earthaccess UMM metadata where available."""
    try:
        raw = granule["umm"]["TemporalExtent"]["RangeDateTime"]["BeginningDateTime"]
        return str(raw)[:10]
    except Exception:
        pass
    # Fallback: many HLS concept IDs / filenames include a YYYYDDD acquisition date.
    text = _granule_id(granule)
    for part in text.replace(".", "_").split("_"):
        if len(part) == 7 and part.isdigit() and part[:4].startswith("20"):
            try:
                return dt.datetime.strptime(part, "%Y%j").date().isoformat()
            except ValueError:
                continue
    return "unknown-date"


def _band_links(granule: Any, nir_band: str) -> dict[str, str]:
    links = granule.data_links()
    found: dict[str, str] = {}
    wanted = {"B04": "red", nir_band: "nir", "Fmask": "fmask"}
    for url in links:
        path = PurePosixPath(str(url).split("?", 1)[0]).name
        # HLS filenames typically end in .B04.tif, .B8A.tif/.B05.tif, .Fmask.tif.
        lower = path.lower()
        for band, key in wanted.items():
            if lower.endswith(f".{band.lower()}.tif") or lower.endswith(f"_{band.lower()}.tif"):
                found[key] = str(url)
    missing = [key for key in ("red", "nir", "fmask") if key not in found]
    if missing:
        raise ValueError(f"Could not identify {', '.join(missing)} TIFF link(s); found {len(links)} links")
    return found


def _window_from_dataset(ds: Any, bbox: tuple[float, float, float, float]) -> tuple[np.ndarray, Any]:
    projected_bbox = transform_bounds("EPSG:4326", ds.crs, *bbox, densify_pts=21)
    window = from_bounds(*projected_bbox, transform=ds.transform)
    window = window.round_offsets().round_lengths()
    array = ds.read(1, window=window, boundless=False)
    if array.size == 0:
        raise ValueError("Site window fell outside this granule")
    return array, ds.nodata


def _read_window(url: str, bbox: tuple[float, float, float, float]) -> tuple[np.ndarray, Any]:
    """Original (slow) way: open the file through Earthaccess and read only the site window."""
    opened = earthaccess.open([url])
    if not opened:
        raise RuntimeError("Earthaccess did not open the requested HLS file")
    source = opened[0]
    with rasterio.open(source) as ds:
        return _window_from_dataset(ds, bbox)


# Faster ways (added 11 Nov 2026). The original way hands rasterio an open file object, and rasterio then
# downloads the WHOLE image file into memory (see rasterio.open: "its entire contents will be read into a
# MemoryFile"), three files per reading. The faster ways fetch only the parts of each file that cover the
# site window, and read several images at the same time. Both use this run's login (memory only):
#   "link":   ask NASA's server once per file for its direct download link (with the login session), then
#             let GDAL read just the needed pieces from that link in a few requests.
#   "opener": give rasterio an "opener" on Earthaccess's HTTPS connection (many smaller requests).
# The pixels read are the same; check_fast_read() proves it on real images at the start of every run and
# picks the fastest way that matches exactly. Any image the chosen way cannot read is retried the original way.
FAST_METHODS = ("link", "opener")
FAST_WORKERS = 8  # images read at the same time; 8 is the setting tested on real NASA data (11 Nov 2026)
FAST_BLOCK_BYTES = 512 * 1024
_SLOW_LOCK = threading.Lock()
_LOCAL = threading.local()


def _https_fs() -> Any:
    try:
        return earthaccess.get_fsspec_https_session()
    except Exception:
        return None


def _read_window_direct(url: str, bbox: tuple[float, float, float, float], fs: Any) -> tuple[np.ndarray, Any]:
    def opener(path: str, mode: str = "rb") -> Any:
        return fs.open(path, mode, block_size=FAST_BLOCK_BYTES, cache_type="blockcache")

    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        with rasterio.open(url, opener=opener) as ds:
            return _window_from_dataset(ds, bbox)


def _login_session() -> Any:
    session = getattr(_LOCAL, "session", None)
    if session is None:
        session = earthaccess.__auth__.get_session()  # one per thread; bearer token kept in memory only
        _LOCAL.session = session
    return session


def _direct_link(url: str) -> str:
    response = _login_session().get(url, allow_redirects=False, stream=True, timeout=60)
    try:
        location = response.headers.get("Location", "")
        if response.status_code in (301, 302, 303, 307, 308) and "?" in location and "urs.earthdata" not in location:
            return location
        raise RuntimeError(f"no direct download link (HTTP {response.status_code})")
    finally:
        response.close()


_LINK_GDAL = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_USE_HEAD": "NO",          # signed links allow GET only
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
    "GDAL_HTTP_MAX_RETRY": "4",
    "GDAL_HTTP_RETRY_DELAY": "2",
}


def _read_window_link(url: str, bbox: tuple[float, float, float, float]) -> tuple[np.ndarray, Any]:
    link = _direct_link(url)
    with rasterio.Env(**_LINK_GDAL):
        with rasterio.open("/vsicurl/" + link) as ds:
            return _window_from_dataset(ds, bbox)


def _read_fast(method: str, url: str, bbox: tuple[float, float, float, float]) -> tuple[np.ndarray, Any]:
    if method == "link":
        return _read_window_link(url, bbox)
    if method == "opener":
        fs = _https_fs()
        if fs is None:
            raise RuntimeError("the Earthaccess HTTPS connection is not available")
        return _read_window_direct(url, bbox, fs)
    raise ValueError(f"unknown reading method {method}")


def check_fast_read(lat: float, lon: float, start: str, end: str, per_product: int = 1) -> tuple[str | None, str]:
    """Read a few real images the original way and each faster way; return the first faster way whose
    pixels are identical for every band, or None if none are."""
    bbox = (lon - HALF_DEGREES, lat - HALF_DEGREES, lon + HALF_DEGREES, lat + HALF_DEGREES)
    reference = []  # (granule id, band, array, nodata) read the original way
    slow_s = 0.0
    try:
        for short_name, nir_band in (("HLSS30", "B8A"), ("HLSL30", "B05")):
            granules = earthaccess.search_data(short_name=short_name, bounding_box=bbox,
                                               temporal=(start, end), count=per_product)
            for granule in list(granules)[:per_product]:
                links = _band_links(granule, nir_band)
                for key in ("red", "nir", "fmask"):
                    t0 = time.perf_counter()
                    array, nodata = _read_window(links[key], bbox)
                    slow_s += time.perf_counter() - t0
                    reference.append((_granule_id(granule), key, links[key], array, nodata))
    except Exception as exc:
        return None, f"the check could not finish: {str(exc)[:300]}"
    if not reference:
        return None, "no images were found to check"
    images = len({r[0] for r in reference})
    notes, passed = [f"original way {slow_s:.0f} s"], {}
    for method in FAST_METHODS:
        fast_s = 0.0
        try:
            for gid, key, url, array, nodata in reference:
                t0 = time.perf_counter()
                fast, fast_nodata = _read_fast(method, url, bbox)
                fast_s += time.perf_counter() - t0
                if fast.shape != array.shape or not np.array_equal(fast, array) or fast_nodata != nodata:
                    raise ValueError(f"pixels differed for {gid} {key}")
        except Exception as exc:
            notes.append(f"'{method}' way not used ({str(exc)[:200]})")
            continue
        passed[method] = fast_s
        notes.append(f"'{method}' way identical, {fast_s:.0f} s")
    if not passed:
        return None, f"{images} images checked: " + "; ".join(notes)
    best = min(passed, key=passed.get)  # fastest of the ways whose pixels matched exactly
    return best, f"{images} images checked: " + "; ".join(notes) + f". Using the '{best}' way"


def _valid_reflectance(array: np.ndarray, nodata: Any) -> np.ndarray:
    valid = np.isfinite(array) & (array > -1000)
    if nodata is not None:
        valid &= array != nodata
    return valid


def _granule_row(granule: Any, short_name: str, nir_band: str, bbox: tuple[float, float, float, float],
                 read: Any) -> dict[str, Any]:
    """Compute one NDVI reading. `read(url)` returns (array, nodata) for the site window."""
    links = _band_links(granule, nir_band)
    red, red_nodata = read(links["red"])
    nir, nir_nodata = read(links["nir"])
    fmask, _ = read(links["fmask"])
    # HLS bands in this product family should align; skip rather than silently misalign.
    if red.shape != nir.shape or red.shape != fmask.shape:
        raise ValueError(f"Band window shapes differ: red={red.shape}, nir={nir.shape}, Fmask={fmask.shape}")
    red = red.astype("float32")
    nir = nir.astype("float32")
    fmask = fmask.astype("uint8")
    good = (
        _valid_reflectance(red, red_nodata)
        & _valid_reflectance(nir, nir_nodata)
        & ((fmask & FMASK_BAD) == 0)
        & (np.abs(nir + red) > 1e-6)
    )
    with np.errstate(divide="ignore", invalid="ignore"):  # pixels with nir + red = 0 are already excluded by `good`
        ndvi = (nir - red) / (nir + red)
    valid_count = int(good.sum())
    total_count = int(good.size)
    return {
        "date": _beginning_date(granule),
        "product": short_name,
        "granule": _granule_id(granule),
        "ndvi_mean": round(float(np.mean(ndvi[good])), 4) if valid_count else None,
        "valid_pct": round(100.0 * valid_count / total_count, 2) if total_count else 0.0,
        "valid_pixels": valid_count,
        "sampled_pixels": total_count,
        "quality_mask": "HLS Fmask bits 1-4 excluded; water and aerosol retained",
    }


def _one_granule(granule: Any, short_name: str, nir_band: str, bbox: tuple[float, float, float, float],
                 method: str | None) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Checked fast way first (if any); if it fails, retry the original way; report an error only if both fail."""
    gid = _granule_id(granule)
    if method:
        try:
            return _granule_row(granule, short_name, nir_band, bbox,
                                lambda url: _read_fast(method, url, bbox)), None
        except Exception:
            pass
    try:
        with _SLOW_LOCK:  # the original way is only used one image at a time
            return _granule_row(granule, short_name, nir_band, bbox, lambda url: _read_window(url, bbox)), None
    except Exception as exc:
        return None, {"granule": gid, "error": f"{type(exc).__name__}: {exc}"[:500]}  # type shown: some errors have no text


def ndvi_series(lat: float, lon: float, fast: str | None = None) -> dict[str, Any]:
    """`fast` is the reading way chosen by check_fast_read() ("link" or "opener"), or None for the original."""
    bbox = (lon - HALF_DEGREES, lat - HALF_DEGREES, lon + HALF_DEGREES, lat + HALF_DEGREES)
    workers = FAST_WORKERS if fast else 1
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for short_name, nir_band in (("HLSS30", "B8A"), ("HLSL30", "B05")):
        print(f"  Searching {short_name} granules…", flush=True)
        # No whole-tile cloud-cover filter (removed 11 Nov 2026): a ~110 km tile can be mostly cloudy
        # while this 10 km box is clear. Cloudy pixels are still removed one by one with Fmask below.
        granules = earthaccess.search_data(
            short_name=short_name,
            bounding_box=bbox,
            temporal=(START, END),
        )
        print(f"  Found {len(granules)} {short_name} granules", flush=True)
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            jobs = [pool.submit(_one_granule, g, short_name, nir_band, bbox, fast) for g in granules]
            for job in as_completed(jobs):
                row, error = job.result()
                if row is not None:
                    rows.append(row)
                else:
                    errors.append(error)
                    print(f"    Skip {error['granule']}: {error['error']}", flush=True)
                done += 1
                if done % 25 == 0:
                    print(f"    Processed {done}/{len(granules)} {short_name} granules", flush=True)
    rows.sort(key=lambda row: (row["date"], row["product"], row["granule"]))
    errors.sort(key=lambda e: e["granule"])
    return {"observations": rows, "errors_count": len(errors), "errors_sample": errors[:25]}


def main() -> None:
    print("NASA Earthdata login: follow the browser/login prompt if requested.", flush=True)
    earthaccess.login()
    data: dict[str, Any] = {
        "schema_version": "1.0",
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "period": [START, END],
        "source_note": (
            "NASA POWER point climate summaries and NASA HLS NDVI observations. "
            "Each location uses a roughly 0.1-degree box around a sample point, not a district-wide average."
        ),
        "ndvi_method": {
            "formula": "(NIR - Red) / (NIR + Red)",
            "hls_s30_bands": {"red": "B04", "nir": "B8A"},
            "hls_l30_bands": {"red": "B04", "nir": "B05"},
            "fmask_bad_bits": [1, 2, 3, 4],
            "cloud_cover_search_filter_percent": None,
        },
        "districts": {},
    }

    for name, (lat, lon) in SITES.items():
        print(f"\nFetching {name} climate data…", flush=True)
        try:
            climate = annual_power(lat, lon)
        except Exception as exc:
            climate = {}
            data.setdefault("errors", []).append({"district": name, "stage": "NASA POWER", "error": str(exc)[:500]})
            print(f"  Climate fetch failed for {name}: {exc}", flush=True)
        print(f"Fetching {name} HLS NDVI data…", flush=True)
        try:
            ndvi = ndvi_series(lat, lon)
        except Exception as exc:
            ndvi = {"observations": [], "errors_count": 1, "errors_sample": [{"error": str(exc)[:500]}]}
            data.setdefault("errors", []).append({"district": name, "stage": "HLS NDVI", "error": str(exc)[:500]})
            print(f"  HLS fetch failed for {name}: {exc}", flush=True)
        data["districts"][name] = {"lat": lat, "lon": lon, "climate_annual": climate, "ndvi": ndvi}
        # Save progress after each location, so a later interruption does not lose all results.
        with open("data.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"Saved progress to data.json for {name}.", flush=True)
        time.sleep(0.5)

    print("\nFinished. Wrote data.json in the current folder.", flush=True)
    print("Review data.json errors and observation counts before uploading it to the app.", flush=True)


if __name__ == "__main__":
    main()
