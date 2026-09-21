# -*- coding: utf-8 -*-
"""포스트팩토리용 — 공식 데이터 우선 팩트 수집 · 수치 검증 · 공식 이미지 저장 모듈.

- 지원금/제도 : 정부24(보조금24) 공공서비스 API를 최우선으로, 복지로(한국사회보장정보원) API를 교차 확인용으로 조회
- 축제/행사   : 한국관광공사 TourAPI(= 대한민국 구석구석) 조회. 이미지도 같은 API에서 받아 출처·이용조건과 함께 저장
- 글 생성 뒤   : 본문의 숫자가 공식 데이터에 실제로 있는지 기계적으로 대조 (없으면 경고)

공공데이터포털(data.go.kr)에서 아래 API를 각각 '활용신청'한 뒤 발급된 인증키 하나를 쓰면 됩니다.
  1) 행정안전부_대한민국 공공서비스(혜택) 정보   (정부24·보조금24)
  2) 한국관광공사_국문 관광정보 서비스_GW        (대한민국 구석구석)
  3) 한국사회보장정보원_중앙부처복지서비스        (복지로, 선택)

※ 아래 API 주소·오퍼레이션 이름은 공공데이터포털 상세 페이지의 '요청주소'와 다르면 맨 위 설정값만 고치면 됩니다.
   연결 확인: python official_sources.py gov24 "청년도전지원사업" <인증키>
"""
from __future__ import annotations

import difflib
import html as _html
import io
import json
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from urllib.parse import unquote, urljoin, urlparse

import requests

# ───────────────────────── 설정 ─────────────────────────
GOV24_BASE = "https://api.odcloud.kr/api/gov24/v3"
GOV24_DETAIL_PAGE = "https://www.gov.kr/portal/rcvfvrSvc/dtlEx/{sid}"
BOKJIRO_LIST_URL = "http://apis.data.go.kr/B554287/NationalWelfareInformationsV001/NationalWelfarelistV001"
BOKJIRO_DETAIL_URL = "http://apis.data.go.kr/B554287/NationalWelfareInformationsV001/NationalWelfaredetailedV001"
TOUR_BASE = "https://apis.data.go.kr/B551011"
# (서비스 경로, 오퍼레이션 접미사) — 신버전을 먼저 시도하고 실패하면 구버전으로 되돌아갑니다.
TOUR_SERVICES = (("KorService2", "2"), ("KorService1", "1"))

TIMEOUT = 12
MIN_MATCH_SCORE = 0.6           # 이 점수 미만이면 '공식 데이터에서 못 찾음'으로 처리
MAX_IMAGE_BYTES = 8_000_000
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

AREA_CODES = {
    "서울": "1", "인천": "2", "대전": "3", "대구": "4", "광주": "5", "부산": "6", "울산": "7", "세종": "8",
    "경기": "31", "강원": "32", "충북": "33", "충남": "34", "경북": "35", "경남": "36", "전북": "37", "전남": "38", "제주": "39",
}
# 검색 키워드에서 빼는 군더더기 단어 (공식 서비스명·행사명과 비교할 때 방해가 됨)
STOP_WORDS = (
    "신청방법", "신청 방법", "신청", "조회", "자격조건", "자격", "대상", "조건", "지원금액", "지급일", "방법", "후기",
    "총정리", "정리", "안내", "가이드", "일정", "정보", "주차", "입장료", "프로그램", "먹거리", "예매", "예약", "가는법",
    "마감", "추가", "총", "완벽",
)
KOGL = {
    "TYPE1": "공공누리 제1유형(출처표시)",
    "TYPE2": "공공누리 제2유형(출처표시·상업적 이용금지)",
    "TYPE3": "공공누리 제3유형(출처표시·변경금지)",
    "TYPE4": "공공누리 제4유형(출처표시·상업적 이용금지·변경금지)",
}

FACT_RULES = (
    "이 글은 아래 [공식 데이터]를 유일한 사실 근거로 씁니다. 규칙:\n"
    "1) 금액·날짜·기간·인원·대상 조건·서류·신청 방법은 공식 데이터의 표현 그대로 옮기세요. 임의로 바꾸거나 반올림하지 마세요.\n"
    "2) 공식 데이터에 없는 수치·날짜·조건·요금·주차 정보는 절대 지어내지 마세요. 필요하면 그 자리에 '[확인 필요]'라고 쓰세요.\n"
    "3) 데이터끼리 모순되거나 애매한 항목(특히 신청기한·금액)은 단정하지 말고 '[확인 필요]'로 두세요.\n"
    "4) 글 도입부에 '{as_of} 기준으로 확인한 내용이에요'처럼 기준일을 한 문장으로 밝히세요. 마감일이 이미 지났으면 지난 사실로 쓰세요.\n"
    "5) D-day, 남은 일수 같은 계산값은 쓰지 말고 날짜만 쓰세요.\n"
    "6) 공식 데이터에 이미지가 필요한 실제 현장 사진은 따로 넣을 예정이니, 이미지 프롬프트는 실제 현장 사진처럼 보이는 "
    "사실적 묘사를 피하고 일러스트·인포그래픽 스타일로 쓰세요."
)


# ───────────────────────── 데이터 구조 ─────────────────────────
@dataclass
class FactPack:
    mode: str
    query: str
    found: bool = False
    source_label: str = ""
    as_of: str = ""
    title: str = ""
    fields: dict = field(default_factory=dict)       # 라벨 → 공식 데이터 값
    facts_text: str = ""                              # 검증·프롬프트용 원문 (공식 데이터 그대로)
    prompt_block: str = ""                            # 글 생성 프롬프트에 앞세워 넣을 블록
    primary_link: str = ""
    secondary_link: str = ""
    homepage: str = ""
    candidates: list = field(default_factory=list)   # [(이름, 점수, 링크 또는 ID)]
    image_items: list = field(default_factory=list)  # 저장 후보 이미지 메타
    error: str = ""
    notes: list = field(default_factory=list)


