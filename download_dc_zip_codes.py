#!/usr/bin/env python3
"""
Download Washington, DC ZIP-code polygons from the official DC GIS
ArcGIS FeatureServer and save them as GeoJSON.

Output:
    Data/Raw/dc_zip_codes.geojson

Run:
    pip install requests
    python download_dc_zip_codes.py
"""

from pathlib import Path
import json
import requests

BASE = Path(__file__).resolve().parent
RAW = BASE / "Data" / "Raw"
RAW.mkdir(parents=True, exist_ok=True)

endpoint = (
    "https://maps2.dcgis.dc.gov/dcgis/rest/services/"
    "DCGIS_DATA/Location_WebMercator/FeatureServer/4/query"
)

params = {
    "where": "1=1",
    "outFields": "*",
    "returnGeometry": "true",
    "outSR": "4326",
    "f": "geojson",
}

response = requests.get(
    endpoint,
    params=params,
    timeout=120,
)

response.raise_for_status()

payload = response.json()

if payload.get("type") != "FeatureCollection":
    raise RuntimeError(
        "The DC GIS response was not a GeoJSON FeatureCollection."
    )

output = RAW / "dc_zip_codes.geojson"

with output.open("w", encoding="utf-8") as f:
    json.dump(payload, f)

print(f"Saved: {output}")
print(f"Features: {len(payload.get('features', []))}")
