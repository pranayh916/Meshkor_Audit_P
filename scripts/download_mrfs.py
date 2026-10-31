"""Download hospital price files (MRFs) listed in each hospital's cms-hpt.txt.

Run from the infusion-audit folder:
    pip install requests
    python download_mrfs.py

What it does:
1. In each data/raw_essential_inputs/hospital_mrf/<system>/ folder, finds the .txt index file.
2. Moves it to <system>/<DATE>/cms-hpt.txt.
3. Reads every location-name + mrf-url pair.
4. Skips out-of-state locations (list below).
5. Downloads each unique mrf-url once into <system>/<DATE>/.
6. Writes data/raw_essential_inputs/hospital_mrf/mrf_download_log.csv.

Safe to re-run: files already downloaded are skipped.
"""
import csv
import hashlib
import re
import shutil
import socket
import sys
import time
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import requests
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.common import paths

ROOT = paths()["raw"] / "hospital_mrf"
DATE = date.today().isoformat()
LOG = ROOT / "mrf_download_log.csv"

# Locations outside Ohio. Matched against location-name (lowercase).
NON_OHIO = [
    "florida weston",        # Cleveland Clinic, FL
    "indian river",          # Cleveland Clinic, FL
    "martin north",          # Cleveland Clinic, FL
    "martin south",          # Cleveland Clinic, FL
    "tradition hospital",    # Cleveland Clinic, FL
    "lourdes hospital",      # Mercy, Paducah KY
    "marcum wallace",        # Mercy, Irvine KY
    "hickman",               # ProMedica, Adrian MI
    "monroe regional",       # ProMedica, Monroe MI
]

MAX_TRIES = 50  # upper limit per file; each failed try resumes where it stopped

HEADERS = {"User-Agent": "Mozilla/5.0 (infusion-audit research download)"}


def parse_index(text: str) -> list[tuple[str, str]]:
    """Return (location_name, mrf_url) pairs. Handles 'mrf-url:https...' with no space."""
    pairs, loc = [], None
    for line in text.splitlines():
        m = re.match(r"\s*location-name:\s*(.+)", line, re.I)
        if m:
            loc = m.group(1).strip()
            continue
        m = re.match(r"\s*mrf-url:\s*(\S+)", line, re.I)
        if m and loc:
            pairs.append((loc, m.group(1).strip()))
            loc = None
    return pairs


def is_non_ohio(loc: str) -> bool:
    low = loc.lower()
    return any(k in low for k in NON_OHIO)


def file_name_for(url: str, resp: requests.Response) -> str:
    # 1. Content-Disposition header
    cd = resp.headers.get("Content-Disposition", "")
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd, re.I)
    if m:
        return unquote(m.group(1)).strip()
    # 2. ?name= query parameter (ProMedica / Canto)
    q = parse_qs(urlparse(url).query)
    if "name" in q:
        return unquote(q["name"][0]).replace("+", " ").replace(" ", "_")
    # 3. Last path segment, add extension from content type if missing
    name = Path(urlparse(url).path).name or "mrf_file"
    if "." not in name:
        ct = resp.headers.get("Content-Type", "")
        ext = ".json" if "json" in ct else ".csv" if "csv" in ct else ".zip" if "zip" in ct else ".dat"
        name += ext
    return name


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_sha256_sidecar(path: Path, digest: str) -> None:
    sidecar = path.with_name(path.name + ".sha256")
    temporary = sidecar.with_name(sidecar.name + ".part")
    temporary.write_text(f"{digest}  {path.name}\n", encoding="ascii")
    temporary.replace(sidecar)


def prepare_index(system_dir: Path) -> Path | None:
    # Use the newest date folder that already holds cms-hpt.txt.
    existing = sorted(system_dir.glob("*/cms-hpt.txt"))
    if existing:
        return existing[-1]
    day_dir = system_dir / DATE
    target = day_dir / "cms-hpt.txt"
    txts = [p for p in system_dir.glob("*.txt")]
    if not txts:
        return None
    day_dir.mkdir(exist_ok=True)
    shutil.move(str(txts[0]), target)
    return target


def internet_ok() -> bool:
    try:
        socket.gethostbyname("www.cms.gov")
        return True
    except OSError:
        return False


