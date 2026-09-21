# -*- coding: utf-8 -*-
"""official_sources.py 동작 확인용 테스트 (실제 API 없이 응답을 흉내 내서 검증).
실행: python test_official_sources.py
※ 실제 API 주소·필드가 다를 수 있으니, 인증키를 넣고 `python official_sources.py gov24 "검색어" 키`로 한 번 연결 확인을 해 주세요.
"""
import io
import json
import unittest
import zipfile
from datetime import date
from unittest import mock

from PIL import Image

import official_sources as osrc


def _png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "#446688").save(buf, "PNG")
    return buf.getvalue()


class _Raw:
    def __init__(self, data):
        self._d = data

    def read(self, n=-1, decode_content=True):
        return self._d[:n] if n and n > 0 else self._d


class _Resp:
    def __init__(self, payload=None, text="", status=200, headers=None, raw=None):
        self._p, self.text, self.status_code = payload, text, status
        self.headers, self.raw = headers or {}, raw

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"{self.status_code}")


GOV24_LIST = {"data": [
    {"서비스ID": "627000000113", "서비스명": "대구광역시 다자녀가정 고등학교 입학축하금 지원"},
    {"서비스ID": "111", "서비스명": "전혀 다른 서비스"},
]}
GOV24_DETAIL = {"data": [{
    "서비스ID": "627000000113", "서비스명": "대구광역시 다자녀가정 고등학교 입학축하금 지원",
    "지원내용": "둘째자녀 30만원, 셋째자녀 이상 50만원 지원",
    "지원대상": "2026년도 대구시 소재 고등학교 1학년에 입학하여 재학중인 둘째이상 자녀 가정",
    "신청기한": "2026.8.24.(월)9:00~9.30.(수)18:00(온라인 24:00)", "신청방법": "정부24 온라인 신청",
    "소관기관명": "대구광역시", "문의처": "대구시청 출산보육과/053-803-5452", "조회수": 999,
}]}
TOUR_KEYWORD = {"response": {"header": {"resultCode": "0000"}, "body": {"items": {"item": [
    {"contentid": "506670", "title": "안동국제탈춤페스티벌", "addr1": "경상북도 안동시 육사로 239", "firstimage": "https://img.test/first.png"},
    {"contentid": "1", "title": "다른 축제", "addr1": "서울"},
]}}}}
TOUR_COMMON = {"response": {"header": {"resultCode": "0000"}, "body": {"items": {"item": [
    {"contentid": "506670", "title": "안동국제탈춤페스티벌", "addr1": "경상북도 안동시 육사로 239", "tel": "054-840-3400",
     "homepage": '<a href="https://www.maskdance.com/2024/main.asp" target="_blank">공식</a>', "overview": "가면의 기억, 모두의 춤", "firstimage": "https://img.test/first.png"}]}}}}
TOUR_INTRO = {"response": {"header": {"resultCode": "0000"}, "body": {"items": {"item": [
    {"eventstartdate": "20260924", "eventenddate": "20261004", "eventplace": "탈춤공원", "playtime": "10:00 ~ 22:00",
     "usetimefestival": "무료 (일부 체험 유료)", "sponsor1": "한국정신문화재단", "sponsor1tel": "054-840-3400",
     "program": "1. 탈춤 공연<br>2. 퍼레이드"}]}}}}
TOUR_IMAGES = {"response": {"header": {"resultCode": "0000"}, "body": {"items": {"item": [
    {"imgname": "포스터", "originimgurl": "https://img.test/a.png", "cpyrhtDivCd": "Type1"},
    {"imgname": "상업불가", "originimgurl": "https://img.test/b.png", "cpyrhtDivCd": "Type2"},
    {"imgname": "변경금지", "originimgurl": "https://img.test/c.png", "cpyrhtDivCd": "Type3"},
]}}}}


def fake_get(url, params=None, headers=None, timeout=None, stream=False):
    if "KorService2" in url:                       # 신버전 실패 → 구버전 폴백 확인
        return _Resp({}, status=404)
    if "gov24/v3/serviceList" in url:
        return _Resp(GOV24_LIST)
    if "gov24/v3/serviceDetail" in url:
        return _Resp(GOV24_DETAIL)
    if "NationalWelfarelistV001" in url:
        return _Resp(text="<response><header/></response>")
    if "searchKeyword1" in url:
        return _Resp(TOUR_KEYWORD)
    if "detailCommon1" in url:
        return _Resp(TOUR_COMMON)
    if "detailIntro1" in url:
        return _Resp(TOUR_INTRO)
    if "detailImage1" in url:
        return _Resp(TOUR_IMAGES)
    if url.startswith("https://img.test/"):
        return _Resp(headers={"Content-Type": "image/png"}, raw=_Raw(_png_bytes()))
    raise AssertionError(f"예상 못 한 호출: {url}")


