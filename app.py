import os
import re
import time
import datetime
import requests
import streamlit as st
import streamlit.components.v1 as components
import google.generativeai as genai
from bs4 import BeautifulSoup

# ────────────────────────────────────────────────────────────────
# 설정
# ────────────────────────────────────────────────────────────────
st.set_page_config(page_title="포스트팩토리 — SEO 블로그 자동작성", page_icon="📝", layout="wide")

QUALITY_RULES = (
    "모바일 가독성을 위해 한 문장은 평균 40~50자 이내로 짧게 끊고, 2~4문장마다 문단을 나누세요. "
    "핵심 키워드는 제목/도입부/소제목 2곳 이상/마무리에 걸쳐 자연스럽게 5~7회 반복하되 "
    "억지로 욱여넣지 말고 문맥에 맞는 동의어·변형 표현으로 분산하세요. "
    "친근하고 신뢰감 있는 어조로, 독자가 흔히 궁금해하거나 헷갈리는 지점을 콕 짚어 먼저 풀어주세요. "
    "\"이것은 중요한 요소입니다\", \"다음과 같은 방법이 있습니다\" 같은 딱딱하고 상투적인 AI 문체는 피하세요. "
    "단, 실제로 확인되지 않은 1인칭 경험(예: 특정 제품을 직접 써봤다는 구체적 후기)을 사실처럼 지어내지는 마세요 — "
    "독자를 오도할 수 있으므로, 대신 흔히 겪는 상황에 공감하는 화법으로 신뢰를 쌓으세요."
)

STYLE_GUIDE = (
    "다음은 이 블로그 필자의 고유한 말투이니 반드시 반영하세요: "
    "도입부는 '안녕하세요!' 같은 짧은 인사, 또는 독자의 경험에 공감을 구하는 질문"
    "(예: '혹시 ~해보신 적 있으신가요?', '~ 때문에 고민이신가요?')으로 시작하고, "
    "이 글을 쓰게 된 개인적 계기나 상황을 1~2문장으로 먼저 밝히세요. "
    "전체 서술은 1인칭 경험담 화법을 기본으로 하되('저도 ~했는데', '제가 알아보니'), "
    "이 챕터/섹션에서 실제로 확인되지 않은 구체적 개인 체험을 지어내지는 마세요 — "
    "체험이 확실하지 않을 때는 '~라고 해요', '~더라고요(전해 들은 정보)'처럼 톤만 유지하고 사실을 지어내지 않습니다. "
    "문장 끝맺음은 '~했어요', '~하더라구요', '~랍니다', '~한답니다', '~네요'처럼 "
    "부드럽고 구어체적인 존댓말로 통일하고, 단정적인 서술('~입니다', '~합니다')보다는 "
    "완곡한 어미('~인 것 같아요', '~인 듯해요')를 섞어 친근한 톤을 유지하세요. "
    "한 문단은 1~3문장으로 짧게 끊어 모바일에서 술술 읽히게 구성하고, "
    "'정말', '진짜', '너무', '완전' 같은 감탄 부사를 과하지 않게 섞어 감정을 자연스럽게 드러내세요. "
    "글 말미는 요약이나 다짐 한두 문장으로 마무리하고, 자연스러우면 다음 이야기를 예고하거나"
    "('다음엔 ~해볼게요') 개인차가 있을 수 있다는 담백한 단서를 덧붙이세요."
)

AD_SLOT_RULES = (
    "<!--AD_SLOT--> 마커를 정확히 3번, 다른 텍스트로 바꾸지 말고 그대로 출력하세요: "
    "① 도입부 첫 CTA 버튼 바로 다음 ② 두 번째 jb-h2 섹션이 끝난 직후 ③ jb-qa(Q&A) 시작 바로 전."
)

IMAGE_PROMPT_RULES = (
    "소제목(섹션) 하나당 이미지 1개씩, 보통 4~6개 정도가 적당합니다. 이미지가 들어가면 좋을 자리마다 "
    "본문에 [이미지1], [이미지2]처럼 번호가 매겨진 자리 표시를 넣고, 그 번호와 정확히 일치하는 영어 이미지 생성 "
    "프롬프트를 본문과 별도로 ###IMAGES### 섹션에 한 줄씩 작성하세요 (예: [이미지1] A cozy realistic photo of ...). "
    "프롬프트는 사실적인 사진 스타일로 피사체·구도·조명·분위기를 구체적으로 묘사하세요."
)

