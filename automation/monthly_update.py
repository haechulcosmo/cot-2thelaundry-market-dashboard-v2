from __future__ import annotations

import argparse
import base64
import calendar
import gzip
import json
import math
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
SUMMARY = ROOT / "automation" / "last-update.json"
KST = timezone(timedelta(hours=9))
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/126 Safari/537.36"
)
SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": UA,
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": "https://map.naver.com/",
    }
)
DBLAND_SNAPSHOT = ROOT / "automation" / "dbland_snapshot.json.gz.b64"
_DBLAND_SNAPSHOT_CACHE: dict | None = None

BRANDS = {
    "크린토피아": ["크린토피아", "코인워시365", "코인워시"],
    "워시엔조이": ["워시엔조이", "washenjoy"],
    "워시프렌즈": ["워시프렌즈"],
    "워시팡팡": ["워시팡팡"],
    "워시테리아": ["워시테리아"],
    "워시큐": ["워시큐"],
    "워시프렌즈": ["워시프렌즈"],
    "화이트365": ["화이트365"],
    "런드리24": ["런드리24"],
    "런드리존": ["런드리존"],
    "런드리익스프레스": ["런드리익스프레스"],
    "런드리카페": ["런드리카페"],
    "호텔런드리": ["호텔런드리"],
    "탑워시": ["탑워시"],
    "이지워시": ["이지워시"],
    "크린업24": ["크린업24", "클린업24"],
    "빨래방24": ["빨래방24"],
    "빨쿡": ["빨쿡"],
    "버블맨": ["버블맨", "버블맨24"],
    "버블샤인": ["버블샤인"],
    "아쿠아워시": ["아쿠아워시"],
    "위니아24크린샵": ["위니아24크린샵", "위니아24"],
    "더런드리": ["더런드리"],
}

DATE_RE = re.compile(r"(20\d{2})[.\-/년]\s*(\d{1,2})[.\-/월]\s*(\d{1,2})")