# ───────────────────────── 공통 유틸 ─────────────────────────
def _key(k: str) -> str:
    """공공데이터포털은 Encoding 키(%2B 등 포함)와 Decoding 키 두 종류를 줍니다. requests가 다시 인코딩하므로 디코딩 형태로 통일."""
    return unquote((k or "").strip())


def _norm(s: str) -> str:
    return re.sub(r"[\s\W_]+", "", (s or "").lower())


def _core(q: str) -> str:
    s = re.sub(r"20\d\d\s*년?", " ", q or "")
    for w in sorted(STOP_WORDS, key=len, reverse=True):
        s = s.replace(w, " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s or (q or "").strip()


def _similarity(query: str, name: str) -> float:
    a, b = _norm(_core(query)), _norm(name)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 0.95 if min(len(a), len(b)) >= 4 else 0.75
    toks = [t for t in _core(query).split() if len(t) >= 2]
    overlap = (sum(1 for t in toks if _norm(t) in b) / len(toks)) if toks else 0.0
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    return max(ratio, overlap * 0.9)


def _query_variants(q: str) -> list:
    out = []
    for cand in [q.strip(), _core(q)] + [t for t in _core(q).split() if len(t) >= 3]:
        if cand and cand not in out:
            out.append(cand)
    return out


def _clip(s, n=1500) -> str:
    s = re.sub(r"[ \t]+", " ", str(s or "")).strip()
    s = re.sub(r"\n\s*\n+", "\n", s)
    return s if len(s) <= n else s[:n].rstrip() + "…"


def _strip_html(s: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"[ \t]+", " ", _html.unescape(s)).strip()


def _get_json(url: str, params: dict) -> dict:
    r = requests.get(url, params=params, headers=UA, timeout=TIMEOUT)
    if r.status_code in (401, 403):
        raise PermissionError(f"인증 실패({r.status_code}) — 인증키 또는 해당 API의 '활용신청 승인' 여부를 확인하세요.")
    r.raise_for_status()
    return r.json()


def _get_text(url: str, params: dict) -> str:
    r = requests.get(url, params=params, headers=UA, timeout=TIMEOUT)
    if r.status_code in (401, 403):
        raise PermissionError(f"인증 실패({r.status_code}) — 인증키 또는 해당 API의 '활용신청 승인' 여부를 확인하세요.")
    r.raise_for_status()
    return r.text


def _flatten(el) -> dict:
    """XML 요소의 말단 태그를 {태그: 텍스트}로 펼친다. 같은 태그가 여러 번 나오면 줄바꿈으로 합친다."""
    out = {}
    for sub in el.iter():
        if len(list(sub)) == 0 and (sub.text or "").strip():
            out[sub.tag] = (out[sub.tag] + "\n" if sub.tag in out else "") + sub.text.strip()
    return out


def _today() -> date:
    return date.today()


def _fmt_ymd(s: str) -> str:
    s = re.sub(r"\D", "", s or "")
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) >= 8 else (s or "")


# ───────────────────────── 지원금: 정부24(보조금24) ─────────────────────────
GOV24_ORDER = [
    "서비스명", "서비스목적요약", "서비스목적", "지원대상", "선정기준", "지원내용", "신청기한", "신청방법", "구비서류",
    "접수기관", "소관기관명", "소관기관유형", "전화문의", "문의처", "지원유형", "지원주기", "온라인신청사이트URL",
    "상세조회URL", "법령", "자치법규", "행정규칙", "수정일시",
]
GOV24_SKIP = {"서비스ID", "조회수", "등록일시", "부서명", "사용자구분", "서비스분야", "신청기한코드"}


def gov24_search(query: str, key: str, per_page: int = 30) -> list:
    rows = {}
    for q in _query_variants(query)[:4]:
        data = _get_json(f"{GOV24_BASE}/serviceList", {
            "serviceKey": key, "page": 1, "perPage": per_page, "returnType": "JSON", "cond[서비스명::LIKE]": q,
        })
        for r in data.get("data") or []:
            sid = str(r.get("서비스ID") or "")
            if sid:
                rows.setdefault(sid, r)
        if any(_similarity(query, r.get("서비스명", "")) >= MIN_MATCH_SCORE for r in rows.values()):
            break
    return list(rows.values())


def gov24_detail(sid: str, key: str) -> dict:
    data = _get_json(f"{GOV24_BASE}/serviceDetail", {
        "serviceKey": key, "page": 1, "perPage": 1, "returnType": "JSON", "cond[서비스ID::EQ]": sid,
    })
    rows = data.get("data") or []
    return rows[0] if rows else {}


def _gov24_fields(row: dict) -> dict:
    out = {}
    for k in GOV24_ORDER:
        v = row.get(k)
        if v not in (None, "", "null"):
            out[k] = _clip(v, 1800)
    for k, v in row.items():
        if k in out or k in GOV24_SKIP or v in (None, "", "null"):
            continue
        out[k] = _clip(v, 600)
    return out


# ───────────────────────── 지원금: 복지로(교차 확인, 선택) ─────────────────────────
BOKJIRO_LABELS = {
    "servNm": "서비스명", "servDgst": "서비스 요약", "wlfareInfoOutlCn": "서비스 개요", "tgtrDtlCn": "지원대상",
    "slctCritCn": "선정기준", "alwServCn": "지원내용", "jurMnofNm": "소관부처", "jurOrgNm": "소관기관",
    "sprtCycNm": "지원주기", "srvPvsnNm": "제공유형", "rprsCtadr": "문의처", "servDtlLink": "상세 링크",
}