# ────────────────────────────────────────────────────────────────
# 콘텐츠 유형 — 플랫폼(HTML/텍스트)과 무관한 내용/구조 규칙
# ────────────────────────────────────────────────────────────────
CONTENT_TYPES = {
    "지원금/제도": {
        "topic_label": "지원금/제도 이름",
        "topic_placeholder": "예: 청년월세지원",
        "link_mode": "dual",
        "link1_label": "링크1 · 신청하러 가기 (비우면 자동 검색)",
        "link2_label": "링크2 · 자격 조회하기 (비우면 자동 검색)",
        "cta1_text": "신청하러 가기", "cta2_text": "자격 조회하기",
        "disclosure": None,
        "trend_hint": "요즘 화제인 정부·지자체 지원금 또는 정책 이름",
        "base_system": (
            "당신은 20년차 SEO 전문가이자 정부 지원금 정보 콘텐츠 작가입니다. "
            "독자는 해당 지원금 대상 여부가 궁금해서 검색해 들어온 사람입니다. "
            "손실 회피 문구로 도입부를 시작해 관심을 끌고, "
            "신청 방법 → 대상 조건 → 지급 금액/유효기간 → Q&A 순으로 구성하세요. "
            "실제 존재하는 제도라면 사실 관계를 왜곡하지 말고, "
            "확실하지 않은 수치는 '지자체·연도별로 다를 수 있음'으로 처리하세요."
        ),
    },
    "축제/행사": {
        "topic_label": "축제/행사 이름",
        "topic_placeholder": "예: 직지문화축제",
        "link_mode": "single",
        "link1_label": "공식 홈페이지 링크 (비우면 자동 검색)",
        "cta1_text": "공식 홈페이지 바로가기", "cta2_text": "공식 홈페이지 바로가기",
        "disclosure": None,
        "trend_hint": "이번 달~다음 달 국내에서 열리는 인기 축제·행사",
        "base_system": (
            "당신은 20년차 SEO 전문가이자 지역 축제 여행 콘텐츠 작가입니다. "
            "독자는 이 축제에 가볼지 결정하려는 사람입니다. "
            "'핵심 명소'와 '주요 프로그램'은 절대 긴 문단으로 나열하지 말고, "
            "항목별로 이모지 + 짧은 이름 + 1~2문장 설명 형태의 카드형 목록으로 3~4개씩 작성하세요 "
            "(형식 규칙에 안내된 카드/목록 표현 방식을 그대로 따르세요). "
            "그 다음 기본 정보(기간/장소/교통/주차) → 방문 꿀팁 → 함께 즐기면 좋은 다른 행사 순으로 구성하세요."
        ),
    },
    "건강정보": {
        "topic_label": "건강 주제/키워드",
        "topic_placeholder": "예: 혈압 낮추는 법",
        "link_mode": "single",
        "link1_label": "참고 링크 (선택 — 없으면 CTA 없이 작성)",
        "cta1_text": "자세히 보기", "cta2_text": "자세히 보기",
        "disclosure": "health",
        "trend_hint": "최근 검색량이 오르는 건강·생활습관 관련 주제",
        "base_system": (
            "당신은 20년차 SEO 전문가이자 건강 정보 콘텐츠 작가입니다. "
            "독자는 실생활에서 바로 실천할 수 있는 건강 관리법이 궁금해서 검색해 들어온 사람입니다. "
            "흔한 오해나 궁금증으로 도입부를 시작하고, 원인/배경 → 실천 방법(단계별 또는 카드형 목록) → "
            "주의사항 → Q&A 순으로 구성하세요. "
            "특정 의약품명이나 복용량, 개별 진단/치료를 지시하는 문장은 절대 쓰지 마세요. "
            "운동·식습관·수면 같은 일반적인 생활습관 정보만 다루고, '~에 도움이 된다고 알려져 있습니다', "
            "'전문가들은 ~을 권장합니다'처럼 출처를 특정하지 않는 일반론으로 서술하세요. "
            "실존 여부가 불확실한 특정 연구·논문·저널명을 지어내 인용하지 마세요."
        ),
    },
    "쿠팡파트너스": {
        "topic_label": "상품/카테고리명",
        "topic_placeholder": "예: 무선 청소기 추천",
        "link_mode": "single",
        "link1_label": "쿠팡 파트너스 링크",
        "cta1_text": "최저가 확인하기", "cta2_text": "최저가 확인하기",
        "disclosure": "coupang",
        "trend_hint": "요즘 잘 팔리는 인기 제품 카테고리",
        "base_system": (
            "당신은 20년차 SEO 전문가이자 쿠팡 파트너스 제휴 마케팅 콘텐츠 작가입니다. "
            "서론(공감 유도 + 링크 자리 1회) → 상품별 분석(장단점을 솔직하게, 스펙 비교 포함) → "
            "결론(핵심 요약 + 링크 자리 1회) → 자주 묻는 질문 3~5개 → 해시태그/태그 순으로 구성하세요. "
            "장점만 나열하지 말고 단점이나 이런 분께는 안 맞을 수 있다는 점도 최소 1곳 솔직하게 언급하세요."
        ),
    },
    "일반 블로그": {
        "topic_label": "주제/키워드",
        "topic_placeholder": "예: 겨울철 난방비 절약 방법",
        "link_mode": "single",
        "link1_label": "참고 링크 (선택)",
        "cta1_text": "자세히 보기", "cta2_text": "자세히 보기",
        "disclosure": None,
        "trend_hint": "요즘 검색량이 오르는 생활정보 주제",
        "base_system": (
            "당신은 20년차 SEO 전문가이자 정보성 블로그 작가입니다. "
            "검색 의도에 정확히 부합하는 실용적인 정보를 다루세요. "
            "핵심 항목이 여러 개 나열되는 부분(방법 목록, 추천 목록 등)은 긴 문단 대신 "
            "카드형 목록으로 정리하면 가독성이 좋습니다(해당될 때만). "
            "왜 중요한지(도입) → 핵심 정보/방법을 섹션별로 → 실수하기 쉬운 점(팁) → Q&A 순으로 구성하세요."
        ),
    },
}

SKIN_CLASSES_DOC = """
사용 가능한 스킨 클래스 (이 클래스만 사용해서 HTML을 작성할 것. 새로운 class나 인라인 style은 만들지 말 것):
- <div class="jb-post"> : 전체 글 감싸는 최외곽 wrapper (필수, 1개)
- <div class="jb-hero">...</div> : 글 맨 위 히어로 배너 (필수, 1개)
- <div class="jb-cta-wrap"><a class="jb-cta" href="LINK">버튼 텍스트👆</a></div> : CTA 버튼
- <div class="jb-h2">섹션 제목</div> : 섹션 제목, 이모지 1개 포함. 분량 목표에 맞춰 4~6개 사용
- <div class="jb-info">...</div> : 기본정보 요약 카드 (jb-info-row/label/val 조합, 선택)
- <div class="jb-spot-list"><div class="jb-spot-item"><div class="jb-spot-icon">이모지</div><div class="jb-spot-body"><div class="jb-spot-name">이름</div><div class="jb-spot-desc">1~2문장 설명</div></div></div>...</div>
  : "카드형 목록"을 요청받으면 이 클래스로 표현 (3~4개 항목)
- <div class="jb-tip"><b>라벨</b> 설명글</div> : 꿀팁/주의사항/안내 박스 (2~3개)
- <div class="jb-table-wrap"><table class="jb-table">...</table></div> : 비교/조건표 (선택)
- <div class="jb-qa"><div class="jb-qa-item"><div class="jb-qa-q">Q. 질문</div><div class="jb-qa-a">답변</div></div>...</div> : Q&A, 2~3문항
- <div class="jb-divider">· · ·</div> : 섹션 구분선 (선택)
- <div class="jb-img-slot">🖼️ [이미지N] 이 자리에 이미지를 삽입하세요</div> : 이미지 자리 표시
- <span class="jb-highlight">강조 텍스트</span> : 본문 강조 inline span
- 일반 문단은 <p>텍스트</p>

작성 규칙:
- 본문 분량 목표에 맞춰 충분히 작성하고, 마지막에 반드시 ###END### 까지 도달할 것 (중간에 끊지 말 것)
- 모든 태그를 빠짐없이 닫을 것
- 코드펜스나 설명 문구 없이, 지정된 마커 형식으로만 응답할 것
"""

TEXT_RULES_DOC = """
작성 형식 (네이버 스마트에디터용 순수 텍스트):
- HTML 태그, 마크다운 기호(#, *, ``` 등)를 절대 사용하지 말 것
- 소제목은 줄 앞에 이모지 1개 + 짧은 문구로 표시 (예: "✅ 핵심 스펙 비교")
- "카드형 목록"을 요청받으면, 항목마다 "이모지 이름" 한 줄 + 바로 아래 설명 한 줄, 항목 사이는 빈 줄로 구분
- 표가 필요하면 "항목: 설명" 형태로 한 줄씩 나열
- 문단 사이는 빈 줄 하나로 구분
- 이미지가 들어갈 자리는 줄 단독으로 "[이미지1]"처럼 표시
- CTA/링크를 넣을 자리는 반드시 아래 형식 그대로 표시:
  👉 [문구] → LINK
- 본문 분량 목표에 맞춰 충분히 작성하고, 마지막에 반드시 ###END### 까지 도달할 것 (중간에 끊지 말 것)
- 코드펜스나 설명 문구 없이, 지정된 마커 형식으로만 응답할 것
"""