class OfficialSourcesTest(unittest.TestCase):
    def test_benefit_fact_pack(self):
        with mock.patch("requests.get", fake_get):
            fp = osrc.build_fact_pack("지원금/제도", "대구 다자녀 고등학교 입학축하금 신청방법", "KEY%2B")
        self.assertTrue(fp.found, fp.error)
        self.assertIn("둘째자녀 30만원", fp.facts_text)
        self.assertIn("대구시청 출산보육과", fp.facts_text)
        self.assertNotIn("조회수", fp.facts_text)                      # 잡음 필드 제외
        self.assertTrue(fp.secondary_link.endswith("627000000113"))    # gov.kr 상세 링크
        self.assertIn("유일한 사실 근거", fp.prompt_block)

    def test_benefit_not_found_blocks(self):
        with mock.patch("requests.get", fake_get):
            fp = osrc.build_fact_pack("지원금/제도", "존재하지않는외계인수당", "KEY")
        self.assertFalse(fp.found)
        self.assertTrue(fp.error)

    def test_missing_key(self):
        fp = osrc.build_fact_pack("지원금/제도", "아무거나", "")
        self.assertFalse(fp.found)
        self.assertIn("인증키", fp.error)

    def test_festival_fact_pack_and_fallback(self):
        with mock.patch("requests.get", fake_get):
            fp = osrc.build_fact_pack("축제/행사", "2026 안동국제탈춤페스티벌 일정", "KEY")
        self.assertTrue(fp.found, fp.error)
        self.assertIn("2026-09-24 ~ 2026-10-04", fp.facts_text)
        self.assertIn("한국정신문화재단", fp.facts_text)
        self.assertEqual(fp.homepage, "https://www.maskdance.com/2024/main.asp")
        self.assertIn("[확인 필요]", fp.facts_text)                     # 주차 등 없는 정보 안내
        self.assertEqual(len(fp.image_items), 4)                        # 대표 + 상세 3장

    def test_verify_numbers(self):
        facts = "둘째자녀 30만원, 셋째자녀 이상 50만원 / 2026.8.24 ~ 9.30 / 053-803-5452"
        good = "<p>둘째는 30만원, 셋째 이상은 50만원이에요. 9월 30일까지 신청하세요. [이미지1]</p>"
        bad = "<p>최대 70만원까지 받을 수 있고 1,200명을 선발해요.</p><style>.a{width:100px}</style>"
        self.assertEqual(osrc.verify_numbers(good, facts, date(2026, 9, 21)), [])
        found = [a for a, _ in osrc.verify_numbers(bad, facts, date(2026, 9, 21))]
        self.assertIn("70만원", found)
        self.assertIn("1,200명", found)
        self.assertFalse(any("100" in a for a in found))                # style 속 숫자는 무시

    def test_license_filtering_and_package(self):
        with mock.patch("requests.get", fake_get):
            fp = osrc.build_fact_pack("축제/행사", "안동국제탈춤페스티벌", "KEY")
            rows, assets = osrc.post_process(fp, "<p>2026년 9월 24일부터 열려요. 입장료 무료. 주차는 [확인 필요]</p>", want_card=False)
        names = [r[0] for r in rows]
        self.assertIn("공식 이미지 저장", names)
        self.assertEqual(len(assets["images"]), 3)                      # 대표(표기없음) + Type1 + Type3
        self.assertEqual(len(assets["candidates"]), 1)                  # Type2 상업적 이용 금지 → 후보로만
        self.assertTrue(any("변경금지" in r["warn"] for r in assets["images"]))
        post = {"title": "t", "meta": "m", "tags": "a,b", "content": "<p>x</p>", "format": "html", "mode": "축제/행사",
                "topic": "안동", "checks": rows, "fact_pack": fp, "assets": assets}
        z = zipfile.ZipFile(io.BytesIO(osrc.build_package_zip(post)))
        n = z.namelist()
        self.assertIn("post.html", n)
        self.assertIn("IMAGE_CREDITS.md", n)
        self.assertTrue(any(x.startswith("images/official_") for x in n))
        self.assertTrue(any(x.startswith("candidates_DO_NOT_PUBLISH/") for x in n))
        self.assertIn("이미지 출처: 한국관광공사", z.read("IMAGE_CREDITS.md").decode("utf-8"))

    def test_info_card(self):
        png, err = osrc.make_info_card_png("대구광역시 다자녀가정 고등학교 입학축하금 지원",
                                           [("대상", "고1 둘째 이상"), ("혜택", "30만원/50만원"), ("신청기한", "9.30 18:00"), ("접수", "대구광역시")],
                                           "기준일 2026-09-21")
        self.assertIsNotNone(png, err)
        self.assertEqual(Image.open(io.BytesIO(png)).size, (1200, 630))

    def test_period_parse(self):
        s, e, code, name = osrc._parse_period("10월 경기 축제 추천", date(2026, 9, 21))
        self.assertEqual((s, e, code, name), (date(2026, 10, 1), date(2026, 10, 31), "31", "경기"))
        s, e, _, _ = osrc._parse_period("겨울 축제", date(2026, 9, 21))
        self.assertEqual((s, e), (date(2026, 12, 1), date(2027, 2, 28)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