def main() -> None:
    if not internet_ok():
        print("No internet / DNS. Check Wi-Fi or VPN, then run again.")
        return
    # Usage: python download_mrfs.py --skip uh_cleveland promedica
    skip = set(sys.argv[sys.argv.index("--skip") + 1:]) if "--skip" in sys.argv else set()
    log_rows = []
    for system_dir in sorted(p for p in ROOT.iterdir() if p.is_dir()):
        if system_dir.name in skip:
            print(f"[{system_dir.name}] skipped by --skip")
            log_rows.append({"system": system_dir.name, "status": "skipped by user, download later"})
            continue
        index = prepare_index(system_dir)
        if index is None:
            print(f"[{system_dir.name}] no cms-hpt.txt, skipped")
            log_rows.append({"system": system_dir.name, "status": "no cms-hpt.txt"})
            continue

        pairs = parse_index(index.read_text(encoding="utf-8", errors="replace"))
        by_url: dict[str, list[str]] = {}
        for loc, url in pairs:
            by_url.setdefault(url, []).append(loc)

        for url, locs in by_url.items():
            ohio_locs = [l for l in locs if not is_non_ohio(l)]
            row = {"system": system_dir.name, "locations": " | ".join(locs), "mrf_url": url}
            if not ohio_locs:
                row["status"] = "skipped non-Ohio"
                log_rows.append(row)
                print(f"[{system_dir.name}] skip non-Ohio: {locs[0]}")
                continue
            tag = hashlib.sha1(url.encode()).hexdigest()[:8]
            done = [p for p in index.parent.glob(f"*__{tag}*")
                    if not p.name.endswith(".part") and p.stat().st_size > 0]
            if done:
                out = done[0]
                digest = sha256(out)
                write_sha256_sidecar(out, digest)
                row.update(status="already downloaded", file_name=out.name,
                           size_bytes=out.stat().st_size, sha256=digest)
                print(f"[{system_dir.name}] already downloaded: {out.name}")
                log_rows.append(row)
                continue
            last_err = None
            no_progress = 0
            attempt = 0
            # Keep trying while each try adds data; stop after 3 tries in a row with none.
            while no_progress < 3 and attempt < MAX_TRIES:
                attempt += 1
                parts = list(index.parent.glob(f"*__{tag}*.part"))
                start = parts[0].stat().st_size if parts else 0
                req_headers = dict(HEADERS)
                if start:
                    req_headers["Range"] = f"bytes={start}-"
                try:
                    print(f"[{system_dir.name}] try {attempt}, from {start / 1048576:,.0f} MB: "
                          f"{url[-60:]}", flush=True)
                    # (connect timeout, read timeout): no data for 60 s = fail and retry.
                    with requests.get(url, headers=req_headers, stream=True, timeout=(30, 60)) as r:
                        r.raise_for_status()
                        if start and r.status_code == 206:
                            tmp = parts[0]
                            name = tmp.name[:-len(".part")]
                            mode = "ab"            # server supports resume: append
                        else:
                            base = Path(file_name_for(url, r))
                            # URL tag keeps file names unique when a site reuses one name.
                            name = f"{base.stem}__{tag}{base.suffix}"
                            tmp = index.parent / (name + ".part")
                            mode, start = "wb", 0  # no resume: start over
                        out = index.parent / name
                        got, next_mark, t0 = start, start + 100 * 1048576, time.time()
                        with tmp.open(mode) as f:
                            for chunk in r.iter_content(1024 * 1024):
                                f.write(chunk)
                                got += len(chunk)
                                if got >= next_mark:
                                    rate = (got - start) / 1048576 / max(time.time() - t0, 1)
                                    print(f"    {got / 1048576:,.0f} MB ({rate:,.1f} MB/s)",
                                          flush=True)
                                    next_mark += 100 * 1048576
                        tmp.replace(out)
                    size = out.stat().st_size
                    head = out.open("rb").read(200).lower()
                    status = "ok"
                    if b"<html" in head or b"<!doctype html" in head:
                        status = "ERROR got HTML page, not data"
                    digest = sha256(out)
                    write_sha256_sidecar(out, digest)
                    row.update(status=status, file_name=name, size_bytes=size, sha256=digest)
                    print(f"[{system_dir.name}] {status}: {name} ({size:,} bytes)")
                    last_err = None
                    break
                except Exception as e:  # noqa: BLE001
                    last_err = e
                    now = list(index.parent.glob(f"*__{tag}*.part"))
                    grew = bool(now) and now[0].stat().st_size > start
                    no_progress = 0 if grew else no_progress + 1
                    print(f"[{system_dir.name}] try {attempt} stopped: {type(e).__name__}. "
                          f"Will resume.", flush=True)
                    time.sleep(10)
            if last_err is not None:
                row["status"] = f"ERROR {type(last_err).__name__}: {last_err}"
                print(f"[{system_dir.name}] FAILED {url}")
            log_rows.append(row)

    fields = ["system", "locations", "mrf_url", "file_name", "size_bytes", "sha256", "status"]
    with LOG.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(log_rows)
    print(f"\nLog written: {LOG}")


if __name__ == "__main__":
    main()