def bokjiro_search(query: str, key: str) -> list:
    xml = _get_text(BOKJIRO_LIST_URL, {
        "serviceKey": key, "callTp": "L", "pageNo": 1, "numOfRows": 10, "srchKeyCode": "003", "searchWrd": _core(query),
    })
    root = ET.fromstring(xml)
    return [_flatten(el) for el in root.iter("servList")]


def bokjiro_detail(sid: str, key: str) -> dict:
    xml = _get_text(BOKJIRO_DETAIL_URL, {"serviceKey": key, "callTp": "D", "servId": sid})
    return _flatten(ET.fromstring(xml))


def _bokjiro_fields(d: dict) -> dict:
    out = {}
    for tag, label in BOKJIRO_LABELS.items():
        if d.get(tag):
            out[label] = _clip(d[tag], 1800)
    for tag, v in d.items():
        if tag in BOKJIRO_LABELS or tag in ("servId", "wantedDtl", "resultCode", "resultMessage"):
            continue
        out[tag] = _clip(v, 500)
    return out


def _fields_to_text(fields: dict) -> str:
    return "\n".join(f"- {k}: {v}" for k, v in fields.items())


def _make_prompt_block(fp: FactPack, body: str) -> str:
    rules = FACT_RULES.format(as_of=fp.as_of)
    return f"[공식 데이터 — 이 글의 유일한 사실 근거 / 조회일 {fp.as_of} / 출처: {fp.source_label}]\n{rules}\n\n{body}"


def _fact_pack_benefit(topic: str, key: str, use_bokjiro: bool = True) -> FactPack:
    fp = FactPack(mode="지원금/제도", query=topic, as_of=_today().isoformat())
    k = _key(key)
    best = None            # (score, source, id, name, list_row)
    cands = []
    try:
        for r in gov24_search(topic, k):
            sc = _similarity(topic, r.get("서비스명", ""))
            cands.append((r.get("서비스명", ""), round(sc, 2), GOV24_DETAIL_PAGE.format(sid=r.get("서비스ID", ""))))
            if best is None or sc > best[0]:
                best = (sc, "gov24", str(r.get("서비스ID", "")), r.get("서비스명", ""), r)
    except Exception as e:  # noqa: BLE001
        fp.notes.append(f"정부24 조회 실패: {e}")

    bok_best = None
    if use_bokjiro:
        try:
            for r in bokjiro_search(topic, k):
                sc = _similarity(topic, r.get("servNm", ""))
                cands.append((f"[복지로] {r.get('servNm', '')}", round(sc, 2), r.get("servDtlLink", "") or r.get("servId", "")))
                if bok_best is None or sc > bok_best[0]:
                    bok_best = (sc, "bokjiro", str(r.get("servId", "")), r.get("servNm", ""), r)
        except Exception as e:  # noqa: BLE001
            fp.notes.append(f"복지로 조회 실패(선택 사항이라 건너뜀): {e}")

    fp.candidates = sorted(cands, key=lambda c: -c[1])[:6]
    if best is None and bok_best is None:
        fp.error = "정부24·복지로에서 결과가 없습니다. " + " / ".join(fp.notes)
        return fp

    blocks, labels = [], []
    if best and best[0] >= MIN_MATCH_SCORE:
        row = gov24_detail(best[2], k) or best[4]
        fields = _gov24_fields(row)
        fp.title = fields.get("서비스명") or best[3]
        fp.fields = fields
        fp.primary_link = fields.get("온라인신청사이트URL") if str(fields.get("온라인신청사이트URL", "")).startswith("http") else ""
        fp.secondary_link = GOV24_DETAIL_PAGE.format(sid=best[2])
        fp.primary_link = fp.primary_link or fp.secondary_link
        blocks.append("■ 정부24(보조금24) 공공서비스 정보\n" + _fields_to_text(fields))
        labels.append("정부24(보조금24)")
    if bok_best and bok_best[0] >= MIN_MATCH_SCORE:
        d = bokjiro_detail(bok_best[2], k) or bok_best[4]
        bf = _bokjiro_fields(d)
        if not fp.title:
            fp.title = bf.get("서비스명") or bok_best[3]
            fp.fields = bf
            link = bf.get("상세 링크", "")
            fp.primary_link = link if link.startswith("http") else ""
            fp.secondary_link = fp.primary_link
        blocks.append("■ 복지로(한국사회보장정보원) 서비스 정보 — 교차 확인용\n" + _fields_to_text(bf))
        labels.append("복지로")

    if not blocks:
        top = max(x[0] for x in (best, bok_best) if x)
        fp.error = f"공식 데이터에서 '{topic}'와(과) 충분히 일치하는 서비스를 찾지 못했습니다(최고 유사도 {top:.2f}). 아래 후보 중 정확한 이름으로 다시 입력해 보세요."
        return fp

    fp.found = True
    fp.source_label = " + ".join(labels)
    body = "\n\n".join(blocks)
    if len(blocks) > 1:
        body += "\n\n※ 두 출처의 신청기한·금액이 다르면 단정하지 말고 [확인 필요]로 표시하세요."
    fp.facts_text = body
    fp.prompt_block = _make_prompt_block(fp, body)
    return fp


