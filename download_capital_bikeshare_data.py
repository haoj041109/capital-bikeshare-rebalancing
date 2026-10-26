#!/usr/bin/env python3
"""
Project 2 data downloader — CSV-first, robust ZIP/encoding version.

Final outputs:
1) Data/Raw/capital_bikeshare_trips_2025_01.csv
2) Data/Raw/capital_bikeshare_stations.csv
3) Data/Raw/capital_bikeshare_station_information.csv
4) Data/Raw/capital_bikeshare_station_status.csv
5) Data/Raw/source_manifest.csv

Run:
    pip install requests pandas
    python download_capital_bikeshare_data_csv_fixed.py
"""

from pathlib import Path
from datetime import datetime, timezone
import hashlib
import tempfile
import xml.etree.ElementTree as ET
import zipfile

import pandas as pd
import requests


BASE = Path(__file__).resolve().parent
RAW = BASE / "Data" / "Raw"
RAW.mkdir(parents=True, exist_ok=True)

session = requests.Session()
session.headers.update({
    "User-Agent": "UW-ACMS-Capital-Bikeshare-Optimization-Project/1.0"
})


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path, params=None) -> Path:
    print(f"Downloading: {url}")
    with session.get(url, params=params, stream=True, timeout=120) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
    print(f"Downloaded: {dest.name}")
    return dest


def read_csv_robust(path: Path) -> pd.DataFrame:
    encodings = ("utf-8", "utf-8-sig", "cp1252", "latin1")
    last_error = None

    for encoding in encodings:
        try:
            df = pd.read_csv(path, low_memory=False, encoding=encoding)
            print(f"Read CSV: {path.name} [encoding={encoding}]")
            return df
        except UnicodeDecodeError as exc:
            last_error = exc

    raise RuntimeError(
        f"Could not decode {path} with {encodings}"
    ) from last_error


def find_trip_key(prefix="202501") -> str:
    bucket = "https://s3.amazonaws.com/capitalbikeshare-data"

    r = session.get(
        bucket,
        params={"list-type": "2", "prefix": prefix},
        timeout=60,
    )
    r.raise_for_status()

    root = ET.fromstring(r.content)

    keys = []
    for elem in root.iter():
        if elem.tag.endswith("Key") and elem.text:
            keys.append(elem.text)

    candidates = [
        key for key in keys
        if prefix in key
        and (
            key.lower().endswith(".zip")
            or key.lower().endswith(".csv")
        )
    ]

    if not candidates:
        raise RuntimeError(
            f"No trip-data object found for prefix {prefix} "
            "in the official Capital Bikeshare bucket."
        )

    candidates.sort(
        key=lambda key: (not key.lower().endswith(".zip"), key)
    )

    return candidates[0]


def save_gbfs_feed_as_csv(feed_url: str, output_path: Path) -> pd.DataFrame:
    r = session.get(feed_url, timeout=60)
    r.raise_for_status()
    payload = r.json()

    station_records = payload.get("data", {}).get("stations", [])

    if not station_records:
        raise RuntimeError(
            f"No station records found in GBFS feed: {feed_url}"
        )

    df = pd.json_normalize(station_records)

    df.insert(
        0,
        "snapshot_downloaded_at_utc",
        datetime.now(timezone.utc).isoformat(),
    )

    df.to_csv(
        output_path,
        index=False,
        encoding="utf-8"
    )

    print(
        f"Saved: {output_path.name} "
        f"({len(df):,} rows, {df.shape[1]} columns)"
    )

    return df


manifest_rows = []

print("\n--- 1. January 2025 trip history ---")

bucket_base = "https://s3.amazonaws.com/capitalbikeshare-data"
trip_key = find_trip_key("202501")
trip_url = f"{bucket_base}/{trip_key}"
trip_output = RAW / "capital_bikeshare_trips_2025_01.csv"