PLATFORMS = {
    "티스토리 (HTML)": {"format": "html", "rules_doc": SKIN_CLASSES_DOC, "extra_rules": AD_SLOT_RULES},
    "네이버 (텍스트)": {"format": "text", "rules_doc": TEXT_RULES_DOC, "extra_rules": ""},
}

SKIN_CSS = """
.jb-post{font-family:'Pretendard',-apple-system,sans-serif;color:#212832;font-size:16px;line-height:1.85;max-width:720px;margin:0 auto;padding:26px 22px 40px;}
.jb-post p{margin:0 0 14px;}
.jb-highlight{color:#E0507A;font-weight:700;}
.jb-hero{position:relative;background:linear-gradient(135deg,#1B2A41 0%,#233A57 100%);border-radius:16px;padding:26px 26px 20px;margin-bottom:30px;color:#fff;}
.jb-hero-tag{display:inline-block;font-size:12px;font-weight:700;letter-spacing:.03em;color:#1B2A41;background:#E3A03E;padding:4px 11px;border-radius:20px;margin-bottom:12px;}
.jb-hero-title{font-size:23px;font-weight:800;line-height:1.4;margin:0 0 14px;letter-spacing:-.01em;}
.jb-hero-perf{border-top:2px dashed rgba(255,255,255,.28);position:relative;margin:0 -26px;}
.jb-hero-perf::before,.jb-hero-perf::after{content:'';position:absolute;top:-9px;width:18px;height:18px;border-radius:50%;background:#ffffff;}
.jb-hero-perf::before{left:-9px;} .jb-hero-perf::after{right:-9px;}
.jb-hero-meta{font-size:13px;color:#C9D3E0;padding-top:14px;}
.jb-cta-wrap{text-align:center;margin:26px 0;}
.jb-cta{display:inline-block;background:#F0A202;color:#241802;font-weight:800;font-size:15px;padding:13px 30px;border-radius:30px;text-decoration:none;box-shadow:0 6px 16px rgba(240,162,2,.35);}
.jb-h2{font-size:18.5px;font-weight:800;color:#1B2A41;margin:34px 0 14px;padding-bottom:9px;border-bottom:3px solid #1B2A41;display:inline-block;}
.jb-info{background:#FFFBF5;border:1px solid #F0E4D0;border-radius:12px;padding:6px 18px;margin:14px 0 20px;}
.jb-info-row{display:flex;gap:14px;padding:11px 0;border-bottom:1px dashed #EADFC8;font-size:14.5px;}
.jb-info-row:last-child{border-bottom:none;}
.jb-info-label{flex:0 0 88px;font-weight:700;color:#B5762F;}
.jb-info-val{color:#3A3A3A;}
.jb-spot-list{margin:14px 0 22px;}
.jb-spot-item{display:flex;gap:13px;padding:14px 0;border-bottom:1px dashed #EADFC8;}
.jb-spot-item:last-child{border-bottom:none;}
.jb-spot-icon{font-size:23px;flex:0 0 30px;line-height:1.5;}
.jb-spot-name{font-weight:800;color:#1B2A41;font-size:15px;margin-bottom:4px;}
.jb-spot-desc{font-size:14px;color:#454545;line-height:1.7;}
.jb-tip{background:#EAF7F3;border-left:4px solid #1F6F63;border-radius:0 10px 10px 0;padding:13px 16px;margin:12px 0;font-size:14.5px;color:#184E46;line-height:1.7;}
.jb-tip b{color:#0F3A33;}
.jb-table-wrap{overflow-x:auto;margin:16px 0 22px;border-radius:10px;border:1px solid #E7E1D6;}
.jb-table{width:100%;border-collapse:collapse;font-size:13.5px;min-width:420px;}
.jb-table th{background:#1B2A41;color:#fff;padding:10px 8px;font-size:13px;}
.jb-table td{padding:10px 8px;text-align:center;border-top:1px solid #EFEAE0;color:#333;}
.jb-table tr:nth-child(even) td{background:#FBF8F2;}
.jb-qa{margin:18px 0;}
.jb-qa-item{background:#F7F6F3;border-radius:10px;padding:14px 16px;margin-bottom:10px;}
.jb-qa-q{font-weight:800;color:#1B2A41;font-size:14.5px;margin-bottom:6px;}
.jb-qa-a{font-size:14px;color:#454545;line-height:1.75;}
.jb-divider{text-align:center;color:#C7BFAE;font-size:13px;margin:28px 0;letter-spacing:.4em;}
.jb-ad-slot{margin:26px 0;text-align:center;}
.jb-img-slot{margin:18px 0;padding:40px 16px;text-align:center;background:#F4F1EA;border:2px dashed #D8D0BE;border-radius:12px;color:#8B8371;font-size:14px;}
"""

TONE_OPTIONS = {
    "친근한 존댓말": "친근하고 다정한 존댓말, 어려운 용어를 풀어서 설명",
    "담백한 존댓말": "정보 전달에 집중하는 담백하고 정중한 존댓말",
    "전문적 문어체": "전문적이고 신뢰감 있는 문어체",
}
LENGTH_OPTIONS = {
    "짧게": "(공백 제외) 1500~2000자 분량으로 핵심만 간결하게",
    "보통": "(공백 제외) 3000자 이상, 검색엔진이 '깊이 있는 정보'로 평가할 만큼 충분한 근거·사례·세부 설명을 갖춰 작성",
}

DISCLOSURE_TEXT = "본 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."
HEALTH_DISCLAIMER = "이 글은 일반적인 건강 정보 제공을 목적으로 하며, 개인의 의학적 진단이나 치료를 대체하지 않습니다. 증상이 있다면 반드시 전문의와 상담하세요."


def get_client():
    api_key = st.secrets.get("GOOGLE_API_KEY", None) or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        api_key = st.session_state.get("manual_api_key", "")
    if not api_key:
        return None
    genai.configure(api_key=api_key)
    return genai


# ────────────────────────────────────────────────────────────────
# 웹 리서치 — Gemini 내장 구글 검색 연동(grounding). 별도 API 등록 불필요.
# ────────────────────────────────────────────────────────────────
def _extract_grounding_sources(response):
    sources = []
    try:
        gm = getattr(response.candidates[0], "grounding_metadata", None)
        if not gm:
            return sources
        for ch in (getattr(gm, "grounding_chunks", None) or []):
            web = getattr(ch, "web", None)
            if web and getattr(web, "uri", ""):
                sources.append({"title": getattr(web, "title", "") or web.uri, "link": web.uri})
    except Exception:
        pass
    return sources


def _grounded_call(prompt, model_name="gemini-flash-latest", max_output_tokens=1200):
    tool_variants = [{"google_search": {}}], "google_search_retrieval", None
    thinking_variants = (0, None)  # 생각 토큰이 답변 예산을 먼저 잡아먹어 잘리는 문제 방지 (0 먼저 시도)
    for tools in tool_variants:
        for tb in thinking_variants:
            try:
                model = genai.GenerativeModel(model_name, tools=tools) if tools else genai.GenerativeModel(model_name)
                gen_kwargs = {"max_output_tokens": max_output_tokens, "temperature": 0.4}
                if tb is not None:
                    gen_kwargs["thinking_config"] = genai.types.ThinkingConfig(thinking_budget=tb)
                resp = model.generate_content(prompt, generation_config=genai.types.GenerationConfig(**gen_kwargs))
                if resp and resp.text and resp.text.strip():
                    sources = _extract_grounding_sources(resp) if tools else []
                    return resp.text.strip(), sources
            except Exception:
                continue
    return "", []


