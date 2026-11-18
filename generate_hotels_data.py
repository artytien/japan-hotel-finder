import json, math, os, re, sys, time
from collections import defaultdict
import requests

DATA_DIR = "./data"
# 改用「核心都市中心點 (緯度, 經度, 半徑公尺)」精準查詢，完全避開山區與海域，速度提升 10 倍
REGIONS_MAP = {
    "kansai":       {"name": "關西圈(京阪神)",       "centers": [(34.6937, 135.5023, 25000), (35.0116, 135.7681, 15000), (34.6901, 135.1955, 15000)]},
    "tokyo":        {"name": "關東(首都圈)",         "centers": [(35.6812, 139.7671, 25000), (35.4437, 139.6380, 15000), (35.6074, 140.1065, 15000)]},
    "tokai":        {"name": "東海(名古屋・浜松)",   "centers": [(35.1709, 136.8815, 20000), (34.7108, 137.7261, 15000), (34.9756, 138.3828, 15000)]},
    "kyushu_north": {"name": "北九州(福岡・小倉)",   "centers": [(33.5902, 130.4017, 18000), (33.8834, 130.8752, 15000)]},
    "kyushu_south": {"name": "南九州(熊本・鹿兒島)", "centers": [(32.8031, 130.7079, 15000), (31.5966, 130.5571, 15000), (31.9077, 131.4202, 12000)]},
    "hokkaido":     {"name": "北海道(札幌・函館)",   "centers": [(43.0618, 141.3545, 18000), (41.7687, 140.7288, 12000), (43.7706, 142.3650, 12000)]},
    "chugoku":      {"name": "中國・四國(廣島岡山)", "centers": [(34.3853, 132.4553, 15000), (34.6551, 133.9195, 15000), (34.3428, 134.0466, 12000)]},
    "tohoku":       {"name": "東北(仙台・青森)",     "centers": [(38.2682, 140.8694, 15000), (40.8222, 140.7474, 12000), (39.7020, 141.1545, 12000)]},
}

OVERPASS_URLS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
REQUEST_HEADERS = {
    "User-Agent": "JapanHotelFinderPWA/2.0 (https://github.com/artytien/japan-hotel-finder)",
    "Accept": "application/json",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
}

BRAND_PATTERNS = [
    ("Via Inn", r"ヴィアイン|via\s*inn"), ("Dormy Inn", r"ドーミーイン|dormy\s*inn|野乃|nono"),
    ("Toyoko Inn", r"東横イン|東橫イン|東横inn|toyoko\s*inn"), ("Super Hotel", r"スーパーホテル|super\s*hotel"),
    ("Route Inn", r"ルートイン|route\s*inn"), ("Comfort Hotel", r"コンフォートホテル|コンフォートイン|comfort\s*(hotel|inn)"),
    ("APA Hotel", r"アパホテル|apa\s*hotel"), ("LiveMax", r"ホテルリブマックス|リブマックス|livemax"),
    ("Fresa Inn", r"相鉄フレッサイン|fresa\s*inn"), ("Washington Hotel", r"ワシントンホテル|ワシントンR&B|washington\s*hotel"),
    ("Richmond Hotel", r"リッチモンドホテル|richmond\s*hotel"), ("Daiwa Roynet", r"ダイワロイネット|daiwa\s*roynet"),
    ("Mitsui Garden", r"三井ガーデンホテル|mitsui\s*garden"), ("Tokyu Stay", r"東急ステイ|tokyu\s*stay"),
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
def get_grid_cell(lat, lng): return int(math.floor(lat / GRID_SIZE)), int(math.floor(lng / GRID_SIZE))
def build_spatial_grid(points):
    grid = defaultdict(list)
    for pt in points: grid[get_grid_cell(pt["lat"], pt["lng"])].append(pt)
    return grid

def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return int(round(R * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1 - a))))

def find_nearest_in_grid(lat, lng, grid, max_dist=9999):
    cx, cy = get_grid_cell(lat, lng)
    min_d, nearest = max_dist, None
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for item in grid.get((cx + dx, cy + dy), []):
                d = haversine_m(lat, lng, item["lat"], item["lng"])
                if d < min_d: min_d, nearest = d, item
    return min_d, nearest