# ───────────────────────── 축제·행사: TourAPI(대한민국 구석구석) ─────────────────────────
def _tour_call(op: str, params: dict, key: str) -> list:
    """TourAPI 호출. 신버전(KorService2)→구버전(KorService1) 순으로 시도해 items 리스트를 돌려준다."""
    last = None
    for svc, suf in TOUR_SERVICES:
        url = f"{TOUR_BASE}/{svc}/{op}{suf}"
        try:
            data = _get_json(url, {**{"serviceKey": key, "MobileOS": "ETC", "MobileApp": "PostFactory", "_type": "json"}, **params})
            resp = data.get("response", {})
            code = str(resp.get("header", {}).get("resultCode", ""))
            if code not in ("0000", "00", ""):
                last = RuntimeError(f"{svc}: {resp.get('header', {}).get('resultMsg', code)}")
                continue
            items = (resp.get("body") or {}).get("items")
            if not items or items == "":
                return []
            item = items.get("item") if isinstance(items, dict) else items
            return item if isinstance(item, list) else ([item] if item else [])
        except PermissionError:
            raise
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"TourAPI 호출 실패({op}): {last}")


def _tour_status(start: str, end: str, today: date) -> str:
    try:
        s = datetime.strptime(re.sub(r"\D", "", start)[:8], "%Y%m%d").date()
        e = datetime.strptime(re.sub(r"\D", "", end)[:8], "%Y%m%d").date()
    except ValueError:
        return "확인 필요"
    if today < s:
        return "예정"
    if today > e:
        return "종료"
    return "진행중"


def _homepage_url(s: str) -> str:
    m = re.search(r'https?://[^\s"\'<>]+', s or "")
    return m.group(0).rstrip(".,)") if m else ""


def _tour_images(content_id: str, key: str, first_image: str = "") -> list:
    items = []
    seen = set()
    try:
        for it in _tour_call("detailImage", {"contentId": content_id, "imageYN": "Y", "subImageYN": "Y", "numOfRows": 12, "pageNo": 1}, key):
            url = it.get("originimgurl") or it.get("smallimageurl") or ""
            if url and url not in seen:
                seen.add(url)
                items.append({"url": url, "name": it.get("imgname", ""), "source": "한국관광공사 TourAPI",
                              "license_raw": str(it.get("cpyrhtDivCd", "") or "")})
    except Exception:  # noqa: BLE001
        pass
    if first_image and first_image not in seen:
        items.insert(0, {"url": first_image, "name": "대표 이미지", "source": "한국관광공사 TourAPI", "license_raw": ""})
    return items


def _fact_pack_festival(topic: str, key: str) -> FactPack:
    fp = FactPack(mode="축제/행사", query=topic, as_of=_today().isoformat())
    k = _key(key)
    today = _today()
    cands = []
    try:
        items = _tour_call("searchKeyword", {"keyword": _core(topic), "contentTypeId": "15", "numOfRows": 20, "pageNo": 1}, k)
        if not items:
            items = _tour_call("searchFestival", {"eventStartDate": f"{today.year}0101", "numOfRows": 200, "pageNo": 1}, k)
    except Exception as e:  # noqa: BLE001
        fp.error = f"대한민국 구석구석(TourAPI) 조회 실패: {e}"
        return fp
    best = None
    for it in items:
        sc = _similarity(topic, it.get("title", ""))
        cands.append((it.get("title", ""), round(sc, 2), it.get("contentid", "")))
        if best is None or sc > best[0]:
            best = (sc, it)
    fp.candidates = sorted(cands, key=lambda c: -c[1])[:6]
    if best is None or best[0] < MIN_MATCH_SCORE:
        fp.error = f"대한민국 구석구석에서 '{topic}'와(과) 충분히 일치하는 행사를 찾지 못했습니다. 정확한 행사명으로 다시 입력해 보세요."
        return fp

    it = best[1]
    cid = str(it.get("contentid", ""))
    common, intro = {}, {}
    try:
        cm = _tour_call("detailCommon", {"contentId": cid, "defaultYN": "Y", "overviewYN": "Y", "firstImageYN": "Y", "addrinfoYN": "Y"}, k)
        common = cm[0] if cm else {}
    except Exception as e:  # noqa: BLE001
        fp.notes.append(f"상세(공통) 조회 실패: {e}")
    try:
        ir = _tour_call("detailIntro", {"contentId": cid, "contentTypeId": "15"}, k)
        intro = ir[0] if ir else {}
    except Exception as e:  # noqa: BLE001
        fp.notes.append(f"상세(소개) 조회 실패: {e}")

    start, end = intro.get("eventstartdate") or it.get("eventstartdate", ""), intro.get("eventenddate") or it.get("eventenddate", "")
    homepage = _homepage_url(intro.get("eventhomepage", "")) or _homepage_url(common.get("homepage", ""))
    rows = [
        ("행사명", common.get("title") or it.get("title", "")),
        ("기간", f"{_fmt_ymd(start)} ~ {_fmt_ymd(end)}" if start else ""),
        ("진행 상태(조회일 기준)", _tour_status(start, end, today) if start else ""),
        ("장소", intro.get("eventplace", "")),
        ("주소", (common.get("addr1", "") + " " + common.get("addr2", "")).strip() or it.get("addr1", "")),
        ("운영시간", _strip_html(intro.get("playtime", ""))),
        ("이용요금", _strip_html(intro.get("usetimefestival", ""))),
        ("할인 정보", _strip_html(intro.get("discountinfofestival", ""))),
        ("연령 제한", _strip_html(intro.get("agelimit", ""))),
        ("주최", _strip_html(intro.get("sponsor1", ""))),
        ("주관", _strip_html(intro.get("sponsor2", ""))),
        ("문의", intro.get("sponsor1tel") or common.get("tel") or it.get("tel", "")),
        ("예매·예약", _strip_html(intro.get("bookingplace", ""))),
        ("공식 홈페이지", homepage),
        ("프로그램", _clip(_strip_html(intro.get("program", "")), 1500)),
        ("부대행사", _clip(_strip_html(intro.get("subevent", "")), 800)),
        ("개요", _clip(_strip_html(common.get("overview", "")), 1800)),
    ]
    fp.fields = {k2: v for k2, v in rows if v}
    fp.title = fp.fields.get("행사명", it.get("title", ""))
    fp.homepage = homepage
    fp.primary_link = homepage
    fp.source_label = "한국관광공사 대한민국 구석구석(TourAPI)"
    fp.found = True
    body = _fields_to_text(fp.fields)
    body += "\n\n※ 주차·교통·셔틀·개별 프로그램 시간표처럼 위 데이터에 없는 정보는 [확인 필요]로 두세요. " \
            "데이터의 먹거리 등 부가 정보가 '전년도 기준'이라고 적혀 있으면 그 사실을 함께 밝히세요."
    fp.facts_text = body
    fp.prompt_block = _make_prompt_block(fp, body)
    fp.image_items = _tour_images(cid, k, common.get("firstimage") or it.get("firstimage", ""))
    return fp