def search_official_link(query):
    text, sources = _grounded_call(
        f"'{query}'의 공식 웹사이트 또는 공식 신청 페이지 URL을 정확히 찾아서 URL만 한 줄로 답해줘. "
        f"설명 문구 없이 URL만 출력해.",
        max_output_tokens=200,
    )
    if sources:
        return sources[0]["link"], None
    m = re.search(r"https?://[^\s\"'<>]+", text)
    return (m.group(0), None) if m else (None, "검색 결과 없음")


def research_topic(topic, max_results=5):
    prompt = f"""'{topic}'에 대해 구글 검색을 활용해 다음을 조사해줘:
1. 사람들이 실제로 많이 검색할 만한 세부 키워드(연관 검색어) 5~8개
2. 그중 경쟁이 상대적으로 약해 보이는 키워드 우선순위
3. 이 주제에 대해 검색으로 확인 가능한 핵심 정보(수치·조건·절차 등, 최신 기준)를 간결하게 요약

확인되지 않은 내용은 지어내지 말고, 검색으로 실제 확인한 내용 위주로 정리해줘.
한국어로, 800자 이내로 간결하게."""
    text, sources = _grounded_call(prompt, max_output_tokens=1400)
    if not text:
        return "", []
    block = (
        "다음은 이 주제에 대해 웹 검색으로 실제 조사한 리서치 자료입니다. "
        "이 자료의 사실 관계를 우선순위로 삼아 작성하고, 여기 없는 내용을 사실처럼 지어내지 마세요:\n" + text
    )
    return block, sources


def research_seo_rules(platform_hint):
    prompt = (
        f"{platform_hint} 블로그의 2026년 기준 최신 SEO 상위노출 규칙을 구글 검색으로 조사해줘. "
        f"제목 규칙, 본문 구조·분량, 키워드 밀도·위치, 이미지 개수, 해시태그, 저품질/금지 패턴을 "
        f"항목별로 간결하게 정리해줘. 확인 안 된 내용은 지어내지 마. 한국어로 700자 이내."
    )
    return _grounded_call(prompt, max_output_tokens=1200)


def suggest_trending_topics(content_key, count=8):
    hint = CONTENT_TYPES[content_key]["trend_hint"]
    prompt = f"""요즘({hint}) 관련해서 사람들이 실제로 많이 검색하는 주제나 키워드를
검색 결과를 바탕으로 {count}개 뽑아줘. 블로그 글 주제로 바로 쓸 수 있는 짧은 명사구로,
번호·설명·부가문구 없이 한 줄에 하나씩만 출력해."""
    text, sources = _grounded_call(prompt, max_output_tokens=900)
    if not text:
        return [], []
    keywords = [re.sub(r"^[\-\•\d\.\)\s]+", "", line).strip() for line in text.splitlines() if line.strip()]
    return [k for k in keywords if k][:count], sources


def datalab_ready():
    cid = st.secrets.get("NAVER_CLIENT_ID", None) or os.environ.get("NAVER_CLIENT_ID")
    csec = st.secrets.get("NAVER_CLIENT_SECRET", None) or os.environ.get("NAVER_CLIENT_SECRET")
    return bool(cid and csec)


def verify_with_datalab(keywords, days=30):
    """네이버 데이터랩 검색어트렌드 API로 후보 키워드들의 상대 검색량을 비교해 순위를 매긴다.
    실시간 급상승 검색어는 제공되지 않으므로(2021년 서비스 종료), '발굴'이 아니라 '검증' 용도로만 쓴다.
    한 번에 최대 5개까지만 비교 가능하다(네이버 API 제한). NAVER_CLIENT_ID/SECRET이 없으면 (None, '미설정')."""
    cid = st.secrets.get("NAVER_CLIENT_ID", None) or os.environ.get("NAVER_CLIENT_ID")
    csec = st.secrets.get("NAVER_CLIENT_SECRET", None) or os.environ.get("NAVER_CLIENT_SECRET")
    if not cid or not csec or not keywords:
        return None, "미설정"
    end = datetime.date.today()
    start = end - datetime.timedelta(days=days)
    groups = [{"groupName": kw[:20], "keywords": [kw]} for kw in keywords[:5]]
    try:
        resp = requests.post(
            "https://openapi.naver.com/v1/datalab/search",
            headers={"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": csec, "Content-Type": "application/json"},
            json={"startDate": start.isoformat(), "endDate": end.isoformat(), "timeUnit": "date", "keywordGroups": groups},
            timeout=10,
        )
        results = resp.json().get("results", [])
        scored = []
        for r in results:
            vals = [p.get("ratio", 0) for p in r.get("data", [])]
            avg = sum(vals) / len(vals) if vals else 0
            scored.append({"keyword": r.get("title", ""), "score": round(avg, 1)})
        return scored, None
    except Exception as e:
        return None, str(e)


def verify_with_datalab_all(keywords, days=30):
    """keywords 전체(개수 제한 없음)를 5개씩 나눠서 verify_with_datalab을 반복 호출하고,
    하나로 합쳐서 검색량 기준 내림차순 정렬한 전체 순위 리스트를 반환한다.
    일부 묶음이 실패해도 나머지는 그대로 반환하고, 검증 실패한 키워드는 unscored로 따로 담는다."""
    if not keywords:
        return [], []
    scored_all, unscored = [], []
    for i in range(0, len(keywords), 5):
        chunk = keywords[i:i + 5]
        result, err = verify_with_datalab(chunk, days)
        if result:
            scored_all.extend(result)
        else:
            unscored.extend(chunk)
    scored_all.sort(key=lambda x: x["score"], reverse=True)
    return scored_all, unscored


def extract_between(text, start_marker, end_marker):
    s = text.find(start_marker)
    if s == -1:
        return ""
    frm = s + len(start_marker)
    e = text.find(end_marker, frm)
    return (text[frm:] if e == -1 else text[frm:e]).strip()


def _insert_after_post_open(content, snippet):
    m = re.search(r'<div class="jb-post"[^>]*>', content)
    return content[:m.end()] + snippet + content[m.end():] if m else snippet + content


def _insert_before_last_close(content, snippet):
    idx = content.rfind("</div>")
    return content[:idx] + snippet + content[idx:] if idx != -1 else content + snippet