def get_coords(el):
    if "lat" in el and "lon" in el: return el["lat"], el["lon"]
    if "center" in el: return el["center"]["lat"], el["center"]["lon"]
    return None, None

def query_overpass(q, label):
    for attempt in range(3):
        for url in OVERPASS_URLS:
            try:
                print(f"📡 [{label}] 請求 {url} ...")
                r = requests.post(url, data={"data": q}, headers=REQUEST_HEADERS, timeout=60)
                r.raise_for_status()
                return r.json().get("elements", [])
            except Exception as e:
                print(f"⚠️ [{label}] 節點異常 ({e})，5秒後切換...")
                time.sleep(5)
        time.sleep(10)
    raise RuntimeError(f"❌ [{label}] 無法完成查詢。")

def detect_hotel_brand(tags):
    txt = " ".join([tags.get(k, "") for k in ["name", "name:ja", "name:en", "brand", "brand:ja", "brand:en", "operator"]])
    for b, pat in BRAND_PATTERNS:
        if re.search(pat, txt, re.IGNORECASE): return b
    return None

def classify_amenity(tags):
    shop, am = tags.get("shop", ""), tags.get("amenity", "")
    txt = " ".join([tags.get(k, "") for k in ["name", "name:ja", "name:en", "brand", "brand:ja", "brand:en"]]).lower()
    if shop == "convenience" or any(k in txt for k in ["ローソン", "セブン", "ファミリーマート"]):
        if any(k in txt for k in ["ローソン", "lawson"]): return "lawson"
        if any(k in txt for k in ["セブン", "7-eleven", "seven-eleven", "7 eleven"]): return "seven"
        if any(k in txt for k in ["ファミリーマート", "ファミマ", "familymart", "family mart"]): return "familymart"
    if (am == "fast_food" or "マクドナルド" in txt or "mcdonald" in txt) and any(k in txt for k in ["マクドナルド", "マック", "mcdonald"]): return "mcdonalds"
    if shop in ["chemist", "pharmacy", "cosmetics"] or am == "pharmacy" or any(k in txt for k in ["マツモトキヨシ", "ウエルシア", "ダイコク", "スギ薬局", "ツルハ", "ココカラファイン", "サンドラッグ", "コスモス", "ドラッグ", "薬局", "drug"]): return "drugstore"
    if shop == "supermarket" or any(k in txt for k in ["ライフ", "玉出", "業務スーパー", "イオン", "マックスバリュ", "成城石井", "コーヨー", "kohyo", "サンディ", "ロピア", "イズミヤ", "マルエツ", "まいばすけっと", "オーケー", "ゆめタウン", "サニー"]): return "supermarket"
    return None

def detect_airport_lines(st_name, st_tags, r_key):
    lines = set()
    op = " ".join([st_name, st_tags.get("operator", ""), st_tags.get("network", ""), st_tags.get("line", "")])
    codes = ["JR_HARUKA", "NANKAI"] if r_key == "kansai" else (["JR_NEX", "KEISEI", "KEIKYU", "MONORAIL"] if r_key == "tokyo" else list(AIRPORT_STATION_RULES.keys()))
    for c in codes:
        if any(kw in st_name for kw in AIRPORT_STATION_RULES[c]): lines.add(c)
    if r_key == "kansai" and ("南海" in op or "nankai" in op.lower()): lines.add("NANKAI")
    if r_key == "tokyo":
        if "京成" in op or "keisei" in op.lower(): lines.add("KEISEI")
        if "京急" in op or "京浜急行" in op or "keikyu" in op.lower(): lines.add("KEIKYU")
        if "東京モノレール" in op: lines.add("MONORAIL")
    return sorted(list(lines))

