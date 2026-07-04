#!/usr/bin/env python3
from __future__ import annotations

import json
import math
from pathlib import Path

PI = math.pi
A = 6378245.0
EE = 0.00669342162296594323
EARTH_R = 6371000.0


# ============================================================
# 1) 在这里填手机采点
#    格式：("名字", 经度GCJ02, 纬度GCJ02)
#    第一个必须是起飞点 anchor，后面至少 4 个中轴线点
# ============================================================

POINTS_GCJ02 = [
    # 示例：把下面这些替换成你实际采到的 5 个点
     ("anchor", 108.64264462, 34.10363631),
     ("CL_1",   108.64275451, 34.10363913),
     ("CL_2",   108.64299928, 34.10362780),
     ("CL_3",   108.64309286, 34.10363650),
     ("CL_4",   108.64335191, 34.10363875),

    #("anchor", 108.64761266, 34.10537959),
]

PROFILE_ID = "field_centerline_wgs84"
PROFILE_NAME = "Field Centerline WGS84"
OUTPUT_PATH = "runtime/field_profiles/field_centerline_wgs84.json"


# ============================================================
# 2) GCJ-02 <-> WGS84 转换
# ============================================================

def out_of_china(lat: float, lon: float) -> bool:
    return not (72.004 <= lon <= 137.8347 and 0.8293 <= lat <= 55.8271)


def transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * PI) + 20.0 * math.sin(2.0 * x * PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * PI) + 40.0 * math.sin(y / 3.0 * PI)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * PI) + 320.0 * math.sin(y * PI / 30.0)) * 2.0 / 3.0
    return ret


def transform_lon(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * PI) + 20.0 * math.sin(2.0 * x * PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * PI) + 40.0 * math.sin(x / 3.0 * PI)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * PI) + 300.0 * math.sin(x / 30.0 * PI)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lat: float, lon: float) -> tuple[float, float]:
    if out_of_china(lat, lon):
        return lat, lon

    dlat = transform_lat(lon - 105.0, lat - 35.0)
    dlon = transform_lon(lon - 105.0, lat - 35.0)

    radlat = lat / 180.0 * PI
    magic = math.sin(radlat)
    magic = 1.0 - EE * magic * magic
    sqrtmagic = math.sqrt(magic)

    dlat = (dlat * 180.0) / ((A * (1.0 - EE)) / (magic * sqrtmagic) * PI)
    dlon = (dlon * 180.0) / (A / sqrtmagic * math.cos(radlat) * PI)

    return lat + dlat, lon + dlon


def gcj02_to_wgs84(lat_gcj: float, lon_gcj: float, iterations: int = 8) -> tuple[float, float]:
    """Iterative inverse. Output: WGS84 lat/lon."""
    if out_of_china(lat_gcj, lon_gcj):
        return lat_gcj, lon_gcj

    lat_wgs = lat_gcj
    lon_wgs = lon_gcj

    for _ in range(iterations):
        lat_back, lon_back = wgs84_to_gcj02(lat_wgs, lon_wgs)
        lat_wgs -= lat_back - lat_gcj
        lon_wgs -= lon_back - lon_gcj

    return lat_wgs, lon_wgs


# ============================================================
# 3) profile 辅助计算
# ============================================================

def gps_enu_deltas(anchor_lat: float, anchor_lon: float, lat: float, lon: float) -> tuple[float, float]:
    """Return north/east delta in meters from anchor to point."""
    d_north = math.radians(lat - anchor_lat) * EARTH_R
    d_east = math.radians(lon - anchor_lon) * EARTH_R * math.cos(math.radians(anchor_lat))
    return d_north, d_east


def main() -> None:
    if len(POINTS_GCJ02) < 5:
        print("ERROR: POINTS_GCJ02 至少需要 5 个点：1 个 anchor + 4 个中轴线点")
        print("当前只有", len(POINTS_GCJ02), "个点")
        print()
        print("单点示例转换：")
        for name, lon_gcj, lat_gcj in POINTS_GCJ02:
            lat_wgs, lon_wgs = gcj02_to_wgs84(lat_gcj, lon_gcj)
            print(f"{name}: GCJ02 lon={lon_gcj:.8f}, lat={lat_gcj:.8f}")
            print(f"      WGS84 lat={lat_wgs:.8f}, lon={lon_wgs:.8f}")
        return

    converted = []
    for name, lon_gcj, lat_gcj in POINTS_GCJ02:
        lat_wgs, lon_wgs = gcj02_to_wgs84(lat_gcj, lon_gcj)
        converted.append((name, lat_wgs, lon_wgs))

    anchor_name, anchor_lat, anchor_lon = converted[0]

    centerline_points = []
    for name, lat, lon in converted[1:]:
        d_n, d_e = gps_enu_deltas(anchor_lat, anchor_lon, lat, lon)
        expected_y = math.hypot(d_n, d_e)
        centerline_points.append({
            "name": name,
            "lat": lat,
            "lon": lon,
            "expected_field_y_m": round(expected_y, 3),
        })

    profile = {
        "schema_version": 2,
        "profile_id": PROFILE_ID,
        "name": PROFILE_NAME,
        "coordinate_convention": {
            "field_x_positive": "right",
            "field_y_positive": "forward",
            "altitude_positive": "up",
        },
        "anchor": {
            "name": anchor_name,
            "lat": anchor_lat,
            "lon": anchor_lon,
            "field_x_m": 0.0,
            "field_y_m": 0.0,
        },
        "centerline_points": centerline_points,
        "gps_quality": {
            "min_fix_type": 3,
            "min_satellites": 8,
            "max_eph": 3.0,
            "max_epv": 5.0,
        },
        "field_geometry": {
            "lane_half_width_m": 4.0,
            "drop_center_y_m": 32.5,
            "recce_center_y_m": 57.5,
            "drop_area_y_min": 30.0,
            "drop_area_y_max": 35.0,
            "recce_area_y_min": 55.0,
            "recce_area_y_max": 60.0,
        },
        "binding_policy": {
            "max_start_error_m": 3.0,
            "warn_start_error_m": 1.5,
            "max_centerline_residual_m": 2.5,
            "warn_centerline_residual_m": 1.5,
        },
    }

    print("=== GCJ-02 -> WGS84 ===")
    for (name, lon_gcj, lat_gcj), (_, lat_wgs, lon_wgs) in zip(POINTS_GCJ02, converted):
        print(f"{name}:")
        print(f"  input  GCJ02  lon={lon_gcj:.8f}, lat={lat_gcj:.8f}")
        print(f"  output WGS84  lat={lat_wgs:.8f}, lon={lon_wgs:.8f}")

    print()
    print("=== Centerline expected_field_y_m ===")
    for pt in centerline_points:
        print(f"{pt['name']}: y={pt['expected_field_y_m']} m")

    out = Path(OUTPUT_PATH)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")

    print()
    print("wrote:", out)
    print("profile_id:", PROFILE_ID)


if __name__ == "__main__":
    main()
