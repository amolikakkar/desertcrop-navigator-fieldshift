"""Refresh only the NASA POWER weather in ../app/data.json, for all three districts.

It re-collects, from 2021-01-01: yearly rain and temperature (as before), plus for each year rain by month,
days with a daytime high of 40 C or more (by month and in total) and root-zone soil wetness by month.
NASA POWER is public, so no NASA Earthdata login is needed. The satellite greenness readings are not touched.

Usage (Windows, in this folder):
    py update_weather.py              same last date as the data file already has
    py update_weather.py 2026-11-30   a new last date

Before saving, it lists every change to the yearly figures that were already in the file, so a refresh
with the same last date can be checked to change nothing but add the new fields.
"""
import sys, json, datetime as dt
import fetch_nasa_data as f
from update_data import DATA, save, now

KEPT = ("last_day", "rain_mm", "mean_tmax_c", "mean_tmin_c", "valid_rain_days", "valid_tmax_days", "valid_tmin_days")


def main(argv):
    data = json.loads(DATA.read_text(encoding="utf-8"))
    end = argv[1] if len(argv) > 1 else data["period"][1]
    dt.date.fromisoformat(end)  # stops here if the date is not YYYY-MM-DD
    total_changes = 0
    for name, d in data["districts"].items():
        lat, lon = d["lat"], d["lon"]
        print(f"{name} ({lat}, {lon}): collecting NASA POWER weather, 2021-01-01 to {end} ...", flush=True)
        f.START, f.END = "2021-01-01", end
        new = f.annual_power(lat, lon)
        changes = []
        for year, old in d.get("climate", {}).items():
            n = new.get(year)
            if n is None:
                changes.append(f"{year}: missing in the new data")
                continue
            changes += [f"{year} {k}: {old.get(k)} -> {n.get(k)}" for k in KEPT if old.get(k) != n.get(k)]
        print(f"  changes to figures already in the file: {len(changes)}", flush=True)
        for c in changes:
            print("   ", c, flush=True)
        total_changes += len(changes)
        full = [y for y, c in new.items() if (c.get("last_day") or "").endswith("-12-31")]
        late_hot = {y: (new[y]["days_40c_month"][10] or 0) + (new[y]["days_40c_month"][11] or 0) for y in full}
        print(f"  days of 40 C or more in November-December of complete years: {late_hot}", flush=True)
        for y in sorted(new):
            c = new[y]
            print(f"  {y}: rain {c['rain_mm']} mm (months add up to {round(sum(v or 0 for v in c['rain_month_mm']), 1)}), "
                  f"days >= 40 C {c['days_40c']}, soil wetness by month {c.get('soil_wet_month')}", flush=True)
        d["climate"] = new
    data["period"] = [data["period"][0], end]
    data["weather_refreshed"] = now()
    data["weather_fields"] = {
        "source": "NASA POWER daily point data (community AG), MERRA-2 based model values, not gauge readings",
        "rain_month_mm": "rain per month (PRECTOTCORR sum), January first",
        "days_40c_month": "days per month with a daytime high (T2M_MAX) of 40 C or more",
        "soil_wet_month": "mean root-zone soil wetness per month (GWETROOT; 0 = dry, 1 = saturated); a model value, not SMAP",
    }
    save(data)
    print(f"Saved. Changes to figures already in the file: {total_changes}.", flush=True)
    print("WEATHER DONE", flush=True)


if __name__ == "__main__":
    main(sys.argv)
