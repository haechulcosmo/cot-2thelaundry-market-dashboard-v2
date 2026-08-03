from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from automation.monthly_update import (
    compact,
    load_app_data,
    phone_suffix,
    replace_app_data,
)


SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": "https://map.naver.com/",
    }
)

REVIEW = "사용자검토필요"
NEW = "신규오픈"
EXISTING = "기존/양도매장"

BRAND_RULES: list[tuple[str, list[str]]] = [
    ("호텔런드리", ["호텔런드리"]),
    ("크린토피아코인워시", ["크린토피아 코인워시365", "크린토피아 코인워시", "크린토피아코인워시"]),
    ("런드리익스프레스", ["런드리익스프레스샵", "런드리익스프레스"]),
    ("런드리스테이션", ["런드리스테이션"]),
    ("런드리타운", ["런드리타운"]),
    ("런드리24", ["런드리24"]),
    ("런드리업", ["런드리업"]),
    ("런드리존", ["런드리존"]),
    ("더런드리", ["더런드리", "국민빨래방"]),
    ("워시엔조이", ["워시엔조이", "washenjoy"]),
    ("워시프렌즈", ["워시프렌즈"]),
    ("워시팡팡", ["워시팡팡"]),
    ("워시큐", ["ampm워시큐", "워시큐"]),
    ("워시쿱", ["워시쿱"]),
    ("워시허브", ["워시허브"]),
    ("워시테리아", ["워시테리아"]),
    ("워시피플", ["워시피플"]),
    ("에코런드렛", ["에코런드렛"]),
    ("어반런드렛", ["어반런드렛"]),
    ("이지워시", ["이지워시"]),
    ("크린업24", ["크린업24"]),
    ("큐브워시", ["큐브워시"]),
    ("버블맨24", ["버블맨24", "버블맨"]),
    ("버블라인", ["버블라인"]),
    ("빨쿡", ["빨쿡"]),
    ("빨래소년", ["빨래소년"]),
    ("모두의표백왕", ["모두의표백왕"]),
    ("맘스핸즈", ["맘스핸즈"]),
    ("셀피아", ["셀피아"]),
    ("화이트365", ["화이트365"]),
    ("아쿠아워시", ["아쿠아워시"]),
    ("세탁풍경", ["세탁풍경"]),
    ("세탁연구소", ["세탁연구소"]),
    ("크린토피아", ["크린토피아"]),
    ("88워시", ["88워시"]),
    ("위니아24크린샵", ["위니아24크린샵"]),
    ("위니아", ["위니아"]),
    ("서울런드리", ["서울런드리"]),
    ("코인워시24", ["코인워시24"]),
]


def normalize_brand(text: str) -> str:
    token = compact(text)
    for brand, aliases in BRAND_RULES:
        for alias in aliases:
            if compact(alias) in token:
                return brand
    return "개인"


def fetch(url: str) -> str:
    for _ in range(3):
        try:
            response = SESSION.get(url, timeout=25)
            if response.status_code == 200 and len(response.text) > 1000:
                response.encoding = "utf-8"
                return response.text
        except requests.RequestException:
            pass
        time.sleep(0.35)
    return ""


def parse_results(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict] = []
    for li in soup.select("li.VLTHu")[:12]:
        name = li.select_one("span.YwYLL")
        addr = li.select_one("span.suKMR")
        cat = li.select_one("span.YzBgS")
        if not name:
            continue
        out.append(
            {
                "name": name.get_text(" ", strip=True),
                "address": addr.get_text(" ", strip=True) if addr else "",
                "category": cat.get_text(" ", strip=True) if cat else "",
            }
        )
    return out


def masked_fragments(text: str) -> list[str]:
    return [compact(part) for part in re.split(r"\*+", str(text or "")) if len(compact(part)) >= 2]


def address_tokens(address: str) -> list[str]:
    return [token for token in str(address or "").split() if "*" not in token]


def locality_tokens(address: str) -> list[str]:
    tokens = address_tokens(address)
    filtered = [token for token in tokens if token.endswith(("시", "구", "군", "동", "읍", "면", "리", "가", "로", "길"))]
    return filtered or tokens[:3]


def query_variants(record: dict) -> list[str]:
    tokens = address_tokens(record.get("address", ""))
    locality = locality_tokens(record.get("address", ""))
    broad_locality = tokens[:4]
    fragments: list[str] = []
    for key in ("dbName", "qdbName", "name"):
        for fragment in masked_fragments(str(record.get(key) or "")):
            if fragment not in fragments:
                fragments.append(fragment)

    out: list[str] = []
    if tokens:
        out.append(" ".join(tokens[:3]) + " 셀프빨래방")
    if broad_locality:
        out.append(" ".join(broad_locality) + " 셀프빨래방")
    if locality:
        out.append(" ".join(locality[:3]) + " 셀프빨래방")
    if locality and fragments:
        out.append(" ".join(locality[:2]) + " 셀프빨래방 " + fragments[0])
    if broad_locality and fragments:
        out.append(" ".join(broad_locality[:3]) + " 셀프빨래방 " + fragments[0])
    if fragments:
        out.append(fragments[0] + " 셀프빨래방")

    digits = re.sub(r"\D", "", str(record.get("phone") or ""))
    suffix = phone_suffix(record.get("phone"))
    if digits.startswith("0507") and suffix:
        out.append(f"{suffix} 셀프빨래방")
    elif digits.startswith(("010", "070")) and broad_locality:
        out.append(" ".join(broad_locality[:3]) + " 셀프빨래방")
    elif locality:
        out.append(" ".join(locality[:2]) + " 셀프빨래방")

    brand = normalize_brand(" ".join(str(record.get(key) or "") for key in ("dbName", "qdbName", "name")))
    if brand != "개인" and locality:
        out.append(" ".join(locality[:2]) + " 셀프빨래방 " + brand)
    if brand != "개인" and broad_locality:
        out.append(" ".join(broad_locality[:3]) + " 셀프빨래방 " + brand)

    deduped: list[str] = []
    seen: set[str] = set()
    for query in out:
        query = " ".join(query.split())
        if query and query not in seen:
            seen.add(query)
            deduped.append(query)
    return deduped[:5]