def _parse_period(topic: str, today: date):
    """'10월 경기 축제', '가을 강원 축제' 같은 주제에서 (시작일, 종료일, 지역코드, 지역명) 추출."""
    year = int(m.group(1)) if (m := re.search(r"(20\d\d)", topic)) else today.year
    seasons = {"봄": (3, 5), "여름": (6, 8), "가을": (9, 11), "겨울": (12, 2)}
    m1 = re.search(r"(\d{1,2})\s*월", topic)
    if m1:
        a = b = int(m1.group(1))
    else:
        sm = next((v for k2, v in seasons.items() if k2 in topic), None)
        a, b = sm if sm else (today.month, today.month)
    start = date(year, a, 1)
    ey = year + 1 if b < a else year
    nxt = date(ey + (1 if b == 12 else 0), 1 if b == 12 else b + 1, 1)
    end = nxt - timedelta(days=1)
    area_name = next((n for n in AREA_CODES if n in topic), "")
    return start, end, AREA_CODES.get(area_name, ""), area_name


def _fact_pack_festival_list(topic: str, key: str) -> FactPack:
    fp = FactPack(mode="축제 모음(월별·계절)", query=topic, as_of=_today().isoformat())
    k = _key(key)
    today = _today()
    start, end, area_code, area_name = _parse_period(topic, today)
    params = {"eventStartDate": (start - timedelta(days=90)).strftime("%Y%m%d"), "numOfRows": 200, "pageNo": 1}
    if area_code:
        params["areaCode"] = area_code
    try:
        items = _tour_call("searchFestival", params, k)
    except Exception as e:  # noqa: BLE001
        fp.error = f"대한민국 구석구석(TourAPI) 조회 실패: {e}"
        return fp
    picked = []
    for it in items:
        try:
            s = datetime.strptime(re.sub(r"\D", "", it.get("eventstartdate", ""))[:8], "%Y%m%d").date()
            e = datetime.strptime(re.sub(r"\D", "", it.get("eventenddate", ""))[:8], "%Y%m%d").date()
        except ValueError:
            continue
        if s <= end and e >= start and (e - s).days < 150:   # 기간 겹침 + 상설·장기 행사 제외
            picked.append((s, e, it))
    picked.sort(key=lambda x: (x[0], x[2].get("title", "")))
    picked = picked[:12]
    if not picked:
        fp.error = f"{start:%Y-%m-%d} ~ {end:%Y-%m-%d} {area_name or '전국'}에서 확인되는 행사가 없습니다."
        return fp
    lines, imgs = [], []
    for s, e, it in picked:
        lines.append(f"- {it.get('title', '')} | 기간 {s:%Y-%m-%d} ~ {e:%Y-%m-%d} | 진행 상태(조회일 기준) "
                     f"{_tour_status(s.strftime('%Y%m%d'), e.strftime('%Y%m%d'), today)} | 주소 {it.get('addr1', '')} | 문의 {it.get('tel', '')}")
        if it.get("firstimage") and len(imgs) < 6:
            imgs.append({"url": it["firstimage"], "name": it.get("title", ""), "source": "한국관광공사 TourAPI", "license_raw": ""})
    fp.found = True
    fp.title = f"{area_name or '전국'} {start.month}월 축제·행사"
    fp.source_label = "한국관광공사 대한민국 구석구석(TourAPI)"
    fp.fields = {"조회 범위": f"{start:%Y-%m-%d} ~ {end:%Y-%m-%d} / {area_name or '전국'}", "행사 수": str(len(picked))}
    body = f"조회 범위: {start:%Y-%m-%d} ~ {end:%Y-%m-%d} / {area_name or '전국'}\n" + "\n".join(lines) + \
           "\n\n※ 위 목록에 없는 행사는 쓰지 마세요. 요금·시간표는 데이터에 없으므로 [확인 필요]로 두세요."
    fp.facts_text = body
    fp.prompt_block = _make_prompt_block(fp, body)
    fp.image_items = imgs
    return fp


def build_fact_pack(mode: str, topic: str, key: str, use_bokjiro: bool = True) -> FactPack:
    """모드에 맞는 공식 데이터 조회. 실패해도 예외를 던지지 않고 FactPack.found=False + error로 돌려준다."""
    if not (key or "").strip():
        return FactPack(mode=mode, query=topic, error="공공데이터포털 인증키가 없습니다. 사이드바에 입력하거나 Secrets에 DATA_GO_KR_KEY를 등록하세요.")
    try:
        if mode == "지원금/제도":
            return _fact_pack_benefit(topic, key, use_bokjiro)
        if mode == "축제/행사":
            return _fact_pack_festival(topic, key)
        if mode == "축제 모음(월별·계절)":
            return _fact_pack_festival_list(topic, key)
    except PermissionError as e:
        return FactPack(mode=mode, query=topic, error=str(e))
    except Exception as e:  # noqa: BLE001
        return FactPack(mode=mode, query=topic, error=f"공식 데이터 조회 중 오류: {e}")
    return FactPack(mode=mode, query=topic, error="이 카테고리는 공식 데이터 조회 대상이 아닙니다.")


