"""Add the latest NASA POWER climate and HLS NDVI to ../app/data.json, one district per run.

Usage (Windows, in this folder):
    py update_data.py Jodhpur
    py update_data.py all
    py update_data.py Jodhpur 2026-11-09 2024-01-01
    py update_data.py all 2026-11-09 2024-01-01 Jodhpur=2026-01-01
  1st value: district (Jodhpur, Barmer or Sikar), or "all" for the three in turn after one login
  2nd value: last date to collect (default: 2 days ago)
  3rd value: first date for greenness (NDVI) (default: 2024-01-01)
  Then, optionally: District=YYYY-MM-DD to start that district's greenness on another date, or
  District=skip to leave that district out.

Rainfall and temperature are always re-collected from 2021-01-01.
Greenness is collected one calendar year at a time, and data.json is saved after each year, so a
dropped connection loses at most the year in progress. Re-collected dates replace older readings.
If the sample point in fetch_nasa_data.SITES has moved, readings from the old point are removed.
A year is not saved if more than a fifth of its images could not be read (usually a network or login
problem). Its earlier readings are kept, and the year is tried again.

Each district runs in a helper process. If the helper stops unexpectedly (on 11 Nov 2026 a reading library
stopped Python after about two hours, with no message), this script starts it again from the last saved
year by itself, up to 5 times in a row without a newly saved year. The helper receives this run's login
token in memory, through its environment; nothing is written to a file. Crash tracing is on in the helper:
if Python is stopped, the lines it was running are printed.

Needs: earthaccess rasterio numpy requests, and a NASA Earthdata login. The login is typed when asked
(or read from an EARTHDATA_TOKEN environment variable) and is never saved to a file.
"""
import sys, os, re, json, time, logging, subprocess, traceback, datetime as dt
from pathlib import Path
import earthaccess
import fetch_nasa_data as f