def generate_post(content_key, platform_key, topic, link1, link2, tone_key, length_key, extra,
                   research_block="", seo_notes=""):
    ccfg = CONTENT_TYPES[content_key]
    pcfg = PLATFORMS[platform_key]
    fmt = pcfg["format"]
    tone = TONE_OPTIONS[tone_key]
    length = LENGTH_OPTIONS[length_key]

    system = ccfg["base_system"] + " " + QUALITY_RULES + " " + STYLE_GUIDE + " " + pcfg["extra_rules"] + " " + IMAGE_PROMPT_RULES

    link_desc = f"링크1: {link1}" if ccfg["link_mode"] == "single" else f"링크1(신청): {link1}\n링크2(자격조회): {link2}"
    has_real_link = link1 != "[링크 입력]"
    if not has_real_link:
        cta_note = "이번 글에는 실제 링크가 없으므로 CTA를 아예 넣지 마세요."
    elif ccfg["link_mode"] == "dual":
        cta_note = f"CTA는 2번 사용: 첫 번째는 링크1로 '{ccfg['cta1_text']}' 문구, 두 번째는 링크2로 '{ccfg['cta2_text']}' 문구."
    else:
        cta_note = f"CTA는 2번 모두 같은 링크로 '{ccfg['cta1_text']}' 문구를 사용하세요."

    user_prompt = f"""
주제: {topic}
콘텐츠 유형: {content_key} / 플랫폼: {platform_key}
{link_desc}
CTA 안내: {cta_note}
말투: {tone}
분량: {length}
추가 반영사항: {extra or '없음'}
{f"추가 SEO 규칙 메모(최신 검색 기반, 반드시 반영): {seo_notes}" if seo_notes.strip() else ""}
{research_block}

{pcfg["rules_doc"]}

응답은 아래 마커 형식을 정확히 지켜 작성하세요 (마커 앞뒤 다른 텍스트 금지):
###TITLE###
(SEO 제목, 32자 이내, 핵심 키워드를 앞쪽에 배치)
###META###
(메타 설명, 80자 이내)
###TAGS###
(쉼표로 구분한 태그 5~7개)
###CONTENT###
(완성된 본문 — html이면 jb-post로 시작하는 HTML, text이면 순수 텍스트)
###IMAGES###
([이미지N] 영어 프롬프트 형식으로 한 줄씩, 본문의 자리 표시 번호와 일치)
###END###
"""

    def call_model(model_name, thinking_budget):
        model = genai.GenerativeModel(model_name, system_instruction=system)
        gen_kwargs = {"max_output_tokens": 8192, "temperature": 0.8}
        if thinking_budget is not None:
            gen_kwargs["thinking_config"] = genai.types.ThinkingConfig(thinking_budget=thinking_budget)
        resp = model.generate_content(user_prompt, generation_config=genai.types.GenerationConfig(**gen_kwargs))
        return resp.text

    raw, best = None, None
    for model_name in ("gemini-flash-latest", "gemini-flash-lite-latest"):
        for thinking_budget in (1024, 0, None):
            try:
                candidate = call_model(model_name, thinking_budget)
            except Exception:
                continue
            if not candidate or not candidate.strip():
                continue
            if best is None or len(candidate) > len(best):
                best = candidate
            if "###END###" in candidate:
                raw = candidate
                break
        if raw:
            break
    if not raw:
        if not best:
            raise RuntimeError("모델 응답을 받지 못했습니다. 잠시 후 다시 시도해 주세요.")
        raw = best

    title = extract_between(raw, "###TITLE###", "###META###")
    meta = extract_between(raw, "###META###", "###TAGS###")
    tags = extract_between(raw, "###TAGS###", "###CONTENT###")
    content_end = "###IMAGES###" if "###IMAGES###" in raw else "###END###"
    content = extract_between(raw, "###CONTENT###", content_end)
    if not content:
        content = raw.split("###CONTENT###")[-1]
    content = re.sub(r"```html|```", "", content).strip()

    images_raw = extract_between(raw, "###IMAGES###", "###END###") if "###IMAGES###" in raw else ""
    images = re.findall(r"\[(이미지\d+)\]\s*(.+)", images_raw)

    if ccfg["disclosure"] == "coupang" and DISCLOSURE_TEXT not in content:
        if fmt == "html":
            content = _insert_after_post_open(content, f'<div class="jb-tip"><b>안내</b> {DISCLOSURE_TEXT}</div>')
        else:
            content = DISCLOSURE_TEXT + "\n\n" + content
    if ccfg["disclosure"] == "health" and HEALTH_DISCLAIMER not in content:
        if fmt == "html":
            content = _insert_before_last_close(content, f'<div class="jb-tip"><b>안내</b> {HEALTH_DISCLAIMER}</div>')
        else:
            content = content.rstrip() + f"\n\n{HEALTH_DISCLAIMER}"

    html_repaired = False
    if fmt == "html":
        ad_code = st.session_state.get("adsense_code", "").strip()
        replacement = f'<div class="jb-ad-slot">{ad_code}</div>' if ad_code else ""
        content = content.replace("<!--AD_SLOT-->", replacement)

        pre_open, pre_close = content.count("<div"), content.count("</div>")
        html_repaired = pre_open != pre_close
        try:
            content = str(BeautifulSoup(content, "html.parser"))
        except Exception:
            pass

    return title, meta, tags, content, images, html_repaired


def run_seo_check(content_key, fmt, topic, title, meta, tags, content, images):
    ccfg = CONTENT_TYPES[content_key]
    checks = []
    plain = re.sub(r"<[^>]+>", " ", content)

    kw_count = plain.lower().count(topic.lower()) + title.lower().count(topic.lower())
    checks.append(("키워드 반복", "ok" if 5 <= kw_count <= 12 else ("warn" if kw_count > 0 else "bad"),
                   f"'{topic}' {kw_count}회 등장 (목표 5~7회)"))
    checks.append(("제목 길이/키워드", "ok" if len(title) <= 32 and topic.lower() in title.lower() else "warn",
                   f"{len(title)}자, 키워드 포함 {'✔' if topic.lower() in title.lower() else '✘'}"))
    checks.append(("메타설명 길이", "ok" if 40 <= len(meta) <= 100 else "warn", f"{len(meta)}자 (목표 40~100자)"))
    tag_count = len([t for t in tags.split(",") if t.strip()])
    checks.append(("태그 개수", "ok" if 5 <= tag_count <= 8 else "warn", f"{tag_count}개 (목표 5~7개)"))

    sentences = re.split(r"(?<=[.!?다요])\s+", plain)
    long_ratio = sum(1 for s in sentences if len(s.strip()) > 55) / max(len(sentences), 1)
    checks.append(("모바일 문장 길이", "ok" if long_ratio < 0.25 else "warn", f"55자 초과 문장 비율 {long_ratio:.0%}"))

    if fmt == "html":
        h2_count = content.count("jb-h2")
        checks.append(("소제목 개수", "ok" if 4 <= h2_count <= 7 else "warn", f"jb-h2 {h2_count}개"))
        cta_count = content.count("jb-cta\"")
        checks.append(("CTA 버튼", "ok" if cta_count >= 2 else "warn", f"{cta_count}회 등장 (목표 2회)"))
        checks.append(("Q&A 포함", "ok" if "jb-qa" in content else "warn", "포함" if "jb-qa" in content else "미포함"))
        if content_key == "축제/행사":
            spot_count = content.count("jb-spot-item")
            checks.append(("명소/프로그램 카드", "ok" if spot_count >= 3 else "warn", f"jb-spot-item {spot_count}개"))
        ad_code = st.session_state.get("adsense_code", "").strip()
        if ad_code:
            ad_count = content.count("jb-ad-slot")
            checks.append(("애드센스 삽입", "ok" if ad_count >= 2 else "warn", f"{ad_count}곳 삽입 (목표 3곳)"))
    else:
        link_count = content.count("→")
        checks.append(("링크 자리 표시", "ok" if link_count >= 1 else "warn", f"{link_count}회 등장"))
        checks.append(("FAQ 포함", "ok" if content.count("?") >= 3 else "warn", f"물음표 {content.count('?')}개"))

    if ccfg["disclosure"] == "coupang":
        checks.append(("파트너스 고지 문구", "ok" if DISCLOSURE_TEXT in content else "bad",
                        "포함" if DISCLOSURE_TEXT in content else "누락 — 자동 보정됨"))
    if ccfg["disclosure"] == "health":
        checks.append(("건강정보 고지 문구", "ok" if HEALTH_DISCLAIMER in content else "bad",
                        "포함" if HEALTH_DISCLAIMER in content else "누락 — 자동 보정됨"))

    slot_count = len(re.findall(r"\[이미지\d+\]", content))
    checks.append(("이미지 자리/프롬프트 매칭", "ok" if slot_count > 0 and slot_count == len(images) else "warn",
                   f"본문 자리 {slot_count}개 / 프롬프트 {len(images)}개"))

    char_count = len(re.sub(r"\s+", "", plain))
    checks.append(("본문 글자수", "ok" if char_count >= 1400 else "warn",
                   f"공백 제외 약 {char_count}자 (SEO 상 3,000자 이상 권장)"))
    return checks


