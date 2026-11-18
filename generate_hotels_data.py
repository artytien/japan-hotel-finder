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

def build_