# ───────────────────────── 수치 검증 ─────────────────────────
_UNIT = r"(?:원|만\s*원|천\s*원|억\s*원|억|%|퍼센트|명|개월|세|일|시간|시|분|회|배|㎡|km|점|년|월)"
_NUM_RE = re.compile(rf"(\d[\d,]*(?:\.\d+)?)\s*({_UNIT})?")


def _numbers(text: str) -> set:
    out = set()
    for m in re.finditer(r"\d[\d,]*(?:\.\d+)?", text or ""):
        out.add(m.group(0).replace(",", "").lstrip("0") or "0")
    return out


def verify_numbers(content_html: str, facts_text: str, today: date | None = None) -> list:
    """생성된 글 속 '의미 있는 숫자'가 공식 데이터에 실제로 있는지 대조한다. 없는 숫자 목록 [(숫자표기, 앞뒤 문맥)] 반환."""
    today = today or _today()
    txt = re.sub(r"<style.*?</style>|<script.*?</script>", " ", content_html or "", flags=re.S | re.I)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = re.sub(r"\[이미지\d+\]|\[\[IMG\d+.*?\]\]|\[확인 필요\]", " ", txt)
    txt = _html.unescape(txt)
    allowed = _numbers(facts_text) | {str(today.year), str(today.month), str(today.day), str(today.year)[2:]}
    seen, bad = set(), []
    for m in _NUM_RE.finditer(txt):
        raw, unit = m.group(1), m.group(2)
        norm = raw.replace(",", "").lstrip("0") or "0"
        meaningful = bool(unit) or len(norm.replace(".", "")) >= 2
        if not meaningful or norm in allowed:
            continue
        if not unit and re.match(r"^(19|20)\d\d$", norm):   # 단독 연도는 통과
            continue
        # 단위 없는 한두 자리 숫자·전화번호 조각 등은 제외 (단위가 있거나 3자리 이상일 때만 검사)
        if not unit and len(norm) < 3:
            continue
        key2 = (norm, unit or "")
        if key2 in seen:
            continue
        seen.add(key2)
        ctx = txt[max(0, m.start() - 12): m.end() + 10].replace("\n", " ").strip()
        bad.append((f"{raw}{unit or ''}", ctx))
    return bad[:12]


# ───────────────────────── 이미지 저장 ─────────────────────────
def download_image(url: str, max_bytes: int = MAX_IMAGE_BYTES):
    r = requests.get(url, headers=UA, timeout=TIMEOUT, stream=True)
    r.raise_for_status()
    ctype = r.headers.get("Content-Type", "").split(";")[0].strip().lower()
    if not ctype.startswith("image/"):
        raise ValueError(f"이미지가 아닙니다({ctype or '알 수 없음'})")
    data = r.raw.read(max_bytes + 1, decode_content=True)
    if len(data) > max_bytes:
        raise ValueError("이미지가 너무 큽니다")
    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}.get(ctype) \
        or os.path.splitext(urlparse(url).path)[1] or ".jpg"
    return data, ext


def _license_info(raw: str):
    """(표시문구, 사용가능 여부, 주의문구). 상업적 이용 금지(2·4유형)는 애드센스 블로그에 쓸 수 없으므로 후보로만 둔다."""
    t = re.sub(r"[^A-Za-z0-9]", "", (raw or "")).upper()
    m = re.search(r"TYPE([1-4])", t)
    if not m:
        return ("이용조건 표기 없음 — 한국관광공사 이용안내에 따라 출처 표시 후 사용, 원본 임의 변경 금지", True,
                "이미지별 저작권 유형 값이 응답에 없었습니다. 공공누리 표시를 확인하세요.")
    code = f"TYPE{m.group(1)}"
    ok = code in ("TYPE1", "TYPE3")
    warn = ""
    if code in ("TYPE3", "TYPE4"):
        warn = "변경금지 — 자르기·편집·글자 얹기 없이 원본 그대로 사용"
    if not ok:
        warn = "상업적 이용 금지 유형 — 수익형 블로그에는 쓰지 마세요"
    return (KOGL[code], ok, warn)