def score_candidate(record: dict, candidate: dict) -> tuple[int, list[str], str]:
    score = 0
    reasons: list[str] = []
    candidate_name = str(candidate["name"])
    candidate_addr = str(candidate["address"])
    candidate_category = str(candidate.get("category") or "")
    candidate_brand = normalize_brand(candidate_name)
    record_brand = normalize_brand(" ".join(str(record.get(key) or "") for key in ("dbName", "qdbName", "name")))

    if not any(token in candidate_category for token in ("셀프빨래방", "빨래방", "세탁")):
        return -999, ["non-laundry"], candidate_brand

    for token in locality_tokens(record.get("address", ""))[:4]:
        if token and token in candidate_addr:
            score += 3
            reasons.append(f"addr:{token}")

    for fragment in masked_fragments(str(record.get("dbName") or record.get("qdbName") or record.get("name") or "")):
        if fragment and fragment in compact(candidate_name):
            score += min(7, len(fragment))
            reasons.append(f"name:{fragment}")

    if record_brand != "개인" and candidate_brand == record_brand:
        score += 6
        reasons.append(f"brand:{record_brand}")

    if "셀프빨래방" in candidate_category:
        score += 1

    if compact(candidate_name) in {"셀프빨래방", "24시셀프빨래방", "코인빨래방"}:
        score -= 3

    return score, reasons, candidate_brand


def earlier_same_store(record: dict, records: list[dict]) -> dict | None:
    record_date = str(record.get("date") or "")
    record_name = compact(record.get("name"))
    record_phone = phone_suffix(record.get("phone"))
    record_addr = compact(record.get("address"))
    for candidate in records:
        if str(candidate.get("date") or "") >= record_date:
            continue
        if candidate.get("judgment") == REVIEW:
            continue
        if record_phone and record_phone == phone_suffix(candidate.get("phone")) and record_addr and record_addr == compact(candidate.get("address")):
            return candidate
        if record_name and record_name == compact(candidate.get("name")) and record_addr and record_addr == compact(candidate.get("address")):
            return candidate
    return None


def process_month(month: str) -> int:
    html, data = load_app_data()
    records = data["records"]
    changed = 0
    targets = [record for record in records if record.get("month") == month and record.get("judgment") == REVIEW]
    for record in targets:
        best = None
        best_meta = None
        for query in query_variants(record):
            html_result = fetch("https://pcmap.place.naver.com/place/list?query=" + quote(query))
            if not html_result:
                continue
            for candidate in parse_results(html_result):
                meta = score_candidate(record, candidate)
                if best_meta is None or meta[0] > best_meta[0]:
                    best = candidate
                    best_meta = (*meta, query)
            time.sleep(0.12)

        if not best or not best_meta or best_meta[0] < 8:
            continue

        score, reasons, candidate_brand, query = best_meta
        record["name"] = best["name"]
        record["brand"] = candidate_brand
        record["brandStatus"] = "네이버 확인" if score >= 10 else "네이버 후보"
        record["identity"] = "확인" if score >= 10 else "미확인"
        record["identityBasis"] = " / ".join(reasons) if reasons else "네이버 검색 확인"
        record["naverUrl"] = "https://map.naver.com/p/search/" + quote(query + " " + best["name"])
        record["evidenceType"] = "네이버검색확인"
        record["evidenceUrl"] = record["naverUrl"]

        prior = earlier_same_store(record, records)
        if prior and score >= 10:
            record["judgment"] = EXISTING
            record["reviewRequired"] = False
            record["reason"] = f"과거 동일 또는 동일 가능 매장이 {str(prior.get('date') or '')[:10]}에 이미 확인되어 기존/양도매장으로 분류"
            record["evidenceNote"] = f"검색상호 {best['name']} / 기준매장 {prior.get('name') or ''}"
            changed += 1
        elif score >= 11:
            record["judgment"] = NEW
            record["reviewRequired"] = False
            record["reason"] = "네이버 검색으로 상호가 확인되고 공개 단서상 과거 동일 매장 재등장 근거가 확인되지 않아 신규오픈으로 반영"
            record["evidenceNote"] = f"{query} 검색으로 {best['name']} 확인"
            changed += 1
        else:
            record["reason"] = "네이버 검색으로 상호는 확인됐으나 최종 판정은 추가 확인 필요"
            record["evidenceNote"] = f"{query} 검색으로 {best['name']} 확인"
            changed += 1

    replace_app_data(html, data)
    print(json.dumps({"month": month, "changed": changed, "judgments": dict(Counter(record.get("judgment") for record in data["records"]))}, ensure_ascii=False))
    return changed


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python automation/resolve_reviews.py YYYY-MM")
    process_month(sys.argv[1])