# ────────────────────────────────────────────────────────────────
# UI
# ────────────────────────────────────────────────────────────────
st.title("📝 포스트팩토리 — SEO 블로그 자동작성")
st.caption("플랫폼(티스토리 HTML / 네이버 텍스트) × 유형(지원금·축제·건강정보·쿠팡파트너스·일반)을 조합해 생성합니다")

client = get_client()
if client is None:
    with st.sidebar:
        st.warning("GOOGLE_API_KEY가 설정되지 않았습니다.")
        st.session_state["manual_api_key"] = st.text_input("Google AI API 키 (테스트용)", type="password")
        st.caption(
            "무료 발급: aistudio.google.com/app/apikey (신용카드 불필요)\n\n"
            "배포 시에는 Streamlit Cloud의 Secrets에 GOOGLE_API_KEY를 등록하세요."
        )
    client = get_client()

search_ready = client is not None

with st.sidebar:
    st.caption("🆓 Gemini Flash 무료 티어 사용 중 (모델은 Google이 자동으로 최신 버전 유지)")
    st.divider()

    st.subheader("📢 애드센스 자동 삽입 (티스토리 전용, 선택)")
    default_ad = st.secrets.get("ADSENSE_CODE", "") if hasattr(st, "secrets") else ""
    st.session_state["adsense_code"] = st.text_area(
        "애드센스 광고 코드 (ins/script 태그 그대로 붙여넣기)",
        value=st.session_state.get("adsense_code", default_ad), height=100,
        help="비워두면 광고 없이 생성됩니다. 티스토리(HTML) 글에만 적용되며, "
             "도입부 CTA 직후·본문 중간·Q&A 직전 3곳에 자동으로 들어갑니다.",
    )
    st.caption("⚠️ 미리보기(iframe)에서는 실제 광고가 안 뜰 수 있어요 — 정상입니다.")

    st.divider()
    st.subheader("🔎 웹 리서치 / 공식 링크 자동 검색")
    if search_ready:
        st.success("사용 가능 — Gemini 내장 구글 검색 연동. 별도 등록 불필요.")
    else:
        st.caption("GOOGLE_API_KEY만 설정되면 자동으로 사용 가능합니다.")

    st.divider()
    st.subheader("📊 데이터랩 키워드 검증 (선택)")
    if datalab_ready():
        st.success("사용 가능 — 추천 키워드를 실제 검색량 기준으로 검증합니다.")
    else:
        st.caption(
            "인기 키워드 추천에 실제 검색량 검증을 더하려면 네이버 오픈 API를 등록하세요 (무료):\n\n"
            "1. developers.naver.com → Application 등록 → '검색어트렌드(데이터랩)' API 선택\n"
            "2. 발급된 Client ID / Client Secret 확인\n"
            "3. Streamlit Secrets에 NAVER_CLIENT_ID, NAVER_CLIENT_SECRET 등록\n\n"
            "⚠️ 참고: 데이터랩은 '지금 뜨는 검색어'를 새로 찾아주는 게 아니라, "
            "이미 뽑힌 후보 키워드들의 상대적 검색량을 비교해주는 용도입니다 "
            "(네이버는 2021년에 실시간 급상승검색어 서비스 자체를 종료했어요)."
        )

    st.divider()
    st.subheader("📈 검색 규칙(SEO) 새로고침 (선택)")
    platform_hint_sb = st.selectbox("검색 대상 플랫폼", ["네이버", "티스토리"], key="seo_refresh_platform")
    if st.button("🔎 최신 SEO 규칙 검색", disabled=not search_ready):
        with st.spinner("검색 중…"):
            text, sources = research_seo_rules(platform_hint_sb)
        if text:
            st.session_state["seo_refresh_text"] = text
            st.session_state["seo_refresh_sources"] = sources
        else:
            st.warning("검색 결과를 가져오지 못했습니다.")
    if st.session_state.get("seo_refresh_text"):
        st.markdown(st.session_state["seo_refresh_text"])
        for r in st.session_state.get("seo_refresh_sources", []):
            st.caption(f"출처: [{r['title']}]({r['link']})")
    st.session_state["seo_extra_notes"] = st.text_area(
        "검색 규칙 메모 (생성 시 자동 반영)",
        value=st.session_state.get("seo_extra_notes", ""), height=100,
        placeholder="예: 2026년부터 제목은 28자 이내 권장 등",
    )

    st.divider()
    st.subheader("📦 공용 스킨 CSS (티스토리 전용)")
    st.caption("티스토리 관리자 → 꾸미기 → 스킨 편집 → CSS 탭 맨 아래에 한 번만 붙여넣으세요.")
    st.code(SKIN_CSS.strip(), language="css")

col_nav, col_main = st.columns([0.85, 3], gap="large")

with col_nav:
    st.markdown("**✏️ 글쓰기 메뉴**")
    platform_key = st.radio("플랫폼", list(PLATFORMS.keys()), key="nav_platform")
    st.divider()
    content_key = st.radio("유형", list(CONTENT_TYPES.keys()), key="nav_content")

pcfg = PLATFORMS[platform_key]
ccfg = CONTENT_TYPES[content_key]

