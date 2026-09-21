# -*- coding: utf-8 -*-
"""app.py 전체 흐름 스모크 테스트 (Gemini·공공데이터·네트워크를 모두 가짜로 대체). 실행: python smoke_apptest.py"""
import os
from unittest import mock

os.environ["GOOGLE_API_KEY"] = "fake"
import test_official_sources as T
from streamlit.testing.v1 import AppTest


def fake_get(url, params=None, headers=None, timeout=None, stream=False, **kw):
    try:
        return T.fake_get(url, params=params, headers=headers, timeout=timeout, stream=stream)
    except AssertionError:
        return T._Resp({}, text="", status=404)


CONTENT_OK = ('<div class="jb-post"><div class="jb-h2">요약</div><p>둘째 30만원, 셋째 이상 50만원. 9월 30일까지 신청.</p>'
              '<p>[이미지1][[IMG1|정보 카드|info card]]</p><p>최대 70만원까지 가능해요.</p><p>주차: [확인 필요]</p></div>')


class FakeResp:
    def __init__(self, text): self.text = text


class FakeModels:
    def __init__(self): self.prompts = []
    def generate_content(self, model, contents, config=None):
        self.prompts.append(contents)
        return FakeResp(f"###TITLE###\n테스트 제목\n###META###\n메타\n###TAGS###\n a,b,c\n###CONTENT###\n{CONTENT_OK}\n###THUMBNAIL###\nthumb\n###END###")


class FakeClient:
    def __init__(self, *a, **k): self.models = FakeModels()


def run(mode, topic, key="KEY", require=True):
    at = AppTest.from_file("app.py", default_timeout=60)
    at.secrets["DATA_GO_KR_KEY"] = key
    with mock.patch("requests.get", fake_get), mock.patch("google.genai.Client", FakeClient):
        at.run()
        assert not at.exception, at.exception
        at.selectbox[0].select(mode).run()
        at.text_input(key="topic_input").set_value(topic).run()
        [b for b in at.button if "블로그 글 생성" in b.label][0].click().run()
    return at


def show(at):
    print("  errors:", [e.value[:80] for e in at.error], "| exceptions:", at.exception)
    print("  success:", [s.value[:80] for s in at.success])
    print("  warnings:", [w.value[:70] for w in at.warning][:4])
    print("  download btns:", [b.label for b in at.get_by_type("download_button")] if hasattr(at, "get_by_type") else "n/a")


print("[1] 지원금 — 공식 데이터 있음")
at = run("지원금/제도", "대구 다자녀 고등학교 입학축하금 신청방법")
show(at)
r = at.session_state["result"]
print("  checks:", [(l, s) for l, s, _ in r["checks"] if l in ("공식 데이터 근거", "수치 검증", "미확정 표기", "정보 카드 이미지")])
assert r["fact_pack"].found and r["assets"]["card"]
assert any(l == "수치 검증" and s == "warn" for l, s, _ in r["checks"])   # 70만원 → 잡혀야 함

print("[2] 지원금 — 공식 데이터 없음 → 생성 중단")
at = run("지원금/제도", "존재하지않는외계인수당")
show(at)
assert at.session_state["result"] is None if "result" in at.session_state else True

print("[3] 지원금 — 키 없음 → 생성 중단")
at = run("지원금/제도", "대구 다자녀 고등학교 입학축하금", key="")
show(at)

print("[4] 축제 — 공식 이미지 저장")
at = run("축제/행사", "2026 안동국제탈춤페스티벌 일정")
show(at)
r = at.session_state["result"]
print("  images:", len(r["assets"]["images"]), "candidates:", len(r["assets"]["candidates"]))
assert len(r["assets"]["images"]) == 3

print("[5] 건강정보 — 공식 조회 대상 아님(기존 흐름 유지)")
at = run("건강정보", "혈압 낮추는 법")
show(at)
assert "fact_pack" in at.session_state["result"] and at.session_state["result"]["fact_pack"] is None
print("ALL OK")
