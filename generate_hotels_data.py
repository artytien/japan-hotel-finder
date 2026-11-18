import json
import math
import os
import re
import sys
import time
from collections import defaultdict
import requests

# ==========================================
# 1. 設定區：日本 8 大精準地理分區定義
# ==========================================
DATA_DIR = "./data"
REGIONS_MAP = {
    "kansai":        {"name": "關西圈(京阪神)",       "bbox": (34.40, 135.10, 35.08, 135.85)},
    "tokyo":         {"name": "關東(首都圈)",         "bbox": (35.35, 139.45, 35.95, 140.42)},
    # 縮小東海範圍，精準鎖定名古屋・岐阜・浜松核心都會帶
    "tokai":         {"name": "東海(名古屋・浜松)",   "bbox": (34.68, 136.75, 35.42, 137.80)},
    "kyushu_north":  {"name": "北九州(福岡・小倉)",   "bbox": (33.30, 130.15, 33.95, 131.05)},
    "kyushu_south":  {"name": "南九州(熊本・鹿兒島)", "bbox": (31.50, 130.40, 32.90, 131.70)},
    "hokkaido":      {"name": "北海道(札幌・函館)",   "bbox": (41.70, 140.65, 43.85, 142.50)},
    "chugoku":       {"name": "中國・四國(廣島岡山)", "bbox": (33.80, 132.30, 34.75, 134.10)},
    "tohoku":        {"name": "東北(仙台・青森)",     "bbox": (38.15, 140.70, 40.90, 141.20)},
}

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter"
]

REQUEST_HEADERS = {
    "User-Agent": "JapanHotelFinderPWA/1.5 (https://github.com/artytien/japan-hotel-finder)",
    "Accept": "application/json",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
}

BRAND_PATTERNS = [
    ("Via Inn", r"ヴィアイン|via\s*inn"),
    ("Dormy Inn", r"ドーミーイン|dormy\s*inn|野乃|nono"),
    ("Toyoko Inn", r"東横イン|東橫イン|東横inn|toyoko\s*inn"),
    ("Super Hotel", r"スーパーホテル|super\s*hotel"),
    ("Route Inn", r"ルートイン|route\s*inn"),
    ("Comfort Hotel", r"コンフォートホテル|コンフォートイン|comfort\s*(hotel|inn)"),
    ("APA Hotel", r"アパホテル|apa\s*hotel"),
    ("LiveMax", r"ホテルリブマックス|リブマックス|livemax"),
    ("Fresa Inn", r"相鉄フレッサイン|fresa\s*inn"),
    ("Washington Hotel", r"ワシントンホテル|ワシントンR&B|washington\s*hotel"),
    ("Richmond Hotel", r"リッチモンドホテル|richmond\s*hotel"),
    ("Daiwa Roynet", r"ダイワロイネット|daiwa\s*roynet"),
    ("Mitsui Garden", r"三井ガーデンホテル|mitsui\s*garden"),
    ("Tokyu Stay", r"東急ステイ|tokyu\s*stay"),
    ("Hotel Metropolitan", r"ホテルメトロポリタン|metropolitan"),
]

SERVER_HOTEL_REGEX = "ヴィアイン|via|ドーミーイン|dormy|野乃|東横|東橫|toyoko|スーパーホテル|super|ルートイン|route|コンフォート|comfort|アパホテル|apa|リブマックス|livemax|フレッサイン|fresa|ワシントン|washington|リッチモンド|richmond|ダイワロイネット|daiwa|三井ガーデン|mitsui|東急ステイ|tokyu|メトロポリタン|metropolitan"

SERVER_AMENITY_REGEX = "ローソン|lawson|セブン|7-eleven|seven-eleven|ファミリーマート|ファミマ|familymart|マクドナルド|mcdonald|マツモトキヨシ|ウエルシア|ダイコク|スギ薬局|ツルハ|ココカラファイン|サンドラッグ|コスモス|ドラッグ|薬局|drug|ライフ|玉出|業務スーパー|イオン|マックスバリュ|成城石井|コーヨー|kohyo|サンディ|ロピア|イズミヤ|マルエツ|まいばすけっと|オーケー|ゆめタウン|サニー"

