from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"

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
    ("워시큐", ["ampm워시큐", "워시큐", "washq"]),
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
    ("탑워시케어", ["탑워시케어"]),
]

CONFIDENCE_RANK = {"높음": 3, "중간": 2, "낮음": 1, "없음": 0, "": 0}
JUDGMENT_RANK = {"신규오픈": 3, "사용자검토필요": 2, "기존/양도매장": 1}


def compact(value: object) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", str(value or "").lower())


def phone_suffix(value: object) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[-4:] if len(digits) >= 4 else ""


def normalized_address(value: object) -> str:
    return compact(str(value or "").replace("*", ""))


def normalize_brand(text: str) -> str:
    token = compact(text)
    if not token:
        return "개인"
    for brand, aliases in BRAND_RULES:
        for alias in aliases:
            if compact(alias) in token:
                return brand
    return "개인"


def best_brand(record: dict) -> str:
    candidates = [
        str(record.get("name") or ""),
        str(record.get("qdbName") or ""),
        str(record.get("dbName") or ""),
    ]
    for text in sorted(candidates, key=lambda x: (-len(compact(x)), x.count("*"))):
        brand = normalize_brand(text)
        if brand != "개인":
            return brand
    return str(record.get("brand") or "개인")


def parse_date(value: object) -> datetime:
    raw = str(value or "")
    return datetime.fromisoformat(raw)


def choose_canonical(records: list[dict]) -> dict:
    def score(record: dict) -> tuple:
        return (
            0 if record.get("historicalBackfill") else 1,
            1 if record.get("source") == "DB랜드+QDB" else 0,
            JUDGMENT_RANK.get(str(record.get("judgment") or ""), 0),
            CONFIDENCE_RANK.get(str(record.get("matchConfidence") or ""), 0),
            -str(record.get("name") or "").count("*"),
            len(compact(record.get("name") or "")),
            len(compact(record.get("qdbName") or "")),
            len(compact(record.get("dbName") or "")),
            -(int(record.get("id") or 0)),
        )

    return max(records, key=score)


def identity_group_keys(record: dict) -> list[tuple[str, str, str]]:
    month = str(record.get("month") or "")
    name = str(record.get("name") or record.get("qdbName") or record.get("dbName") or "")
    phone = phone_suffix(record.get("phone"))
    address = normalized_address(record.get("address"))
    keys: list[tuple[str, str, str]] = []
    if month and phone and address:
        keys.append((month, "phone_addr", f"{phone}|{address}"))
    compact_name = compact(name)
    if month and compact_name and address:
        keys.append((month, "name_addr", f"{compact_name}|{address}"))
    return keys


def earlier_same_store(record: dict, prior_records: list[dict]) -> dict | None:
    record_pid = str(record.get("placeId") or "")
    record_phone = phone_suffix(record.get("phone"))
    record_addr = compact(record.get("address"))
    record_name = compact(record.get("name"))
    for prior in prior_records:
        prior_pid = str(prior.get("placeId") or "")
        if record_pid and prior_pid and record_pid == prior_pid:
            return prior
        if record_phone and record_addr:
            if (
                record_phone == phone_suffix(prior.get("phone"))
                and record_addr == compact(prior.get("address"))
            ):
                return prior
        if record_addr and record_name:
            prior_name = compact(prior.get("name"))
            if record_addr == compact(prior.get("address")) and prior_name == record_name:
                return prior
    return None


def replace_app_data(html: str, data: dict) -> None:
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    marker = "const APP_DATA = "
    start = html.find(marker)
    if start < 0:
        raise RuntimeError("APP_DATA not found")
    json_start = start + len(marker)
    _, offset = json.JSONDecoder().raw_decode(html[json_start:])
    updated = html[:json_start] + encoded + html[json_start + offset :]
    INDEX.write_text(updated, encoding="utf-8")


def monthly_history(records: list[dict]) -> dict[str, dict[str, int]]:
    counts: dict[str, Counter] = defaultdict(Counter)
    for record in records:
        if record.get("judgment") != "신규오픈":
            continue
        counts[str(record.get("month") or "")][str(record.get("brand") or "개인")] += 1
    return {month: dict(counter) for month, counter in counts.items() if month}