DATA = Path(__file__).resolve().parent.parent / "app" / "data.json"
HELPER = "--helper"
HELPER_MODE = False          # True inside the helper process
MAX_RESTARTS = 5             # restarts in a row without a newly saved year
RESTART_PAUSE_S = 60
MAX_UNREADABLE_SHARE = 0.2   # a year with a larger share of unreadable images is not saved


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def save(data):
    text = json.dumps(data, indent=1)
    tmp = DATA.with_name(DATA.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    # Swap in one step, so an interruption never leaves a half-written file. On Windows another program
    # (antivirus, file preview, an editor) can hold either file for a moment, so retry before giving up.
    for attempt in range(40):
        try:
            os.replace(tmp, DATA)
            return
        except PermissionError:
            time.sleep(0.5)
    DATA.write_text(text, encoding="utf-8")  # last resort: write in place
    try:
        tmp.unlink()
    except OSError:
        pass
    print("  (data.json was busy, so it was written in place instead of swapped.)", flush=True)


def update(name, end, ndvi_start):
    data = json.loads(DATA.read_text(encoding="utf-8"))
    lat, lon = f.SITES[name]
    d = data["districts"].setdefault(name, {"lat": lat, "lon": lon, "climate": {}, "ndvi": []})
    if (d.get("lat"), d.get("lon")) != (lat, lon):
        print(f"{name}: sample point moved from {d.get('lat')},{d.get('lon')} to {lat},{lon}. "
              f"Removing {len(d.get('ndvi', []))} greenness readings taken at the old point.", flush=True)
        d["ndvi"] = []
        d.pop("ndvi_errors", None)
        d.pop("ndvi_from", None)
    d["lat"], d["lon"] = lat, lon
    d["box_half_deg"] = f.HALF_DEGREES
    data["note"] = "Each district is a ~10 km box around its lat/lon point, not the whole district."
    data["ndvi_method"] = {
        "formula": "(NIR - Red) / (NIR + Red)",
        "cloud_mask": "HLS Fmask bits 1-4 excluded (cloud, adjacent, shadow, snow/ice)",
        "tile_cloud_cover_filter": None,
    }

    print(f"{name}: collecting rainfall and temperature, 2021-01-01 to {end} ...", flush=True)
    f.START, f.END = "2021-01-01", end
    d["climate"] = f.annual_power(lat, lon)
    d["updated_to"] = end
    data["period"] = ["2021-01-01", end]
    data["generated"] = now()
    save(data)
    print(f"{name}: rainfall and temperature saved.", flush=True)

    start, stop = dt.date.fromisoformat(ndvi_start), dt.date.fromisoformat(end)
    d["ndvi_from"] = min(d.get("ndvi_from", ndvi_start), ndvi_start)
    errors = d.setdefault("ndvi_errors", {})

    # Before using the faster reading method, read a few real images both ways and require identical
    # pixels. If anything differs or the check cannot finish, use the original (slower) way for this run.
    print(f"\n{name}: checking that the faster reading method gives identical pixels ...", flush=True)
    first_b = min(stop, dt.date(start.year, 12, 31)).isoformat()
    fast, message = f.check_fast_read(lat, lon, start.isoformat(), first_b)
    print(f"  {'OK' if fast else 'Not used'}: {message}.", flush=True)
    if not fast:
        print("  Using the original, slower method for this run.", flush=True)

    for year in range(start.year, stop.year + 1):
        a = max(start, dt.date(year, 1, 1)).isoformat()
        b = min(stop, dt.date(year, 12, 31)).isoformat()
        print(f"\n{name}: collecting greenness, {a} to {b} ...", flush=True)
        f.START, f.END = a, b
        res = f.ndvi_series(lat, lon, fast=fast)
        new = [{"date": o["date"], "product": o["product"], "ndvi": o["ndvi_mean"],
                "valid_pct": o["valid_pct"]} for o in res["observations"]]
        total = len(res["observations"]) + res["errors_count"]
        if res["errors_count"] and (not new or res["errors_count"] > MAX_UNREADABLE_SHARE * total):
            raise RuntimeError(f"{name} {year}: {res['errors_count']} of {total} images could not be read, so "
                               f"this year was not saved (its earlier readings are kept). This usually means "
                               f"a network or login problem.")
        kept = [o for o in d["ndvi"] if not (a <= o["date"] <= b)]
        d["ndvi"] = sorted(kept + new, key=lambda o: (o["date"], o["product"]))
        errors[str(year)] = res["errors_count"]
        data["generated"] = now()
        save(data)
        print(f"{name} {year}: saved {len(new)} greenness readings ({res['errors_count']} images could "
              f"not be read).", flush=True)
        if year < stop.year and not HELPER_MODE:
            print(f"  If the run stops before the next year is saved, continue with:\n"
                  f"  py update_data.py {name} {end} {year + 1}-01-01", flush=True)
    print(f"\nDone: {name} is up to date to {end}.", flush=True)


# ---- Helper process and automatic restart (added 11 Nov 2026) ----

def helper_command(name, end, ndvi_start):
    # -X faulthandler: if Python is stopped by a crash, print the lines each thread was running.
    return [sys.executable, "-X", "faulthandler", str(Path(__file__).resolve()), HELPER, name, end, ndvi_start]


def _crash_tracing():
    # GDAL reports a fatal error through rasterio's logger just before it stops the program, but rasterio
    # hides those messages by default. Show them (fatal ones only, so normal runs stay quiet).
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logging.CRITICAL)
    handler.setFormatter(logging.Formatter("  Reading library fatal error: %(message)s"))
    logging.getLogger("rasterio").addHandler(handler)


def helper_main(name, end, ndvi_start):
    """Runs inside the helper process started by run_helper()."""
    global HELPER_MODE
    HELPER_MODE = True
    _crash_tracing()
    code = 0
    try:
        earthaccess.login(strategy="environment", persist=False)  # this run's token, handed over in memory
        if not earthaccess.__auth__.authenticated:
            raise RuntimeError("The helper could not use this run's login.")
        update(name, end, ndvi_start)
    except Exception:
        traceback.print_exc()
        code = 1
    # Close straight away once the work is saved: background connection threads in the reading libraries
    # can otherwise keep Python from closing, and the main script waits for the helper to close.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


