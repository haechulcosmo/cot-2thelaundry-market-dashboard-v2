from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"


def compact(value: object) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", str(value or "").lower())


def phone_suffix(value: object) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[-4:] if len(digits) >= 4 else ""


def normalized_address(value: object) -> str:
    return compact(str(value or "").replace("*", ""))


def normalize_brand(name: str) -> str:
    rules = [
        ("호텔런드리", ["호텔런드리"]),
        ("크린토피아코인워시", ["크린토피아 코인워시365", "크린토피아 코인워시", "크린토피아코인워시"]),
        ("런드리익스프레스", ["런드리익스프레스샵", "런드리익스프레스"]),
        ("런드리24", ["런드리24"]),
        ("더런드리", ["더런드리", "국민빨래방"]),
        ("워시엔조이", ["워시엔조이", "washenjoy"]),
        ("워시프렌즈", ["워시프렌즈"]),
        ("워시팡팡", ["워시팡팡"]),
        ("워시큐", ["ampm워시큐", "ampm워시q", "워시큐", "워시q"]),
        ("워시허브", ["워시허브"]),
        ("에코런드렛", ["에코런드렛"]),
        ("크린업24", ["크린업24"]),
        ("버블맨24", ["버블맨24", "버블맨"]),
        ("빨쿡", ["빨쿡"]),
        ("맘스핸즈", ["맘스핸즈"]),
        ("아쿠아워시", ["아쿠아워시"]),
        ("세탁풍경", ["세탁풍경"]),
        ("위니아24크린샵", ["위니아24크린샵"]),
        ("코인워시24", ["코인워시24"]),
    ]
    token = compact(name)
    for brand, aliases in rules:
        for alias in aliases:
            if compact(alias) in token:
                return brand
    return "개인"


def load_data() -> tuple[str, dict]:
    html = INDEX.read_text(encoding="utf-8")
    marker = "const APP_DATA = "
    start = html.find(marker)
    if start < 0:
        raise RuntimeError("APP_DATA not found")
    json_start = start + len(marker)
    data, _ = json.JSONDecoder().raw_decode(html[json_start:])
    return html, data


def replace_data(html: str, data: dict) -> None:
    marker = "const APP_DATA = "
    start = html.find(marker)
    json_start = start + len(marker)
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    _, offset = json.JSONDecoder().raw_decode(html[json_start:])
    INDEX.write_text(html[:json_start] + encoded + html[json_start + offset :], encoding="utf-8")


def has_prior_same_store(record: dict, records: list[dict]) -> bool:
    record_date = str(record.get("date") or "")
    rec_suffix = phone_suffix(record.get("phone"))
    rec_addr = normalized_address(record.get("address"))
    rec_name = compact(record.get("name"))
    rec_pid = str(record.get("placeId") or "")
    for other in records:
        if other is record:
            continue
        if str(other.get("date") or "") >= record_date:
            continue
        if str(other.get("judgment") or "") == "사용자검토필요":
            continue
        if rec_pid and str(other.get("placeId") or "") == rec_pid:
            return True
        if rec_suffix and rec_addr and phone_suffix(other.get("phone")) == rec_suffix and normalized_address(other.get("address")) == rec_addr:
            return True
        if rec_name and rec_addr and compact(other.get("name")) == rec_name and normalized_address(other.get("address")) == rec_addr:
            return True
    return False


def is_exact_confirmed_review(record: dict) -> bool:
    if record.get("judgment") != "사용자검토필요":
        return False
    name = str(record.get("name") or "")
    reason = str(record.get("reason") or "")
    evidence = str(record.get("evidenceNote") or "")
    if "*" in name:
        return False
    if "네이버 검색으로 상호는 확인됐으나" in reason:
        return True
    if "후보1:" in str(record.get("identityBasis") or ""):
        candidates = re.findall(r"후보\d+:([^/]+)", str(record.get("identityBasis") or ""))
        cleaned = [c.strip() for c in candidates if c.strip()]
        return len(cleaned) == 1 and compact(cleaned[0]) == compact(name)
    if "검색으로" in evidence and "확인" in evidence:
        return True
    return False


def main() -> None:
    html, data = load_data()
    records: list[dict] = list(data["records"])
    changed = 0
    for record in records:
        if not is_exact_confirmed_review(record):
            continue
        brand = normalize_brand(str(record.get("name") or ""))
        if brand != "개인":
            record["brand"] = brand
            record["brandStatus"] = "네이버 확인"
        if has_prior_same_store(record, records):
            record["judgment"] = "기존/양도매장"
            record["reviewRequired"] = False
            record["reason"] = "과거 동일 매장 정황이 확인되어 기존/양도매장으로 분류"
            record["evidenceType"] = "과거 동일매장 정황"
        else:
            record["judgment"] = "신규오픈"
            record["reviewRequired"] = False
            record["reason"] = "네이버 상호 확인이 완료됐고 공개 범위 내 과거 동일 매장 재등장 근거가 확인되지 않아 신규오픈으로 반영"
            record["evidenceType"] = "네이버검색확인"
        changed += 1

    data["records"] = sorted(records, key=lambda row: row.get("date", ""), reverse=True)
    replace_data(html, data)
    print(json.dumps({"changed": changed}, ensure_ascii=False))


if __name__ == "__main__":
    main()