def main() -> None:
    html = INDEX.read_text(encoding="utf-8")
    marker = "const APP_DATA = "
    start = html.find(marker)
    if start < 0:
        raise RuntimeError("APP_DATA not found")
    data, _ = json.JSONDecoder().raw_decode(html[start + len(marker) :])
    records: list[dict] = list(data["records"])

    # 1) 같은 월 + 같은 placeId는 한 건만 남기고 정리
    by_month_pid: dict[tuple[str, str], list[dict]] = defaultdict(list)
    survivors: list[dict] = []
    passthrough: list[dict] = []
    for record in records:
        pid = str(record.get("placeId") or "")
        if pid:
            by_month_pid[(str(record.get("month") or ""), pid)].append(record)
        else:
            passthrough.append(record)

    deduped: list[dict] = []
    removed_same_month = 0
    for group in by_month_pid.values():
        if len(group) == 1:
            deduped.extend(group)
            continue
        canonical = choose_canonical(group)
        earliest = min(group, key=lambda row: row.get("date", ""))
        canonical["date"] = earliest.get("date")
        if earliest.get("dbDate") and (
            not canonical.get("dbDate") or earliest.get("dbDate") < canonical.get("dbDate")
        ):
            canonical["dbDate"] = earliest.get("dbDate")
        if earliest.get("qdbDate") and (
            not canonical.get("qdbDate") or earliest.get("qdbDate") < canonical.get("qdbDate")
        ):
            canonical["qdbDate"] = earliest.get("qdbDate")
        deduped.append(canonical)
        removed_same_month += len(group) - 1

    deduped.extend(passthrough)
    records = deduped

    # 1-1) 같은 월 + 동일 전화/주소 또는 동일 상호/주소도 한 건만 남기고 정리
    by_identity: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    passthrough = []
    seen_ids: set[int] = set()
    for record in records:
        keys = identity_group_keys(record)
        if not keys:
            passthrough.append(record)
            continue
        placed = False
        for key in keys:
            if key in by_identity:
                by_identity[key].append(record)
                placed = True
                break
        if not placed:
            by_identity[keys[0]].append(record)

    rededuped: list[dict] = []
    removed_same_month_alt = 0
    for group in by_identity.values():
        if len(group) == 1:
            record = group[0]
            record_id = int(record.get("id") or 0)
            if record_id not in seen_ids:
                rededuped.append(record)
                seen_ids.add(record_id)
            continue
        canonical = choose_canonical(group)
        earliest = min(group, key=lambda row: row.get("date", ""))
        canonical["date"] = earliest.get("date")
        if earliest.get("dbDate") and (
            not canonical.get("dbDate") or earliest.get("dbDate") < canonical.get("dbDate")
        ):
            canonical["dbDate"] = earliest.get("dbDate")
        if earliest.get("qdbDate") and (
            not canonical.get("qdbDate") or earliest.get("qdbDate") < canonical.get("qdbDate")
        ):
            canonical["qdbDate"] = earliest.get("qdbDate")
        record_id = int(canonical.get("id") or 0)
        if record_id not in seen_ids:
            rededuped.append(canonical)
            seen_ids.add(record_id)
        removed_same_month_alt += len(group) - 1

    for record in passthrough:
        record_id = int(record.get("id") or 0)
        if record_id not in seen_ids:
            rededuped.append(record)
            seen_ids.add(record_id)

    records = rededuped

    # 2) 브랜드 보정
    for record in records:
        brand = best_brand(record)
        if brand and brand != record.get("brand"):
            record["brand"] = brand
            if brand == "개인":
                record["brandStatus"] = "개인/미확인"
            else:
                record["brandStatus"] = "상호 확인"

    # 3) 동일 네이버 플레이스 / 동일 매장이 과거에 있으면 기존/양도매장 처리
    records.sort(key=lambda row: row.get("date", ""))
    prior_records: list[dict] = []
    promoted_existing = 0
    promoted_new = 0
    demoted_existing = 0
    by_pid_all: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        pid = str(record.get("placeId") or "")
        if pid:
            by_pid_all[pid].append(record)

    for pid, group in by_pid_all.items():
        if not pid:
            continue
        canonical_brand = Counter(
            best_brand(record) for record in group if best_brand(record) != "개인"
        ).most_common(1)
        canonical_name = max(
            (
                str(record.get("name") or "")
                for record in group
                if str(record.get("name") or "")
            ),
            key=lambda text: (len(compact(text)), -text.count("*")),
            default="",
        )
        for record in group:
            if canonical_brand:
                record["brand"] = canonical_brand[0][0]
                record["brandStatus"] = "상호 확인"
            if canonical_name and (
                str(record.get("name") or "").count("*") >= canonical_name.count("*")
            ):
                record["name"] = canonical_name

    records.sort(key=lambda row: row.get("date", ""))
    prior_records = []
    for record in records:
        earlier = earlier_same_store(record, prior_records)
        pid = str(record.get("placeId") or "")
        if earlier:
            if record.get("judgment") != "기존/양도매장":
                promoted_existing += 1
            record["judgment"] = "기존/양도매장"
            record["reviewRequired"] = False
            prior_date = str(earlier.get("date") or "")[:10]
            evidence_url = (
                earlier.get("naverUrl")
                or earlier.get("evidenceUrl")
                or earlier.get("dbUrl")
                or earlier.get("qdbUrl")
                or record.get("naverUrl")
            )
            record["reason"] = f"동일 네이버 플레이스/동일 매장이 {prior_date}에 이미 확인되어 기존/양도매장으로 분류"
            record["evidenceType"] = "과거 동일매장 재등장"
            record["evidenceUrl"] = evidence_url
            record["evidenceNote"] = f"최초 확인일 {prior_date} / 기준 매장 {earlier.get('name') or ''}".strip()
            prior_records.append(record)
            continue

        if record.get("judgment") == "기존/양도매장":
            note = str(record.get("evidenceNote") or "")
            if "기존 근거 부족" in note or "전화 뒷자리 일치만으로는" in str(record.get("reason") or ""):
                record["judgment"] = "사용자검토필요"
                record["reviewRequired"] = True
                record["reason"] = "기존/양도 근거가 부족해 사용자 확인이 필요"
                record["evidenceType"] = "추가확인필요"
                record["evidenceNote"] = "명확한 과거 동일매장 근거 미확인"
                demoted_existing += 1

        if record.get("judgment") == "사용자검토필요" and pid:
            record["judgment"] = "신규오픈"
            record["reviewRequired"] = False
            record["reason"] = "네이버 매장 매칭이 확인됐고 공개 범위 내 과거 동일 매장 재등장 근거가 확인되지 않아 신규오픈으로 반영"
            record["evidenceType"] = "네이버매장확인"
            if not record.get("evidenceUrl"):
                record["evidenceUrl"] = record.get("naverUrl") or record.get("dbUrl") or record.get("qdbUrl")
            record["evidenceNote"] = f"{record['reason']} / {record.get('identityBasis') or ''}".strip(" /")
            promoted_new += 1

        note = str(record.get("evidenceNote") or "")
        if record.get("judgment") == "신규오픈":
            if "기존·재등록 추정 이력 우세" in note:
                record["judgment"] = "기존/양도매장"
                record["reviewRequired"] = False
                record["reason"] = "기존 운영 또는 재등록 정황이 우세해 기존/양도매장으로 분류"
                record["evidenceType"] = "과거 동일매장 정황"
                if not record.get("evidenceUrl"):
                    record["evidenceUrl"] = record.get("naverUrl") or record.get("dbUrl") or record.get("qdbUrl")
                promoted_existing += 1
            elif record.get("evidenceType") == "과거집계대조":
                record["evidenceType"] = "네이버매장확인"
                record["evidenceNote"] = f"{record.get('reason') or ''} / {record.get('identityBasis') or ''}".strip(" /")

        reason = str(record.get("reason") or "")
        if "??" in reason:
            if record.get("judgment") == "신규오픈":
                record["reason"] = "네이버 매장 매칭이 확인됐고 공개 범위 내 과거 동일 매장 재등장 근거가 확인되지 않아 신규오픈으로 반영"
            elif record.get("judgment") == "기존/양도매장":
                record["reason"] = "기존 운영 또는 재등록 정황이 확인되어 기존/양도매장으로 분류"
            else:
                record["reason"] = "네이버 매장 또는 과거 동일매장 여부를 추가 확인해야 해 사용자검토필요로 분류"
            record["evidenceNote"] = f"{record.get('reason') or ''} / {record.get('identityBasis') or ''}".strip(" /")

        prior_records.append(record)

    records.sort(key=lambda row: row.get("date", ""), reverse=True)
    data["records"] = records
    data["monthlyHistory"] = monthly_history(records)
    data["updatedAt"] = datetime.now().strftime("%Y-%m-%d")
    data["repairSummary"] = {
        "removedSameMonthDuplicates": removed_same_month,
        "removedSameMonthIdentityDuplicates": removed_same_month_alt,
        "promotedExisting": promoted_existing,
        "promotedNew": promoted_new,
        "demotedExisting": demoted_existing,
        "judgments": dict(Counter(str(record.get("judgment") or "") for record in records)),
    }
    replace_app_data(html, data)
    print(json.dumps(data["repairSummary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