def run_helper(name, end, ndvi_start, token):
    """Run one district in a helper process, restarting it from the last saved year if it stops.
    Returns (finished, greenness start date to continue from)."""
    env = dict(os.environ, EARTHDATA_TOKEN=token, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    last_year = dt.date.fromisoformat(end).year
    saved_line = re.compile(rf"{re.escape(name)} (\d{{4}}): saved ")
    start, misses = ndvi_start, 0
    while True:
        saved = []
        proc = subprocess.Popen(helper_command(name, end, start), env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        try:
            for line in proc.stdout:
                print(line, end="", flush=True)
                m = saved_line.match(line)
                if m:
                    saved.append(int(m.group(1)))
            code = proc.wait()
        except KeyboardInterrupt:
            proc.kill()
            proc.wait()
            print(f"\n{name}: stopped by you. Everything saved so far is kept.", flush=True)
            return False, (f"{max(saved) + 1}-01-01" if saved else start)
        if saved:
            start = f"{max(saved) + 1}-01-01"
        if code == 0:
            return True, None
        print(f"\n{name}: the helper stopped unexpectedly (exit code {code & 0xFFFFFFFF:#x}). "
              f"Everything saved so far is kept.", flush=True)
        if saved and max(saved) >= last_year:
            print(f"{name}: every year had already been saved, so nothing needs to be redone.", flush=True)
            return True, None
        misses = 1 if saved else misses + 1
        if misses > MAX_RESTARTS:
            print(f"{name}: it stopped {misses} times in a row without saving a new year, so the run "
                  f"stops here.", flush=True)
            return False, start
        print(f"{name}: starting again from {start} in {RESTART_PAUSE_S} s "
              f"(restart {misses} of {MAX_RESTARTS} allowed in a row) ...\n", flush=True)
        try:
            time.sleep(RESTART_PAUSE_S)
        except KeyboardInterrupt:
            print(f"\n{name}: stopped by you. Everything saved so far is kept.", flush=True)
            return False, start


def parse_args(argv):
    """Return (names, end, ndvi_start, starts); starts maps a district to its own start date or 'skip'."""
    if len(argv) < 2 or (argv[1] not in f.SITES and argv[1] != "all"):
        sys.exit(__doc__)
    names = list(f.SITES) if argv[1] == "all" else [argv[1]]
    end = argv[2] if len(argv) > 2 else (dt.date.today() - dt.timedelta(days=2)).isoformat()
    ndvi_start = argv[3] if len(argv) > 3 else "2024-01-01"
    dt.date.fromisoformat(end), dt.date.fromisoformat(ndvi_start)  # stop early on a mistyped date
    starts = {}
    for item in argv[4:]:
        district, _, value = item.partition("=")
        if district not in names or not value:
            sys.exit(f"Not understood: {item}. Use District=YYYY-MM-DD or District=skip.")
        if value != "skip":
            dt.date.fromisoformat(value)
        starts[district] = value
    if any(v != "skip" and v > end for v in [ndvi_start, *starts.values()]):
        sys.exit("A greenness start date is after the end date.")
    return names, end, ndvi_start, starts


def continue_command(first_arg, names, i, end, ndvi_start, starts, continue_from):
    """The command that carries on where a stopped run left off, without redoing finished districts."""
    if first_arg != "all":
        return f"py update_data.py {names[i]} {end} {continue_from}"
    extra = [f"{n}=skip" for n in names[:i]] + [f"{names[i]}={continue_from}"]
    extra += [f"{n}={starts[n]}" for n in names[i + 1:] if n in starts]
    return f"py update_data.py all {end} {ndvi_start} " + " ".join(extra)


def main(argv):
    names, end, ndvi_start, starts = parse_args(argv)
    auth = earthaccess.login(persist=False)  # asks for the login; never writes it to a file
    token = (getattr(auth, "token", None) or {}).get("access_token")
    if not getattr(auth, "authenticated", False) or not token:
        sys.exit("The Earthdata login did not work. Please run the command again and check the username "
                 "and password.")
    for i, name in enumerate(names):
        start = starts.get(name, ndvi_start)
        if start == "skip":
            print(f"{name}: left out, as asked.\n", flush=True)
            continue
        finished, continue_from = run_helper(name, end, start, token)
        if not finished:
            cmd = continue_command(argv[1], names, i, end, ndvi_start, starts, continue_from)
            print(f"\nTo continue later, run:\n  {cmd}", flush=True)
            sys.exit(1)
        print("", flush=True)
    print("All done.", flush=True)


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == HELPER:
        helper_main(*sys.argv[2:5])
    else:
        main(sys.argv)