with tempfile.TemporaryDirectory() as tmp:
    tmp_dir = Path(tmp)
    temp_download = tmp_dir / Path(trip_key).name

    download(trip_url, temp_download)

    if temp_download.suffix.lower() == ".zip":
        extract_dir = tmp_dir / "extracted"
        extract_dir.mkdir()

        with zipfile.ZipFile(temp_download, "r") as z:
            members = [
                name
                for name in z.namelist()
                if name.lower().endswith(".csv")
                and "__MACOSX" not in name
                and not Path(name).name.startswith("._")
            ]

            if not members:
                raise RuntimeError(
                    "The downloaded ZIP contains no usable CSV files."
                )

            print("Usable trip CSV files inside ZIP:")
            for name in members:
                print(f"  {name}")

            for member in members:
                z.extract(member, extract_dir)

        csv_files = [
            extract_dir / member
            for member in members
        ]

        frames = [
            read_csv_robust(path)
            for path in csv_files
        ]

        trips = pd.concat(
            frames,
            ignore_index=True
        )

    elif temp_download.suffix.lower() == ".csv":
        trips = read_csv_robust(temp_download)

    else:
        raise RuntimeError(
            f"Unsupported trip-data file type: {temp_download.suffix}"
        )

trips.to_csv(
    trip_output,
    index=False,
    encoding="utf-8"
)

print(
    f"Saved: {trip_output.name} "
    f"({len(trips):,} rows, {trips.shape[1]} columns)"
)

manifest_rows.append({
    "file": trip_output.name,
    "source": "Capital Bikeshare official trip-history S3 bucket",
    "source_url": trip_url,
    "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
    "rows": len(trips),
    "columns": trips.shape[1],
    "sha256": sha256_file(trip_output),
})


print("\n--- 2. Station metadata ---")

station_url = (
    "https://opendata.dc.gov/api/download/v1/items/"
    "a1f7acf65795451d89f0a38565a975b3/csv?layers=5"
)

station_output = RAW / "capital_bikeshare_stations.csv"

download(
    station_url,
    station_output
)

stations = read_csv_robust(
    station_output
)

print(
    f"Station metadata: "
    f"{len(stations):,} rows, "
    f"{stations.shape[1]} columns"
)

manifest_rows.append({
    "file": station_output.name,
    "source": "DC Open Data / DC GIS Capital Bikeshare Locations",
    "source_url": station_url,
    "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
    "rows": len(stations),
    "columns": stations.shape[1],
    "sha256": sha256_file(station_output),
})


print("\n--- 3. GBFS station feeds ---")

gbfs_root_url = (
    "https://gbfs.capitalbikeshare.com/gbfs/2.3/gbfs.json"
)

r = session.get(
    gbfs_root_url,
    timeout=60
)
r.raise_for_status()

gbfs_root = r.json()

feeds = gbfs_root["data"]["en"]["feeds"]

feed_urls = {
    item["name"]: item["url"]
    for item in feeds
}


station_info_output = (
    RAW / "capital_bikeshare_station_information.csv"
)

station_info = save_gbfs_feed_as_csv(
    feed_urls["station_information"],
    station_info_output,
)

manifest_rows.append({
    "file": station_info_output.name,
    "source": "Capital Bikeshare GBFS station_information",
    "source_url": feed_urls["station_information"],
    "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
    "rows": len(station_info),
    "columns": station_info.shape[1],
    "sha256": sha256_file(station_info_output),
})


station_status_output = (
    RAW / "capital_bikeshare_station_status.csv"
)

station_status = save_gbfs_feed_as_csv(
    feed_urls["station_status"],
    station_status_output,
)

manifest_rows.append({
    "file": station_status_output.name,
    "source": "Capital Bikeshare GBFS station_status",
    "source_url": feed_urls["station_status"],
    "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
    "rows": len(station_status),
    "columns": station_status.shape[1],
    "sha256": sha256_file(station_status_output),
})


manifest_output = RAW / "source_manifest.csv"

pd.DataFrame(
    manifest_rows
).to_csv(
    manifest_output,
    index=False,
    encoding="utf-8",
)

print(
    f"\nSaved: {manifest_output.name}"
)

print("\nFinished. Final CSV files:")

for path in sorted(
    RAW.glob("*.csv")
):
    print(f"  {path.name}")

print(
    "\nNext step: inspect schema, missing values, "
    "station IDs, and station matching."
)