with col_main:
    st.markdown(f"### {platform_key} · {content_key}")

    with st.expander("🔥 요즘 인기 키워드 추천받기", expanded=True):
        dl_ready = datalab_ready()
        st.caption(
            "실시간 구글 검색 기반으로 후보를 뽑고" + (
                ", 네이버 데이터랩으로 상대 검색량까지 검증해서 전체 순위를 매깁니다."
                if dl_ready else
                " 순서대로 보여드려요. (네이버 데이터랩을 연결하면 실제 검색량 기준 전체 순위를 매길 수 있어요 — 사이드바 참고)"
            ) + " 계정 로그인이 필요한 크리에이터 어드바이저의 '내 통계'는 가져올 수 없지만, "
            "그 화면을 캡처/복사해서 아래 '추가 반영사항'에 붙여넣으면 그대로 반영됩니다."
        )
        all_categories = st.checkbox("전체 유형별로 나눠서 보기 (지원금·축제·건강정보·쿠팡파트너스·일반)", value=False)

        def _render_ranked(kws, key_prefix):
            """추천 키워드 목록을 데이터랩 검증 결과와 함께 순위 버튼으로 렌더링."""
            if not kws:
                st.caption("추천 결과가 없습니다.")
                return
            if dl_ready:
                with st.spinner("데이터랩으로 검색량 검증하는 중…"):
                    scored, unscored = verify_with_datalab_all(kws)
                for i, item in enumerate(scored, 1):
                    if st.button(f"{i}위 · {item['keyword']} (지수 {item['score']})", key=f"{key_prefix}_s_{i}"):
                        st.session_state["topic_input"] = item["keyword"]
                        st.rerun()
                if unscored:
                    st.caption("검증 실패(데이터랩 응답 없음) — 그래도 추천 후보입니다")
                    cols = st.columns(2)
                    for i, kw in enumerate(unscored):
                        if cols[i % 2].button(kw, key=f"{key_prefix}_u_{i}"):
                            st.session_state["topic_input"] = kw
                            st.rerun()
            else:
                cols = st.columns(2)
                for i, kw in enumerate(kws):
                    if cols[i % 2].button(kw, key=f"{key_prefix}_{i}"):
                        st.session_state["topic_input"] = kw
                        st.rerun()

        if st.button("🔎 추천 + 검증", disabled=not search_ready, key="trend_btn"):
            if all_categories:
                grouped = {}
                with st.spinner("전체 유형별로 인기 키워드를 검색하는 중… (시간이 좀 걸려요)"):
                    for i, ck in enumerate(CONTENT_TYPES.keys()):
                        if i > 0:
                            time.sleep(2)  # 무료 티어 속도 제한 방지
                        kws, _ = suggest_trending_topics(ck, count=5)
                        grouped[ck] = kws
                st.session_state["trend_grouped"] = grouped
                st.session_state["trend_suggestions"] = None
            else:
                with st.spinner("인기 키워드를 검색하는 중…"):
                    kws, _ = suggest_trending_topics(content_key, count=8)
                st.session_state["trend_suggestions"] = kws
                st.session_state["trend_grouped"] = None

        if st.session_state.get("trend_grouped"):
            for ck, kws in st.session_state["trend_grouped"].items():
                st.markdown(f"**{ck}**")
                _render_ranked(kws, key_prefix=f"grp_{ck}")
        elif st.session_state.get("trend_suggestions"):
            _render_ranked(st.session_state["trend_suggestions"], key_prefix="single")

    topic = st.text_input(ccfg["topic_label"], placeholder=ccfg["topic_placeholder"], key="topic_input")

    if ccfg["link_mode"] == "dual":
        link1_in = st.text_input(ccfg["link1_label"], placeholder="https://... (비우면 자동 검색)")
        link2_in = st.text_input(ccfg["link2_label"], placeholder="https://... (비우면 자동 검색)")
    else:
        link1_in = st.text_input(ccfg["link1_label"], placeholder="https://...")
        link2_in = link1_in
        if content_key == "쿠팡파트너스":
            st.caption("⚠️ 쿠팡 파트너스 이용약관상 링크는 실제 발급받은 파트너스 링크만 사용해야 합니다.")

    c1, c2 = st.columns(2)
    with c1:
        tone_key = st.selectbox("말투", list(TONE_OPTIONS.keys()))
    with c2:
        length_key = st.selectbox("분량", list(LENGTH_OPTIONS.keys()), index=1)
    extra = st.text_area("추가 반영사항 (선택)", placeholder="예: 청주 지역 특화, 2026년 기준, 크리에이터 어드바이저 통계 붙여넣기 등")

    use_research = st.checkbox(
        "🔎 웹 리서치 사용 (실제 검색 결과 기반으로 작성)", value=search_ready,
        help="Gemini의 구글 검색 연동으로 주제를 실제 검색해서 그 결과를 근거로 글을 씁니다.",
        disabled=not search_ready,
    )

    generate = st.button("✨ 블로그 글 생성하기", type="primary", use_container_width=True)
    st.divider()

    if generate:
        if not topic.strip():
            st.error("주제를 입력해 주세요.")
        elif client is None:
            st.error("Google API 키가 필요합니다.")
        else:
            fmt = pcfg["format"]
            resolved_link1, resolved_link2 = link1_in.strip(), link2_in.strip()
            auto_used = []
            if fmt == "html":
                if not resolved_link1:
                    found, _ = search_official_link(topic.strip())
                    resolved_link1 = found if found else "[링크 입력]"
                    if found:
                        auto_used.append(("링크1", found))
                if ccfg["link_mode"] == "dual" and not resolved_link2:
                    found, _ = search_official_link(topic.strip())
                    resolved_link2 = found if found else "[링크 입력]"
                    if found:
                        auto_used.append(("링크2", found))
            resolved_link1 = resolved_link1 or "[링크 입력]"
            resolved_link2 = resolved_link2 or resolved_link1

            research_block, research_sources = "", []
            if use_research and search_ready:
                with st.spinner("주제를 웹에서 리서치하는 중…"):
                    research_block, research_sources = research_topic(topic.strip())
                    if not research_block:
                        st.warning("리서치 검색에 실패해서 리서치 없이 진행합니다.")

            with st.spinner("SEO 구조에 맞춰 글을 작성하는 중…"):
                try:
                    title, meta, tags, content, images, html_repaired = generate_post(
                        content_key, platform_key, topic.strip(), resolved_link1, resolved_link2,
                        tone_key, length_key, extra.strip(), research_block,
                        st.session_state.get("seo_extra_notes", ""),
                    )
                    checks = run_seo_check(content_key, fmt, topic.strip(), title, meta, tags, content, images)
                    st.session_state["result"] = {
                        "title": title, "meta": meta, "tags": tags,
                        "content": content, "format": fmt, "mode": f"{platform_key} · {content_key}",
                        "checks": checks, "auto_used": auto_used, "images": images,
                        "html_repaired": html_repaired, "research_sources": research_sources,
                    }
                except Exception as e:
                    st.error(f"생성 중 오류가 발생했습니다: {e}")

    result = st.session_state.get("result")
    if result:
        if result.get("auto_used"):
            for label, url in result["auto_used"]:
                st.info(f"🔎 {label}를 자동 검색으로 채웠습니다: {url} (필요하면 직접 수정하세요)")
        if result.get("html_repaired"):
            st.warning("⚠️ 원본 HTML에서 태그가 안 닫힌 부분이 감지되어 자동으로 정리했습니다.")
        if result.get("research_sources"):
            with st.expander(f"🔎 리서치 출처 {len(result['research_sources'])}건"):
                for r in result["research_sources"]:
                    st.markdown(f"- [{r['title']}]({r['link']})")

        st.markdown(f"**[{result['mode']}] 제목** {result['title']}")
        st.markdown(f"**메타설명** {result['meta']}")

        ICONS = {"ok": "✅", "warn": "⚠️", "bad": "❌"}
        checks = result.get("checks", [])
        bad_count = sum(1 for _, s, _ in checks if s == "bad")
        warn_count = sum(1 for _, s, _ in checks if s == "warn")
        summary = "모든 항목 통과" if not bad_count and not warn_count else f"주의 {warn_count}건 · 문제 {bad_count}건"
        tag_chips = " ".join(f"`#{t.strip()}`" for t in result["tags"].split(",") if t.strip())
        st.markdown(f"**태그** {tag_chips}")
        with st.expander(f"🔍 SEO 체크리스트 — {summary}", expanded=bool(bad_count)):
            for label, status, detail in checks:
                st.markdown(f"{ICONS.get(status, '•')} **{label}** — {detail}")

        if result["format"] == "html":
            tab_preview, tab_code = st.tabs(["미리보기", "HTML 코드"])
            with tab_preview:
                components.html(f"<style>{SKIN_CSS}</style>{result['content']}", height=1000, scrolling=True)
            with tab_code:
                st.code(result["content"], language="html")
        else:
            st.caption("네이버 스마트에디터에 그대로 붙여넣을 수 있는 순수 텍스트입니다.")
            st.code(result["content"], language=None)

        if result.get("images"):
            st.subheader("🖼️ 이미지 생성 프롬프트")
            st.caption("아래 프롬프트를 Google Flow 등에 붙여넣고, 마음에 드는 이미지를 골라 본문의 같은 번호 자리에 넣어주세요.")
            for label, prompt in result["images"]:
                st.code(f"[{label}] {prompt}", language=None)
    else:
        st.info("왼쪽에서 플랫폼·유형·주제를 입력하고 생성 버튼을 누르면 결과가 여기에 표시됩니다.")


