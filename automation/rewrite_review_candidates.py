from __future__ import annotations

from urllib.parse import quote

from automation.monthly_update import load_app_data, replace_app_data
from automation.resolve_reviews import fetch, normalize_brand, parse_results, query_variants, score_candidate


STRONG_MATCHES: dict[int, str] = {
    2026030217: "워시팡팡 복대점",
    2024091219: "런드리24 삼성디스플레이 기흥점",
    2025030994: "런드리스테이션셀프빨래방 조정경기장점",
    2026030243: "워시프렌즈셀프빨래방 김해장유율하관동점",
    2026030224: "에코런드렛 셀프빨래방 송도국제도시점",
    2026030253: "워시팡팡 무인셀프빨래방 신월점",
    2026030294: "워시엔조이 셀프빨래방 청주봉명점",
    2026030207: "런드리24 안산시우역점",
    2026030314: "24시간 셀프빨래방 인천신현점",
    2026030266: "워시팡팡 셀프빨래방 봉명자이점",
    2026030248: "낙산24시 셀프빨래방",
    2026030230: "런드리나인 봉천동셀프빨래방",
    2026030226: "호텔런드리 24시 셀프빨래방 평택점",
    2026030279: "맘스핸즈 셀프빨래방 고암점",
    2026010630: "런드리존 덕명점",
}

MANUAL_REVIEW_HINTS: dict[int, list[str]] = {
    72: [
        "AMPM워시큐 신월그라비스점 (서울 양천구 신월동)",
        "워시테리아 서울신월점 (서울 양천구 신월동)",
        "워시팡팡 무인셀프빨래방 신월점 (서울 양천구 신월동)",
    ],
    102: [
        "세탁풍경 원신흥점 (대전 유성구 원신흥동)",
        "워시테리아 대전원신흥점 (대전 유성구 원신흥동)",
        "워시팡팡 무인셀프빨래방 대전원신흥점 (대전 유성구 원신흥동)",
    ],
    2025110672: [
        "워시팡팡 셀프빨래방 (충남 아산시 신창면)",
        "신창셀프빨래방 (충남 아산시 신창면)",
        "에코런드렛 셀프빨래방 아산신창점 (충남 아산시 신창면)",
    ],
    2025120669: [
        "24셀프빨래방 (충남 천안시 서북구 쌍용동)",
        "맘스워시24 (충남 천안시 서북구 쌍용동)",
        "빨쿡 셀프빨래방 천안나사렛점 (충남 천안시 서북구 쌍용동)",
    ],
    2026030264: [
        "워시프레쉬 셀프빨래방 검단아라역점 (인천 검단구 당하동)",
    ],
}


def source_visible_chars(record: dict) -> int:
    source = str(record.get("dbName") or record.get("qdbName") or record.get("name") or "")
    return len(source.replace("*", "").replace(" ", ""))


def top_candidates(record: dict) -> list[tuple[int, str, str, str, str, str]]:
    seen: set[tuple[str, str]] = set()
    out: list[tuple[int, str, str, str, str, str]] = []
    for query in query_variants(record):
        html = fetch("https://pcmap.place.naver.com/place/list?query=" + quote(query))
        if not html:
            continue
        for candidate in parse_results(html)[:8]:
            score, _, candidate_brand = score_candidate(record, candidate)
            if score <= -100:
                continue
            key = (candidate["name"], candidate["address"])
            if key in seen:
                continue
            seen.add(key)
            out.append(
                (
                    score,
                    candidate["name"],
                    candidate["address"],
                    candidate.get("category", ""),
                    candidate_brand,
                    query,
                )
            )
    out.sort(key=lambda item: (-item[0], item[1]))
    return out[:3]


def apply() -> None:
    html, data = load_app_data()
    records = data["records"]
    record_map = {record["id"]: record for record in records}

    for record_id, exact_name in STRONG_MATCHES.items():
        record = record_map.get(record_id)
        if not record:
            continue
        brand = normalize_brand(exact_name)
        query = f"{str(record.get('address') or '').replace('****', '').strip()} {exact_name}".strip()
        record["name"] = exact_name
        record["brand"] = brand
        record["brandStatus"] = "네이버 확인"
        record["judgment"] = "신규오픈"
        record["reviewRequired"] = False
        record["identity"] = "확인"
        record["matchConfidence"] = "높음"
        record["reason"] = "네이버 검색으로 상호가 확인되고 공개 단서상 과거 동일 매장 재등장 근거가 확인되지 않아 신규오픈으로 반영"
        record["identityBasis"] = f"상호:{exact_name}"
        record["evidenceType"] = "네이버검색확인"
        record["evidenceNote"] = f"네이버 후보 상호 확정: {exact_name}"
        record["naverUrl"] = "https://map.naver.com/p/search/" + quote(query)
        record["evidenceUrl"] = record["naverUrl"]

    for record in records:
        if not record.get("reviewRequired"):
            continue
        if "?" in str(record.get("brand")):
            record["brand"] = "개인"
        if "?" in str(record.get("brandStatus")):
            record["brandStatus"] = "개인/미확인"
        candidates = top_candidates(record)
        if not candidates and record.get("id") not in MANUAL_REVIEW_HINTS:
            continue

        if candidates:
            top = candidates[0]
            if top[0] >= 9 and source_visible_chars(record) >= 4:
                record["name"] = top[1]
                record["brand"] = top[4]
                record["brandStatus"] = "네이버 후보"
                record["identity"] = "확인" if top[0] >= 11 else "미확인"
            evidence_parts = [f"{name} ({address})" for _, name, address, _, _, _ in candidates]
            record["identityBasis"] = " / ".join(
                [f"후보{i + 1}:{candidate[1]}" for i, candidate in enumerate(candidates)]
            )
            record["naverUrl"] = "https://map.naver.com/p/search/" + quote(top[5])
            record["evidenceUrl"] = record["naverUrl"]
        else:
            evidence_parts = MANUAL_REVIEW_HINTS.get(record["id"], [])
            record["identityBasis"] = "후보 정리"

        if record["id"] in MANUAL_REVIEW_HINTS:
            evidence_parts = MANUAL_REVIEW_HINTS[record["id"]]
            if record["id"] == 2025110672:
                record["brand"] = "워시팡팡"
                record["brandStatus"] = "네이버 후보"

        record["evidenceType"] = "네이버후보정리"
        record["evidenceNote"] = "네이버 후보: " + " / ".join(evidence_parts)
        record["reason"] = "네이버 후보 상호를 정리했으며 신규·기존 판정은 추가 확인 필요"

    replace_app_data(html, data)


if __name__ == "__main__":
    apply()