AIRPORT_STATION_RULES = {
    "JR_HARUKA": ["関西空港", "天王寺", "新今宮", "大阪", "うめきた", "新大阪", "京都", "日根野", "和泉府中", "西九条"],
    "NANKAI": ["難波", "なんば", "新今宮", "天下茶屋", "堺", "泉佐野", "りんくうタウン", "関西空港"],
    "JR_NEX": ["成田空港", "空港第2ビル", "東京", "品川", "渋谷", "新宿", "池袋", "横浜", "武蔵小杉", "大船", "千葉"],
    "KEISEI": ["京成上野", "上野", "日暮里", "青砥", "京成高砂", "京成船橋", "京成成田", "押上", "空港第2ビル", "成田空港"],
    "KEIKYU": ["羽田空港", "品川", "京急蒲田", "川崎", "横浜", "泉岳寺", "大門", "浜松町", "新橋", "東銀座", "浅草"],
    "MONORAIL": ["浜松町", "天王洲アイル", "大井競馬場前", "流通センター", "羽田空港"]
}

GRID_SIZE = 0.02

def get_grid_cell(lat, lng):
    return int(math.floor(lat / GRID_SIZE)), int(math.floor(lng / GRID_SIZE))

def build_spatial_grid(points):
    grid = defaultdict(list)
    for pt in points:
        grid[get_grid_cell(pt["lat"], pt["lng"])].append(pt)
    return grid

def find_nearest_in_grid(lat, lng, grid, max_search_dist=9999):
    cx, cy = get_grid_cell(lat, lng)
    min_dist = max_search_dist
    nearest_item = None
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for item in grid.get((cx + dx, cy + dy), []):
                d = haversine_m(lat, lng, item["lat"], item["lng"])
                if d < min_dist:
                    min_dist = d
                    nearest_item = item
    return min_dist, nearest_item

def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return int(round(R * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1 - a))))

def get_coords(element):
    if "lat" in element and "lon" in element:
        return element["lat"], element["lon"]
    if "center" in element:
        return element["center"]["lat"], element["center"]["lon"]
    return None, None

def query_overpass(query_str, step_label):
    for attempt in range(3):
        for url in OVERPASS_URLS:
            try:
                print(f"📡 [{step_label}] 請求伺服器 ({url}) ...")
                resp = requests.post(
                    url,
                    data={"data": query_str},
                    headers=REQUEST_HEADERS,
                    timeout=90
                )
                resp.raise_for_status()
                return resp.json().get("elements", [])
            except Exception as e:
                print(f"⚠️ [{step_label}] 節點異常 ({e})，6 秒後切換...")
                time.sleep(6)
        print(f"⏳ [{step_label}] 等待 12 秒後重試...")
        time.sleep(12)
    raise RuntimeError(f"❌ [{step_label}] 無法完成查詢。")

def detect_hotel_brand(tags):
    search_text = " ".join([
        tags.get("name", ""), tags.get("name:ja", ""), tags.get("name:en", ""),
        tags.get("brand", ""), tags.get("brand:ja", ""), tags.get("brand:en", ""),
        tags.get("operator", "")
    ])
    for standard_brand, pattern in BRAND_PATTERNS:
        if re.search(pattern, search_text, re.IGNORECASE):
            return standard_brand
    return None