# ────────────────────────────────────────────────────────────────
# 배치 생성
# ────────────────────────────────────────────────────────────────
st.divider()
with st.expander("📅 여러 주제 한 번에 생성 (배치)"):
    st.caption("왼쪽에서 선택한 플랫폼·유형·말투·분량·리서치 설정을 그대로 사용해 순차 생성합니다.")
    batch_topics_raw = st.text_area(
        "주제 목록 (한 줄에 하나씩, 최대 30개)", height=180,
        placeholder="예)\n혈압 낮추는 법\n겨울철 난방비 절약 방법\n무선 청소기 추천\n...",
        key="batch_topics_raw",
    )
    run_batch = st.button("🚀 전체 순차 생성", key="run_batch_button")

    if run_batch:
        topics = [t.strip() for t in batch_topics_raw.splitlines() if t.strip()][:30]
        if not topics:
            st.error("주제를 한 줄에 하나씩 입력해 주세요.")
        elif client is None:
            st.error("Google API 키가 필요합니다.")
        else:
            fmt = pcfg["format"]
            batch_results = []
            progress = st.progress(0.0, text="시작합니다…")
            for i, t in enumerate(topics):
                progress.progress((i) / len(topics), text=f"({i+1}/{len(topics)}) {t} 생성 중…")
                if i > 0:
                    time.sleep(4)  # 무료 티어 분당 요청 제한 방지용 대기
                try:
                    b_link1 = link1_in.strip()
                    b_link2 = link2_in.strip() if ccfg["link_mode"] == "dual" else b_link1
                    if fmt == "html":
                        if not b_link1:
                            found, _ = search_official_link(t)
                            b_link1 = found or "[링크 입력]"
                        if ccfg["link_mode"] == "dual" and not b_link2:
                            found, _ = search_official_link(t)
                            b_link2 = found or "[링크 입력]"
                    b_link1 = b_link1 or "[링크 입력]"
                    b_link2 = b_link2 or b_link1

                    b_research_block, b_sources = "", []
                    if use_research and search_ready:
                        b_research_block, b_sources = research_topic(t)

                    title, meta, tags, content, images, html_repaired = generate_post(
                        content_key, platform_key, t, b_link1, b_link2, tone_key, length_key, extra.strip(),
                        b_research_block, st.session_state.get("seo_extra_notes", ""),
                    )
                    batch_results.append({
                        "topic": t, "title": title, "meta": meta, "tags": tags,
                        "content": content, "format": fmt, "mode": f"{platform_key} · {content_key}",
                        "images": images, "sources": b_sources, "error": None,
                    })
                except Exception as e:
                    batch_results.append({"topic": t, "error": str(e)})
            progress.progress(1.0, text="완료!")
            st.session_state["batch_results"] = batch_results

    batch_results = st.session_state.get("batch_results")
    if batch_results:
        ok_count = sum(1 for r in batch_results if not r.get("error"))
        st.success(f"{ok_count}/{len(batch_results)}건 생성 완료")

        import io
        import zipfile

        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for idx, r in enumerate(batch_results, 1):
                if r.get("error"):
                    continue
                ext = "html" if r["format"] == "html" else "txt"
                safe_name = re.sub(r"[\\/:*?\"<>|]", "_", r["title"] or r["topic"])[:60]
                zf.writestr(f"{idx:02d}_{safe_name}.{ext}", r["content"])
        st.download_button("⬇️ 전체 결과 ZIP으로 다운로드", data=zip_buf.getvalue(),
                            file_name="batch_posts.zip", mime="application/zip")

        for idx, r in enumerate(batch_results, 1):
            if r.get("error"):
                st.error(f"{idx}. {r['topic']} — 생성 실패: {r['error']}")
                continue
            with st.expander(f"{idx}. [{r['mode']}] {r['title']}"):
                st.markdown(f"**메타설명** {r['meta']}")
                tag_chips = " ".join(f"`#{tg.strip()}`" for tg in r["tags"].split(",") if tg.strip())
                st.markdown(f"**태그** {tag_chips}")
                if r.get("sources"):
                    st.caption(f"🔎 리서치 출처 {len(r['sources'])}건 반영됨")
                st.code(r["content"], language="html" if r["format"] == "html" else None)
                ext = "html" if r["format"] == "html" else "txt"
                st.download_button("이 글만 다운로드", data=r["content"],
                                    file_name=f"{r['title'] or r['topic']}.{ext}", key=f"dl_{idx}")