def compact(value: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", str(value or "").lower())


def phone_suffix(value: str) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[-4:] if len(digits) >= 4 else ""


def locality(address: str) -> str:
    tokens = [
        token
        for token in str(address or "").replace("****", "").split()
        if "*" not in token
    ]
    for token in reversed(tokens):
        if token.endswith(("동", "읍", "면", "리", "가")):
            return token
    return tokens[-1] if tokens else ""


def address_tokens(address: str) -> set[str]:
    return {
        token
        for token in str(address or "").replace("****", "").split()
        if "*" not in token and len(token) >= 2
    }


def masked_fragments(name: str) -> list[str]:
    return [
        compact(part)
        for part in re.split(r"\*+", str(name or ""))
        if len(compact(part)) >= 2
    ]


def parse_date(value: str) -> datetime | None:
    match = DATE_RE.search(str(value or ""))
    if not match:
        short = re.search(r"(?<!\d)(\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})", str(value or ""))
        if not short:
            return None
        year, month, day = map(int, short.groups())
        year += 2000
    else:
        year, month, day = map(int, match.groups())
    try:
        return datetime(year, month, day)
    except ValueError:
        return None


def target_month(value: str | None) -> str:
    if value and re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", value):
        return value
    now = datetime.now(KST)
    first = now.replace(day=1)
    previous = first - timedelta(days=1)
    return previous.strftime("%Y-%m")


def month_bounds(month: str) -> tuple[datetime, datetime]:
    year, mon = map(int, month.split("-"))
    return (
        datetime(year, mon, 1),
        datetime(year, mon, calendar.monthrange(year, mon)[1], 23, 59, 59),
    )


def fetch(url: str, attempts: int = 3) -> str:
    for attempt in range(attempts):
        try:
            response = SESSION.get(url, timeout=35)
            if response.status_code == 200 and len(response.content) > 500:
                response.encoding = response.apparent_encoding or "utf-8"
                return response.text
        except requests.RequestException:
            pass
        time.sleep(1.2 * (attempt + 1))
    return ""


def parse_table_rows(html: str) -> list[list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[list[str]] = []
    for tr in soup.select("tr"):
        cells = [" ".join(cell.stripped_strings) for cell in tr.select("td")]
        if cells and parse_date(cells[0]):
            rows.append(cells)
    return rows


def dbland_page(page: int, items_per_page: int = 50) -> tuple[list[dict], int]:
    payload = {}
    try:
        response = SESSION.post(
            "https://db-land.kr/archive/proc/get_list.php",
            data={
                "type": "place",
                "sch_ca_id": "021302",
                "itemsPerPage": items_per_page,
                "currentPage": page,
            },
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Referer": "https://db-land.kr/archive/place/021302/1",
            },
            timeout=35,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        payload = {}

    if not payload.get("data"):
        try:
            response = SESSION.get(
                "https://thelaundry-market-dashboard.thelaundry-market-2026.workers.dev/api/source/dbland",
                params={"page": page},
                headers={"x-update-callback": "c7ef1d9a4b6240f69837e2ab51d2c8f4"},
                timeout=35,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            payload = {}

    if not payload.get("data") and DBLAND_SNAPSHOT.exists():
        global _DBLAND_SNAPSHOT_CACHE
        if _DBLAND_SNAPSHOT_CACHE is None:
            compressed = base64.b64decode(DBLAND_SNAPSHOT.read_text(encoding="ascii"))
            _DBLAND_SNAPSHOT_CACHE = json.loads(gzip.decompress(compressed).decode("utf-8"))
        snapshot_rows = _DBLAND_SNAPSHOT_CACHE.get("rows", [])
        start = (page - 1) * items_per_page
        normalized = snapshot_rows[start : start + items_per_page]
        rows = [
            {
                "source": "DB랜드",
                "date": datetime.fromisoformat(item["date"]),
                "name": item["name"],
                "phone": item["phone"],
                "address": item["address"],
                "page": item.get("page", page),
                "url": f"https://db-land.kr/archive/place/021302/{item.get('page', page)}",
            }
            for item in normalized
        ]
        return rows, int(_DBLAND_SNAPSHOT_CACHE.get("totalCount") or len(snapshot_rows))

    rows = []
    for item in payload.get("data", []):
        try:
            date = datetime.fromtimestamp(int(item["reg_time"]) + 86400, KST).replace(tzinfo=None)
        except (KeyError, TypeError, ValueError, OSError):
            continue
        rows.append(
            {
                "source": "DB랜드",
                "date": date,
                "name": str(item.get("company") or ""),
                "phone": str(item.get("phone") or item.get("tel") or ""),
                "address": str(item.get("address") or ""),
                "page": page,
                "url": f"https://db-land.kr/archive/place/021302/{page}",
            }
        )
    return rows, int(payload.get("totalCount") or 0)


def collect_dbland(month: str) -> list[dict]:
    start, end = month_bounds(month)
    output: list[dict] = []
    total_pages = 1
    for page in range(1, 1000):
        rows, total_count = dbland_page(page)
        if page == 1 and total_count:
            total_pages = math.ceil(total_count / 50)
        if not rows:
            break
        output.extend(row for row in rows if start <= row["date"] <= end)
        if min(row["date"] for row in rows) < start or page >= total_pages:
            break
    return output


def qdb_page(page: int) -> list[dict]:
    params = {
        "cate_1": "",
        "cate_2": "",
        "cate_3": "셀프빨래방",
        "cate_1c": "",
        "cate_2c": "",
        "cate_3c": "1065",
        "local": "",
        "corp": "",
        "latest": "",
        "type": "",
        "addr": "",
        "bname": "",
        "page": page,
    }
    try:
        response = SESSION.get(
            "https://qdb.kr/db/place_data_new.php",
            params=params,
            headers={"Referer": "https://qdb.kr/db/place.php"},
            timeout=35,
        )
        response.raise_for_status()
    except requests.RequestException:
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    output = []
    for tr in soup.select("tr"):
        cells = [" ".join(cell.stripped_strings) for cell in tr.select("td")]
        if len(cells) < 6:
            continue
        date = parse_date(cells[0])
        if not date:
            continue
        output.append(
            {
                "source": "QDB",
                "date": date,
                "name": cells[1],
                "phone": cells[2] or cells[3],
                "address": cells[5],
                "page": page,
                "url": (
                    "https://qdb.kr/db/place.php?cate_3="
                    "%EC%85%80%ED%94%84%EB%B9%A8%EB%9E%98%EB%B0%A9"
                    f"&cate_3c=1065&page={page}"
                ),
            }
        )
    return output


def collect_qdb(month: str) -> list[dict]:
    start, end = month_bounds(month)
    output: list[dict] = []
    for page in range(1, 1000):
        rows = qdb_page(page)
        if not rows:
            break
        output.extend(row for row in rows if start <= row["date"] <= end)
        if min(row["date"] for row in rows) < start:
            break
    return output


def collect_all_dbland(from_month: str) -> list[dict]:
    start, _ = month_bounds(from_month)
    output = []
    total_pages = 1
    for page in range(1, 1000):
        rows, total_count = dbland_page(page)
        if page == 1 and total_count:
            total_pages = math.ceil(total_count / 50)
        if not rows:
            break
        output.extend(row for row in rows if row["date"] >= start)
        print(f"DB랜드 {page}/{total_pages}페이지 · 누적 {len(output)}건")
        if min(row["date"] for row in rows) < start or page >= total_pages:
            break
        time.sleep(0.08)
    return output


def collect_all_qdb(from_month: str) -> list[dict]:
    start, _ = month_bounds(from_month)
    output = []
    for page in range(1, 1000):
        rows = qdb_page(page)
        if not rows:
            break
        output.extend(row for row in rows if row["date"] >= start)
        print(f"QDB {page}페이지 · 누적 {len(output)}건")
        if min(row["date"] for row in rows) < start:
            break
        time.sleep(0.08)
    return output


def source_match(left: dict, right: dict) -> int:
    score = 0
    ls, rs = phone_suffix(left["phone"]), phone_suffix(right["phone"])
    if ls and rs and ls == rs:
        score += 9
    common = address_tokens(left["address"]) & address_tokens(right["address"])
    score += min(4, len(common) * 2)
    lf = masked_fragments(left["name"])
    rn = compact(right["name"])
    if any(fragment in rn for fragment in lf):
        score += 4
    if abs((left["date"] - right["date"]).days) <= 14:
        score += 2
    return score


def merge_sources(db_rows: list[dict], qdb_rows: list[dict]) -> list[dict]:
    used: set[int] = set()
    merged: list[dict] = []
    for db in db_rows:
        ranked = sorted(
            (
                (source_match(db, qdb), index, qdb)
                for index, qdb in enumerate(qdb_rows)
                if index not in used
            ),
            reverse=True,
            key=lambda row: row[0],
        )
        score, index, qdb = ranked[0] if ranked else (0, -1, None)
        if score >= 8:
            used.add(index)
        else:
            qdb = None
        merged.append({"db": db, "qdb": qdb})
    for index, qdb in enumerate(qdb_rows):
        if index not in used:
            merged.append({"db": None, "qdb": qdb})
    return merged


def apollo_state(html: str) -> dict:
    marker = "__APOLLO_STATE__"
    pos = html.find(marker)
    if pos < 0:
        return {}
    eq = html.find("=", pos)
    start = html.find("{", eq)
    if start < 0:
        return {}
    try:
        value, _ = json.JSONDecoder().raw_decode(html[start:])
        return value
    except json.JSONDecodeError:
        return {}


def place_items(state: dict) -> list[dict]:
    items = []
    for key, value in state.items():
        if key.startswith("PlaceListBusinessesItem:") and isinstance(value, dict):
            items.append(dict(value))
    return items


def classify_brand(name: str) -> tuple[str, str]:
    normalized = compact(name)
    for brand, aliases in BRANDS.items():
        for alias in aliases:
            if compact(alias) in normalized:
                return brand, f"네이버 상호에 {alias} 확인"
    return "개인", "브랜드 목록과 일치하는 상호 단서 없음"


def naver_query(row: dict) -> str:
    digits = re.sub(r"\D", "", row["phone"])
    suffix = phone_suffix(row["phone"])
    area = locality(row["address"])
    if digits.startswith("0507") and suffix:
        parts = [suffix, "셀프빨래방", area]
    elif digits.startswith(("010", "070")):
        parts = [area, "셀프빨래방"]
    else:
        parts = [area, "셀프빨래방", suffix]
    return " ".join(part for part in parts if part)


def candidate_score(row: dict, item: dict) -> tuple[int, list[str]]:
    score = 0
    reasons = []
    address = str(item.get("fullAddress") or item.get("commonAddress") or "")
    name = compact(item.get("name", ""))
    area = locality(row["address"])
    if area and area in address:
        score += 5
        reasons.append(f"지역:{area}")
    suffix = phone_suffix(row["phone"])
    item_phone = str(item.get("phone") or item.get("virtualPhone") or "")
    if suffix and phone_suffix(item_phone) == suffix:
        score += 9
        reasons.append(f"전화:{suffix}")
    fragments = masked_fragments(row["name"])
    matched = [fragment for fragment in fragments if fragment in name]
    if matched:
        best = max(matched, key=len)
        score += 3 + min(4, len(best))
        reasons.append(f"상호:{best}")
    return score, reasons


def naver_match(row: dict) -> dict:
    query = naver_query(row)
    html = fetch(
        "https://pcmap.place.naver.com/place/list?query=" + quote(query),
        attempts=4,
    )
    items = place_items(apollo_state(html))
    ranked = sorted(
        ((candidate_score(row, item), item) for item in items),
        key=lambda value: value[0][0],
        reverse=True,
    )
    if not ranked:
        return {"query": query, "confidence": "없음"}
    (score, reasons), item = ranked[0]
    second = ranked[1][0][0] if len(ranked) > 1 else -1
    confidence = "높음" if score >= 8 and score - second >= 2 else "중간" if score >= 6 else "낮음"
    if confidence == "낮음":
        return {"query": query, "confidence": confidence}
    return {
        "query": query,
        "confidence": confidence,
        "score": score,
        "reasons": reasons,
        "id": str(item.get("id") or ""),
        "name": str(item.get("name") or ""),
        "phone": str(item.get("phone") or item.get("virtualPhone") or ""),
        "address": str(item.get("fullAddress") or item.get("commonAddress") or ""),
        "new_opening": item.get("newOpening") is True,
    }


def load_app_data() -> tuple[str, dict]:
    html = INDEX.read_text(encoding="utf-8")
    marker = "const APP_DATA = "
    start = html.find(marker)
    if start < 0:
        raise RuntimeError("index.html에서 APP_DATA를 찾지 못했습니다.")
    json_start = start + len(marker)
    data, _ = json.JSONDecoder().raw_decode(html[json_start:])
    return html, data


def is_existing_record(candidate: dict, records: list[dict]) -> bool:
    suffix = phone_suffix(candidate["phone"])
    area = locality(candidate["address"])
    fragments = masked_fragments(candidate["name"])
    for record in records:
        if suffix and suffix == phone_suffix(record.get("phone", "")):
            return True
        if area and area == locality(record.get("address", "")):
            name = compact(record.get("name", ""))
            if any(fragment in name for fragment in fragments):
                return True
    return False


def build_record(item: dict, row_id: int, month: str, existing: list[dict]) -> dict:
    db, qdb = item["db"], item["qdb"]
    base = qdb or db
    name = base["name"]
    phone = base["phone"] or (db["phone"] if db else "")
    address = base["address"] or (db["address"] if db else "")
    basis = db["date"] if db else qdb["date"]
    source = "DB랜드+QDB" if db and qdb else "DB랜드만" if db else "QDB만"
    candidate = {"name": name, "phone": phone, "address": address}
    prior = is_existing_record(candidate, existing)
    matched = naver_match(candidate)
    if matched.get("confidence") in {"높음", "중간"}:
        final_name = matched["name"] or name
        brand, brand_basis = classify_brand(final_name)
        identity = "확인"
        brand_status = "네이버 확인"
        if prior:
            judgment = "기존·양도추정"
            reason = "과거 집계에 전화번호 뒷자리 또는 지역·상호가 일치하는 매장 존재"
        elif matched.get("new_opening"):
            judgment = "신규확정"
            reason = "네이버 신규오픈 표시 확인"
        else:
            judgment = "사용자검토"
            reason = "네이버 매장 매칭 완료. 신규·양도 여부는 최신·직전 거리뷰 최종 확인 필요"
    else:
        final_name = name
        brand, brand_basis = classify_brand(name)
        identity = "미확인"
        brand_status = "상호단서 추정" if brand != "개인" else "개인/미확인"
        judgment = "기존·양도추정" if prior else "사용자검토"
        reason = (
            "과거 집계와 동일 후보"
            if prior
            else "네이버 매장 단일 매칭 불가. 사용자 최종 확인 필요"
        )
    place_id = matched.get("id", "")
    naver_url = (
        f"https://map.naver.com/p/entry/place/{place_id}"
        if place_id
        else "https://map.naver.com/p/search/" + quote(matched.get("query") or naver_query(candidate))
    )
    return {
        "id": row_id,
        "month": month,
        "date": basis.isoformat(),
        "brand": brand,
        "brandStatus": brand_status,
        "judgment": judgment,
        "identity": identity,
        "name": final_name,
        "phone": phone,
        "address": address,
        "dbName": db["name"] if db else "",
        "qdbName": qdb["name"] if qdb else "",
        "dbDate": db["date"].isoformat() if db else None,
        "qdbDate": qdb["date"].isoformat() if qdb else None,
        "source": source,
        "reason": reason,
        "identityBasis": " / ".join(matched.get("reasons", [])) or brand_basis,
        "placeId": place_id,
        "naverUrl": naver_url,
        "dbUrl": db["url"] if db else "",
        "qdbUrl": qdb["url"] if qdb else "",
        "reviewRequired": judgment == "사용자검토",
        "matchConfidence": matched.get("confidence", ""),
        "roadviewUrl": "",
        "roadviewLatestDate": "",
        "roadviewPreviousDate": "",
        "roadviewPairData": "",
    }


def build_history_record(item: dict, row_id: int, month: str) -> dict:
    db, qdb = item["db"], item["qdb"]
    base = qdb or db
    name = base["name"]
    phone = base["phone"] or (db["phone"] if db else "")
    address = base["address"] or (db["address"] if db else "")
    basis = db["date"] if db else qdb["date"]
    source = "DB랜드+QDB" if db and qdb else "DB랜드만" if db else "QDB만"
    brand, brand_basis = classify_brand(name)
    return {
        "id": row_id,
        "month": month,
        "date": basis.isoformat(),
        "brand": brand,
        "brandStatus": "상호단서 추정" if brand != "개인" else "개인/미확인",
        "judgment": "신규후보",
        "identity": "미확인",
        "name": name,
        "phone": phone,
        "address": address,
        "dbName": db["name"] if db else "",
        "qdbName": qdb["name"] if qdb else "",
        "dbDate": db["date"].isoformat() if db else None,
        "qdbDate": qdb["date"].isoformat() if qdb else None,
        "source": source,
        "reason": "DB랜드·QDB 과거 등록자료 자동 백필. 실제 신규개설 여부는 미확정",
        "identityBasis": brand_basis,
        "placeId": "",
        "naverUrl": "https://map.naver.com/p/search/" + quote(naver_query({
            "name": name,
            "phone": phone,
            "address": address,
        })),
        "dbUrl": db["url"] if db else "",
        "qdbUrl": qdb["url"] if qdb else "",
        "reviewRequired": False,
        "matchConfidence": "",
        "roadviewUrl": "",
        "roadviewLatestDate": "",
        "roadviewPreviousDate": "",
        "roadviewPairData": "",
        "historicalBackfill": True,
    }


def replace_app_data(html: str, data: dict) -> None:
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    marker = "const APP_DATA = "
    start = html.find(marker)
    if start < 0:
        raise RuntimeError("APP_DATA 교체에 실패했습니다.")
    json_start = start + len(marker)
    _, offset = json.JSONDecoder().raw_decode(html[json_start:])
    updated = html[:json_start] + encoded + html[json_start + offset :]
    INDEX.write_text(updated, encoding="utf-8")


def backfill_history(from_month: str) -> int:
    html, data = load_app_data()
    existing_records = data["records"]
    db_rows = collect_all_dbland(from_month)
    qdb_rows = collect_all_qdb(from_month)

    db_by_month: dict[str, list[dict]] = defaultdict(list)
    qdb_by_month: dict[str, list[dict]] = defaultdict(list)
    for row in db_rows:
        db_by_month[row["date"].strftime("%Y-%m")].append(row)
    for row in qdb_rows:
        qdb_by_month[row["date"].strftime("%Y-%m")].append(row)

    existing_keys = {
        (
            record.get("month", ""),
            phone_suffix(record.get("phone", "")),
            locality(record.get("address", "")),
            compact(record.get("dbName") or record.get("qdbName") or record.get("name", "")),
        )
        for record in existing_records
    }
    next_id = max((int(record["id"]) for record in existing_records), default=0) + 1
    added = []

    months = sorted(set(db_by_month) | set(qdb_by_month))
    for month in months:
        merged = merge_sources(db_by_month[month], qdb_by_month[month])
        month_added = []
        for item in merged:
            base = item["qdb"] or item["db"]
            key = (
                month,
                phone_suffix(base["phone"]),
                locality(base["address"]),
                compact(base["name"]),
            )
            if key in existing_keys:
                continue
            record = build_history_record(item, next_id, month)
            added.append(record)
            month_added.append(record)
            existing_keys.add(key)
            next_id += 1

        if month_added and month not in data.get("monthlyHistory", {}):
            data.setdefault("monthlyHistory", {})[month] = dict(
                Counter(record["brand"] for record in month_added)
            )
        print(f"{month}: {len(month_added)}건 추가")

    existing_records.extend(added)
    existing_records.sort(key=lambda record: record.get("date", ""), reverse=True)
    now_kst = datetime.now(KST)
    data["updatedAt"] = now_kst.strftime("%Y-%m-%d")
    data["sourceBackfillFrom"] = from_month
    data["sourceBackfillAt"] = now_kst.isoformat()
    data["sourceBackfillCounts"] = {
        "dbLand": len(db_rows),
        "qdb": len(qdb_rows),
        "added": len(added),
    }
    data["missingHistoryMonths"] = [
        month for month in data.get("missingHistoryMonths", []) if month < from_month
    ]
    replace_app_data(html, data)

    summary = {
        "mode": "backfill",
        "fromMonth": from_month,
        "updatedAt": data["updatedAt"],
        "dbLand": len(db_rows),
        "qdb": len(qdb_rows),
        "added": len(added),
        "months": months,
    }
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", default="")
    parser.add_argument("--backfill", action="store_true")
    parser.add_argument("--from-month", default="2023-10")
    args = parser.parse_args()
    if args.backfill:
        return backfill_history(args.from_month)
    month = target_month(args.month)
    html, data = load_app_data()
    existing_records = data["records"]

    db_rows = collect_dbland(month)
    qdb_rows = collect_qdb(month)
    merged = merge_sources(db_rows, qdb_rows)
    current_month_ids = {
        (
            phone_suffix(record.get("phone", "")),
            locality(record.get("address", "")),
            compact(record.get("dbName") or record.get("qdbName") or record.get("name", "")),
        )
        for record in existing_records
        if record.get("month") == month
    }

    next_id = max((int(record["id"]) for record in existing_records), default=0) + 1
    added = []
    for item in merged:
        base = item["qdb"] or item["db"]
        key = (
            phone_suffix(base["phone"]),
            locality(base["address"]),
            compact(base["name"]),
        )
        if key in current_month_ids:
            continue
        record = build_record(item, next_id, month, existing_records + added)
        added.append(record)
        current_month_ids.add(key)
        next_id += 1
        time.sleep(0.25)

    data["records"].extend(added)
    now_kst = datetime.now(KST)
    data["updatedAt"] = now_kst.strftime("%Y-%m-%d")
    current_month = now_kst.strftime("%Y-%m")
    if month < current_month:
        data["completedThrough"] = max(data.get("completedThrough", month), month)
    else:
        data["inProgressThrough"] = now_kst.strftime("%Y-%m-%d")
    included = {"신규확정", "신규유력", "신규후보"}
    data.setdefault("monthlyHistory", {})[month] = dict(
        Counter(
            record["brand"]
            for record in data["records"]
            if record.get("month") == month and record.get("judgment") in included
        )
    )
    replace_app_data(html, data)

    summary = {
        "month": month,
        "updatedAt": data["updatedAt"],
        "partial": month >= current_month,
        "dbLand": len(db_rows),
        "qdb": len(qdb_rows),
        "mergedCandidates": len(merged),
        "added": len(added),
        "judgments": dict(Counter(record["judgment"] for record in added)),
        "brands": dict(Counter(record["brand"] for record in added)),
    }
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