def fetch_and_save_region(r_key):
    cfg = REGIONS_MAP[r_key]
    r_name, centers = cfg["name"], cfg["centers"]
    
    # 組合各都市中心點的 around 半徑查詢條件
    q1_parts, q2_parts = [], []
    for lat, lng, rad in centers:
        q1_parts.append(f'nw["tourism"="hotel"]["name"~"{SERVER_HOTEL_REGEX}",i](around:{rad},{lat},{lng});')
        q1_parts.append(f'nw["tourism"="hotel"]["brand"~"{SERVER_HOTEL_REGEX}",i](around:{rad},{lat},{lng});')
        q1_parts.append(f'node["railway"="station"](around:{rad},{lat},{lng});')
        q2_parts.append(f'nw["shop"~"convenience|supermarket|chemist"]["name"~"{SERVER_AMENITY_REGEX}",i](around:{rad},{lat},{lng});')
        q2_parts.append(f'nw["shop"~"convenience|supermarket|chemist"]["brand"~"{SERVER_AMENITY_REGEX}",i](around:{rad},{lat},{lng});')
        q2_parts.append(f'nw["amenity"~"fast_food|pharmacy"]["name"~"{SERVER_AMENITY_REGEX}",i](around:{rad},{lat},{lng});')

    el1 = query_overpass(f'[out:json][timeout:45];({"".join(q1_parts)});out center tags;', f"{r_name}-飯店與車站")
    time.sleep(2)
    el2 = query_overpass(f'[out:json][timeout:45];({"".join(q2_parts)});out center tags;', f"{r_name}-生活機能")

    hotels, stations = [], []
    am_pool = {k: [] for k in ["lawson", "seven", "familymart", "mcdonalds", "drugstore", "supermarket"]}
    for el in el1:
        tags, (lat, lon) = el.get("tags", {}), get_coords(el)
        if lat is None: continue
        if tags.get("railway") == "station": stations.append({"name": tags.get("name:ja") or tags.get("name") or "周邊車站", "lat": lat, "lng": lon, "tags": tags})
        elif tags.get("tourism") == "hotel":
            b = detect_hotel_brand(tags)
            if b: hotels.append({"name": tags.get("name:ja") or tags.get("name") or f"{b} ({r_name})", "brand": b, "lat": round(lat, 6), "lng": round(lon, 6)})
    for el in el2:
        tags, (lat, lon) = el.get("tags", {}), get_coords(el)
        if lat is not None:
            at = classify_amenity(tags)
            if at: am_pool[at].append({"lat": lat, "lng": lon})

    st_grid = build_spatial_grid(stations)
    am_grids = {k: build_spatial_grid(v) for k, v in am_pool.items()}
    seen, results = set(), []
    for h in hotels:
        gk = (h["brand"], round(h["lat"], 3), round(h["lng"], 3))
        if gk in seen: continue
        seen.add(gk)
        st_d, st = find_nearest_in_grid(h["lat"], h["lng"], st_grid)
        st_name = st["name"] if st else "周邊車站"
        am_dists = {k: find_nearest_in_grid(h["lat"], h["lng"], g)[0] for k, g in am_grids.items()}
        results.append({
            "id": f"{r_key}_{len(results)+1}", "name": h["name"], "brand": h["brand"],
            "region": r_key if r_key in ["kansai", "tokyo"] else "other",
            "lat": h["lat"], "lng": h["lng"], "station_name": st_name, "station_dist": st_d,
            "airport_lines": detect_airport_lines(st_name, st["tags"], r_key) if st else [],
            "amenities": am_dists
        })
    results.sort(key=lambda x: x["station_dist"])
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, f"hotels_{r_key}.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"💾 [{r_name}] 完成！收錄 {len(results)} 筆")

def merge_all_regions():
    all_h, seen = [], set()
    for rk in REGIONS_MAP:
        fp = os.path.join(DATA_DIR, f"hotels_{rk}.json")
        if os.path.exists(fp):
            with open(fp, "r", encoding="utf-8") as f:
                for h in json.load(f):
                    gk = (h["brand"], round(h["lat"], 3), round(h["lng"], 3))
                    if gk not in seen: seen.add(gk); all_h.append(h)
    all_h.sort(key=lambda x: x["station_dist"])
    with open(os.path.join(DATA_DIR, "hotels_all.json"), "w", encoding="utf-8") as f:
        json.dump(all_h, f, ensure_ascii=False, indent=2)
    print(f"🎉 總檔更新完成，目前累計 {len(all_h)} 間飯店")

def main():
    t = sys.argv[1].strip().lower() if len(sys.argv) > 1 else "all"
    if t == "all":
        for i, k in enumerate(REGIONS_MAP):
            fetch_and_save_region(k)
            if i < len(REGIONS_MAP) - 1: time.sleep(2)
    elif t in REGIONS_MAP: fetch_and_save_region(t)
    else: raise ValueError(f"不支援區域: {t}")
    merge_all_regions()

if __name__ == "__main__": main()