def classify_amenity(tags):
    shop = tags.get("shop", "")
    amenity = tags.get("amenity", "")
    text = " ".join([
        tags.get("name", ""), tags.get("name:ja", ""), tags.get("name:en", ""),
        tags.get("brand", ""), tags.get("brand:ja", ""), tags.get("brand:en", "")
    ]).lower()

    if shop == "convenience" or "ローソン" in text or "セブン" in text or "ファミリーマート" in text:
        if any(k in text for k in ["ローソン", "lawson", "natural lawson"]):
            return "lawson"
        if any(k in text for k in ["セブン", "7-eleven", "seven-eleven", "7 eleven"]):
            return "seven"
        if any(k in text for k in ["ファミリーマート", "ファミマ", "familymart", "family mart"]):
            return "familymart"

    if amenity == "fast_food" or "マクドナルド" in text or "mcdonald" in text:
        if any(k in text for k in ["マクドナルド", "マック", "mcdonald"]):
            return "mcdonalds"

    if shop in ["chemist", "pharmacy", "cosmetics"] or amenity == "pharmacy" or any(
        k in text for k in [
            "マツモトキヨシ", "ウエルシア", "ダイコク", "スギ薬局", "ツルハ", 
            "ココカラファイン", "サンドラッグ", "コスモス", "オーエスドラッグ", "ドラッグ", "薬局", "drug"
        ]
    ):
        return "drugstore"

    if shop == "supermarket" or any(
        k in text for k in [
            "ライフ", "玉出", "業務スーパー", "イオン", "マックスバリュ", 
            "成城石井", "コーヨー", "kohyo", "サンディ", "ロピア", "イズミヤ", "マルエツ", "まいばすけっと", "オーケー", "ゆめタウン", "サニー"
        ]
    ):
        return "supermarket"

    return None

def detect_airport_lines(station_name, station_tags, region_key):
    lines = set()
    operator_text = " ".join([
        station_name,
        station_tags.get("operator", ""),
        station_tags.get("network", ""),
        station_tags.get("line", "")
    ])

    allowed_codes = ["JR_HARUKA", "NANKAI"] if region_key == "kansai" else (
        ["JR_NEX", "KEISEI", "KEIKYU", "MONORAIL"] if region_key == "tokyo" else list(AIRPORT_STATION_RULES.keys())
    )

    for code in allowed_codes:
        if any(kw in station_name for kw in AIRPORT_STATION_RULES[code]):
            lines.add(code)

    if region_key == "kansai" and ("南海" in operator_text or "nankai" in operator_text.lower()):
        lines.add("NANKAI")
    if region_key == "tokyo":
        if "京成" in operator_text or "keisei" in operator_text.lower():
            lines.add("KEISEI")
        if "京急" in operator_text or "京浜急行" in operator_text or "keikyu" in operator_text.lower():
            lines.add("KEIKYU")
        if "東京モノレール" in operator_text:
            lines.add("MONORAIL")

    return sorted(list(lines))