def og_image_candidates(page_url: str) -> list:
    """공식 홈페이지의 og:image를 '후보'로 수집. 이용허락이 확인되기 전에는 발행에 쓰면 안 됩니다."""
    if not page_url:
        return []
    try:
        r = requests.get(page_url, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
    except requests.RequestException:
        return []
    out, seen = [], set()
    for pat in (r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
                r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)'):
        for m in re.finditer(pat, r.text, flags=re.I):
            u = urljoin(page_url, _html.unescape(m.group(1)))
            if u not in seen:
                seen.add(u)
                out.append({"url": u, "name": "공식 홈페이지 대표 이미지", "source": f"공식 홈페이지({urlparse(page_url).netloc})",
                            "license_raw": "", "candidate_only": True})
    return out[:2]


def _find_font(bold: bool = False):
    from PIL import ImageFont  # 지연 임포트: Pillow가 없어도 나머지 기능은 동작
    names = [os.environ.get("CARD_FONT_PATH", "")]
    if bold:
        names += ["/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf", "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                  "C:/Windows/Fonts/malgunbd.ttf", "/System/Library/Fonts/AppleSDGothicNeo.ttc"]
    names += ["/usr/share/fonts/truetype/nanum/NanumGothic.ttf", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
              "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", "C:/Windows/Fonts/malgun.ttf",
              "/System/Library/Fonts/AppleSDGothicNeo.ttc", "/Library/Fonts/AppleGothic.ttf"]
    for p in names:
        if p and os.path.exists(p):
            return lambda size, _p=p: ImageFont.truetype(_p, size)
    return None


def _wrap(draw, text, font, max_w, max_lines):
    """공백 단위로 줄바꿈하고, 한 단어가 한 줄보다 길 때만 글자 단위로 자른다(마지막 줄에 글자 하나만 남는 것 방지)."""
    lines, cur = [], ""
    for w in (text or "").split(" "):
        trial = f"{cur} {w}".strip() if cur else w
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
            continue
        if cur:
            lines.append(cur)
            cur = ""
        while draw.textlength(w, font=font) > max_w:
            k = len(w)
            while k > 1 and draw.textlength(w[:k], font=font) > max_w:
                k -= 1
            lines.append(w[:k])
            w = w[k:]
        cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while lines[-1] and draw.textlength(lines[-1] + "…", font=font) > max_w:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "…"
    return lines


def _short(s: str, n: int) -> str:
    s = re.sub(r"\s+", " ", re.sub(r"[○●◎ㅇ※▶■\-]+", " ", s or "")).strip()
    return s if len(s) <= n else s[:n].rstrip() + "…"


def make_info_card_png(title: str, rows: list, footer: str, size=(1200, 630)):
    """지원금 '정보 카드' 이미지를 직접 제작(저작권 문제 없음). 한글 폰트가 없으면 None."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None, "Pillow가 설치되지 않았습니다."
    loader, loader_b = _find_font(False), _find_font(True)
    if loader is None:
        return None, "한글 폰트를 찾지 못했습니다(packages.txt에 fonts-nanum 추가 또는 CARD_FONT_PATH 지정)."
    W, H = size
    img = Image.new("RGB", size, "#F4F1EA")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 22, H], fill="#2F6B4F")
    x0, x1 = 70, W - 70
    y = 52
    f_title, f_lab, f_val, f_ft = (loader_b or loader)(54), (loader_b or loader)(30), loader(34), loader(26)
    for ln in _wrap(d, title, f_title, x1 - x0, 2):
        d.text((x0, y), ln, font=f_title, fill="#1F2A24")
        y += 68
    y += 14
    d.line([x0, y, x1, y], fill="#D8D0BE", width=3)
    y += 26
    for label, value in rows:
        if not value:
            continue
        d.text((x0, y), label, font=f_lab, fill="#2F6B4F")
        vlines = _wrap(d, value, f_val, x1 - x0 - 210, 2)
        for i, ln in enumerate(vlines):
            d.text((x0 + 210, y - 2 + i * 44), ln, font=f_val, fill="#222222")
        y += max(1, len(vlines)) * 44 + 22
        if y > H - 90:
            break
    d.text((x0, H - 60), footer, font=f_ft, fill="#7A7566")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue(), ""


def post_process(fp, content_html: str, want_images=True, want_candidates=False, want_card=True, max_images=6):
    """글 생성 뒤 호출: (체크 행 리스트, assets dict). assets = images/candidates/card/unverified/notes."""
    rows, assets = [], {"images": [], "candidates": [], "card": None, "unverified": [], "notes": []}
    if fp is None or not fp.found:
        rows.append(("공식 데이터 근거", "warn", "공식 데이터 없이 생성됨 — 금액·날짜를 공식 페이지에서 직접 확인하세요"))
        return rows, assets
    rows.append(("공식 데이터 근거", "ok", f"{fp.source_label} / 조회일 {fp.as_of}"))

    unv = verify_numbers(content_html, fp.facts_text)
    assets["unverified"] = unv
    if unv:
        rows.append(("수치 검증", "warn", f"공식 데이터에 없는 숫자 {len(unv)}개: " + ", ".join(f"{a}" for a, _ in unv[:6]) + " — 발행 전 확인"))
    else:
        rows.append(("수치 검증", "ok", "본문의 금액·날짜·인원 숫자가 모두 공식 데이터에서 확인됨"))
    left = len(re.findall(r"\[확인 필요\]", content_html or ""))
    rows.append(("미확정 표기", "warn" if left else "ok",
                 f"본문에 [확인 필요] {left}곳 — 공식 페이지에서 채우거나 문장을 삭제한 뒤 발행" if left else "없음"))

    if want_images and fp.image_items:
        saved, failed = 0, 0
        for it in fp.image_items[:max_images]:
            try:
                data, ext = download_image(it["url"])
            except Exception as e:  # noqa: BLE001
                failed += 1
                assets["notes"].append(f"이미지 다운로드 실패: {it['url']} ({e})")
                continue
            lic, ok, warn = _license_info(it.get("license_raw", ""))
            rec = {**it, "bytes": data, "ext": ext, "license": lic, "warn": warn,
                   "caption": "이미지 출처: 한국관광공사", "filename": ""}
            (assets["images"] if ok else assets["candidates"]).append(rec)
            saved += ok
        for i, rec in enumerate(assets["images"], 1):
            rec["filename"] = f"official_{i:02d}{rec['ext']}"
        rows.append(("공식 이미지 저장", "ok" if assets["images"] else "warn",
                     f"{len(assets['images'])}장 저장 / 이용불가 유형 {len(assets['candidates'])}장 / 실패 {failed}장 — 출처 문구와 함께 패키지에 포함"))

    if want_candidates and fp.homepage:
        for i, it in enumerate(og_image_candidates(fp.homepage), 1):
            try:
                data, ext = download_image(it["url"])
            except Exception as e:  # noqa: BLE001
                assets["notes"].append(f"후보 이미지 다운로드 실패: {it['url']} ({e})")
                continue
            assets["candidates"].append({**it, "bytes": data, "ext": ext, "license": "이용허락 미확인",
                                         "warn": "주최 측 허락 또는 공공누리 표시를 확인하기 전에는 발행에 사용 금지",
                                         "caption": "", "filename": f"candidate_{i:02d}{ext}"})
        rows.append(("공식 홈페이지 이미지(후보)", "warn",
                     f"{sum(1 for c in assets['candidates'] if c.get('candidate_only'))}장 후보로만 저장 — 이용허락 확인 전 사용 금지"))

    if want_card and fp.mode == "지원금/제도":
        f = fp.fields
        card, err = make_info_card_png(
            fp.title, [("대상", _short(f.get("지원대상", ""), 64)), ("혜택", _short(f.get("지원내용", ""), 64)),
                      ("신청기한", _short(f.get("신청기한", ""), 56)), ("접수", _short(f.get("접수기관", "") or f.get("소관기관명", ""), 40))],
            f"기준일 {fp.as_of} · {fp.source_label}",
        )
        assets["card"] = card
        rows.append(("정보 카드 이미지", "ok" if card else "warn", "직접 제작(저작권 문제 없음)" if card else f"제작 못 함 — {err}"))
    return rows, assets


# ───────────────────────── 발행 패키지(ZIP) ─────────────────────────
def build_package_zip(post: dict) -> bytes:
    """post: title, meta, tags, content, format, mode, topic, checks, fact_pack, assets."""
    fp, assets = post.get("fact_pack"), post.get("assets") or {}
    buf = io.BytesIO()
    ext = "html" if post.get("format") == "html" else "txt"
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"post.{ext}", post.get("content", ""))
        meta = {"title": post.get("title"), "meta": post.get("meta"), "tags": post.get("tags"), "mode": post.get("mode"),
                "topic": post.get("topic"), "generated_at": datetime.now().isoformat(timespec="seconds")}
        if fp is not None:
            meta.update({"official_found": fp.found, "official_source": fp.source_label, "as_of": fp.as_of,
                         "primary_link": fp.primary_link, "secondary_link": fp.secondary_link})
        zf.writestr("meta.json", json.dumps(meta, ensure_ascii=False, indent=2))
        if fp is not None and fp.facts_text:
            zf.writestr("official_data.md", f"# 공식 데이터 원문 (조회일 {fp.as_of}, {fp.source_label})\n\n{fp.facts_text}\n")
        lines = ["# 발행 전 체크", ""]
        for label, status, detail in post.get("checks", []):
            lines.append(f"- [{ {'ok': 'OK', 'warn': '확인', 'bad': '문제'}.get(status, status) }] {label}: {detail}")
        if assets.get("unverified"):
            lines += ["", "## 공식 데이터에 없는 숫자 (원문 확인 필요)"] + [f"- {a}  …{c}…" for a, c in assets["unverified"]]
        zf.writestr("CHECKLIST.md", "\n".join(lines) + "\n")
        credits = ["# 이미지 출처·이용조건", ""]
        for rec in assets.get("images", []):
            zf.writestr(f"images/{rec['filename']}", rec["bytes"])
            credits += [f"## images/{rec['filename']}", f"- 캡션(이미지 아래에 붙여넣기): {rec['caption']}", f"- 이용조건: {rec['license']}",
                        f"- 주의: {rec['warn'] or '-'}", f"- 원본 URL: {rec['url']}", ""]
        if assets.get("card"):
            zf.writestr("images/info_card.png", assets["card"])
            credits += ["## images/info_card.png", "- 직접 제작한 정보 카드(저작권 문제 없음)", ""]
        for rec in assets.get("candidates", []):
            zf.writestr(f"candidates_DO_NOT_PUBLISH/{rec['filename']}", rec["bytes"])
            credits += [f"## candidates_DO_NOT_PUBLISH/{rec['filename']}", f"- 상태: {rec['license']}", f"- 주의: {rec['warn']}",
                        f"- 원본 URL: {rec['url']}", ""]
        zf.writestr("IMAGE_CREDITS.md", "\n".join(credits) + "\n")
    return buf.getvalue()


# ───────────────────────── 연결 확인용 CLI ─────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python official_sources.py [gov24|festival|list|card] <검색어> <인증키>")
        raise SystemExit(0)
    cmd = sys.argv[1]
    if cmd == "card":
        png, err = make_info_card_png("샘플 지원금 정보 카드", [("대상", "2026년 대구 고교 1학년 둘째 이상 자녀 가정"), ("혜택", "둘째 30만원 · 셋째 이상 50만원"),
                                                               ("신청기한", "2026.9.30(수) 18:00까지"), ("접수", "대구광역시")], "기준일 2026-09-21 · 샘플")
        open("card_sample.png", "wb").write(png or b"")
        print("card_sample.png 생성" if png else f"실패: {err}")
        raise SystemExit(0)
    q, k = sys.argv[2], sys.argv[3]
    mode = {"gov24": "지원금/제도", "festival": "축제/행사", "list": "축제 모음(월별·계절)"}[cmd]
    fp = build_fact_pack(mode, q, k)
    print("found:", fp.found, "| error:", fp.error, "| notes:", fp.notes)
    print("candidates:", fp.candidates)
    print(fp.facts_text[:1500])
    print("images:", [i["url"] for i in fp.image_items])