def fetch_and_save_region(r_key):
    cfg = REGIONS_MAP[r_key]
    r_name = cfg["name"]
    s, w, n, e = cfg["bbox"]
    bbox_str = f"{s},{w},{n},{e}"

    # 使用 nw（Node + Way）取代 nwr，跳過複雜多邊形關係，查詢速度提升 5 倍以上
    query_part1 = f"""
    [out:json][timeout:60];
    (
      nw["tourism"="hotel"]["name"~"{SERVER_HOTEL_REGEX}",i]({bbox_str});
      nw["tourism"="hotel"]["brand"~"{SERVER_HOTEL_REGEX}",i]({bbox_str});
      node["railway"="station"]({bbox_str});
    );
    out center tags;
    """
    elements_part1 = query_overpass(query_part1, f"{r_name}-飯店與車站")
    print(f"✅ [{r_name}-飯店與車站] 取回 {len(elements_part1)} 筆節點")

    time.sleep(3)

    query_part2 = f"""
    [out:json][timeout:60];
    (
      nw["shop"~"convenience|supermarket|chemist"]["name"~"{SERVER_AMENITY_REGEX}",i]({bbox_str});
      nw["shop"~"convenience|supermarket|chemist"]["brand"~"{SERVER_AMENITY_REGEX}",i]({bbox_str});
      nw["amenity"~"fast_food|pharmacy"]["name"~"{SERVER_AMENITY_REGEX}",i]({bbox_str});
      nw["amenity"~"fast_food|pharmacy"]["brand"~"{SERVER_AMENITY_REGEX}",i]({bbox_str});
    );
    out center tags;
    """
    elements_part2 = query_overpass(query_part2, f"{r_name}-生活機能")
    print(f"✅ [{r_name}-生活機能] 取回 {len(elements_part2)} 筆節點，開始空間配對...")

    raw_hotels = []
    stations = []
    amenities_pool = {k: [] for k in ["lawson", "seven", "familymart", "mcdonalds", "drugstore", "supermarket"]}

    for el in elements_part1:
        tags = el.get("tags", {})
        lat, lon = get_coords(el)
        if lat is None or lon is None:
            continue

        if tags.get("railway") == "station":
            st_name = tags.get("name:ja") or tags.get("name") or "周邊車站"
            stations.append({"name": st_name, "lat": lat, "lng": lon, "tags": tags})
        elif tags.get("tourism") == "hotel":
            brand = detect_hotel_brand(tags)
            if brand:
                name = tags.get("name:ja") or tags.get("name") or f"{brand} ({r_name})"
                raw_hotels.append({
                    "name": name,
                    "brand": brand,
                    "lat": round(lat, 6),
                    "lng": round(lon, 6),
                    "tags": tags
                })

    for el in elements_part2:
        tags = el.get("tags", {})
        lat, lon = get_coords(el)
        if lat is None or lon is None:
            continue
        a_type = classify_amenity(tags)
        if a_type:
            amenities_pool[a_type].append({"lat": lat, "lng": lon})

    station_grid = build_spatial_grid(stations)
    amenity_grids = {k: build_spatial_grid(v) for k, v in amenities_pool.items()}

    seen_keys = set()
    region_results = []
    for h in raw_hotels:
        grid_key = (h["brand"], round(h["lat"], 3), round(h["lng"], 3))
        if grid_key in seen_keys:
            continue
        seen_keys.add(grid_key)

        h_lat, h_lng = h["lat"], h["lng"]
        min_st_dist, nearest_st = find_nearest_in_grid(h_lat, h_lng, station_grid)
        station_name = nearest_st["name"] if nearest_st else "周邊車站"
        airport_lines = detect_airport_lines(station_name, nearest_st["tags"], r_key) if nearest_st else []

        amenity_dists = {}
        for a_key, a_grid in amenity_grids.items():
            dist, _ = find_nearest_in_grid(h_lat, h_lng, a_grid)
            amenity_dists[a_key] = dist

        frontend_region = r_key if r_key in ["kansai", "tokyo"] else "other"

        region_results.append({
            "id": f"{r_key}_{len(region_results) + 1}",
            "name": h["name"],
            "brand": h["brand"],
            "region": frontend_region,
            "lat": h_lat,
            "lng": h_lng,
            "station_name": station_name,
            "station_dist": min_st_dist,
            "airport_lines": airport_lines,
            "amenities": amenity_dists
        })

    region_results.sort(key=lambda x: x["station_dist"])

    os.makedirs(DATA_DIR, exist_ok=True)
    out_file = os.path.join(DATA_DIR, f"hotels_{r_key}.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(region_results, f, ensure_ascii=False, indent=2)
    print(f"💾 [{r_name}] 已儲存至 {out_file} (共 {len(region_results)} 筆)")

def merge_all_regions():
    all_hotels = []
    seen_keys = set()

    for r_key in REGIONS_MAP.keys():
        filepath = os.path.join(DATA_DIR, f"hotels_{r_key}.json")
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                for h in data:
                    g_key = (h["brand"], round(h["lat"], 3), round(h["lng"], 3))
                    if g_key not in seen_keys:
                        seen_keys.add(g_key)
                        all_hotels.append(h)

    all_hotels.sort(key=lambda x: x["station_dist"])
    all_path = os.path.join(DATA_DIR, "hotels_all.json")
    with open(all_path, "w", encoding="utf-8") as f:
        json.dump(all_hotels, f, ensure_ascii=False, indent=2)
    print(f"🎉 已自動更新全國總檔 {all_path} (目前累計收錄 {len(all_hotels)} 間商務飯店)")

def main():
    target = sys.argv[1].strip().lower() if len(sys.argv) > 1 else "all"

    if target == "all":
        keys = list(REGIONS_MAP.keys())
        for idx, k in enumerate(keys):
            fetch_and_save_region(k)
            if idx < len(keys) - 1:
                time.sleep(3)
    elif target in REGIONS_MAP:
        fetch_and_save_region(target)
    else:
        raise ValueError(f"不支援的區域名稱: {target}")

    merge_all_regions()

if __name__ == "__main__":
    main()
