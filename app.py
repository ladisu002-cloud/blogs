import os
import re
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

# 애드센스 광고 자동 삽입 위치 규칙 (html 카테고리 공통)
AD_SLOT_RULES = (
    "<!--AD_SLOT--> 마커를 정확히 3번, 다른 텍스트로 바꾸지 말고 그대로 출력하세요: "
    "① 도입부 첫 CTA 버튼 바로 다음 ② 두 번째 jb-h2 섹션이 끝난 직후 ③ jb-qa(Q&A) 시작 바로 전."
)

# 이미지 생성 프롬프트 규칙 (모든 카테고리 공통 — 실제 이미지는 생성하지 않고, 자리 표시 + 영어 프롬프트만 제공)
IMAGE_PROMPT_RULES = (
    "소제목(섹션) 하나당 이미지 1개씩, 보통 4~6개 정도가 적당합니다. 이미지가 들어가면 좋을 자리마다 "
    "본문에 [이미지1], [이미지2]처럼 번호가 매겨진 자리 표시를 넣고, 그 번호와 정확히 일치하는 영어 이미지 생성 "
    "프롬프트를 본문과 별도로 ###IMAGES### 섹션에 한 줄씩 작성하세요 (예: [이미지1] A cozy realistic photo of ...). "
    "프롬프트는 사실적인 사진 스타일로 피사체·구도·조명·분위기를 구체적으로 묘사하세요."
)

# 건강정보 등 링크가 없을 수도 있는 카테고리를 위한 동적 CTA 안내는 generate_post에서 상황에 따라 주입한다.

MODE_CONFIG = {
    "지원금/제도": {
        "format": "html",
        "topic_label": "지원금/제도 이름",
        "topic_placeholder": "예: 청년월세지원",
        "link_mode": "dual",
        "link1_label": "버튼1 링크 · 신청하러 가기 (비우면 자동 검색)",
        "link2_label": "버튼2 링크 · 자격 조회하기 (비우면 자동 검색)",
        "system": (
            "당신은 20년차 SEO 전문가이자 정부 지원금 정보 콘텐츠 작가입니다. "
            "독자는 해당 지원금 대상 여부가 궁금해서 검색해 들어온 사람입니다. "
            "손실 회피 문구로 도입부를 시작해 관심을 끌고, "
            "신청 방법 → 대상 조건 → 지급 금액/유효기간 → Q&A 순으로 구성하세요. "
            "실제 존재하는 제도라면 사실 관계를 왜곡하지 말고, "
            "확실하지 않은 수치는 '지자체·연도별로 다를 수 있음'으로 처리하세요. "
            "CTA 버튼은 정확히 2번 사용합니다: 첫 번째는 도입부 직후, 링크1로 '신청하러 가기👆' 텍스트. "
            "두 번째는 Q&A 섹션 바로 다음, 링크2로 '자격 조회하기👆' 텍스트. "
            + QUALITY_RULES + " " + AD_SLOT_RULES + " " + IMAGE_PROMPT_RULES
        ),
    },
    "축제/행사": {
        "format": "html",
        "topic_label": "축제/행사 이름",
        "topic_placeholder": "예: 직지문화축제",
        "link_mode": "single",
        "link1_label": "공식 홈페이지 링크 (비우면 자동 검색)",
        "system": (
            "당신은 20년차 SEO 전문가이자 지역 축제 여행 콘텐츠 작가입니다. "
            "독자는 이 축제에 가볼지 결정하려는 사람입니다. "
            "'핵심 명소'와 '주요 프로그램'은 절대 긴 문단으로 나열하지 말고, "
            "반드시 jb-spot-list 카드 목록(아이콘 + 짧은 이름 + 1~2문장 설명)으로 3~4개씩 작성하세요. "
            "그 다음 기본 정보(기간/장소/교통/주차) → 방문 꿀팁 → 함께 즐기면 좋은 다른 행사 순으로 구성하세요. "
            "CTA 버튼은 정확히 2번, 같은 링크로 '공식 홈페이지 바로가기👆' 텍스트를 사용하세요. "
            + QUALITY_RULES + " " + AD_SLOT_RULES + " " + IMAGE_PROMPT_RULES
        ),
    },
    "일반 블로그": {
        "format": "html",
        "topic_label": "주제/키워드",
        "topic_placeholder": "예: 겨울철 난방비 절약 방법",
        "link_mode": "single",
        "link1_label": "참고 링크 (선택)",
        "system": (
            "당신은 20년차 SEO 전문가이자 정보성 블로그 작가입니다. "
            "검색 의도에 정확히 부합하는 실용적인 정보를 다루세요. "
            "핵심 항목이 여러 개 나열되는 부분(예: 방법 목록, 추천 목록)은 긴 문단 대신 "
            "jb-spot-list 카드 목록으로 정리하면 가독성이 좋습니다(해당될 때만). "
            "왜 중요한지(도입) → 핵심 정보/방법을 섹션별로 → 실수하기 쉬운 점(팁 박스) → Q&A 순으로 구성하세요. "
            "CTA 버튼은 정확히 2번, 같은 링크로 '자세히 보기👆' 텍스트를 사용하세요. "
            + QUALITY_RULES + " " + AD_SLOT_RULES + " " + IMAGE_PROMPT_RULES
        ),
    },
    "쿠팡파트너스": {
        "format": "text",
        "topic_label": "상품/카테고리명",
        "topic_placeholder": "예: 무선 청소기 추천",
        "link_mode": "single",
        "link1_label": "쿠팡 파트너스 링크",
        "system": (
            "당신은 20년차 SEO 전문가이자 쿠팡 파트너스 제휴 마케팅 콘텐츠 작가입니다. "
            "네이버 블로그에 그대로 붙여넣을 순수 텍스트(HTML 태그 없음)로 작성합니다. "
            "구조는 서론(공감 유도 + 파트너스 링크 자리 1회) → 상품별 분석(장단점을 솔직하게, "
            "스펙 비교는 '항목: 설명' 형태의 줄글로) → 결론(핵심 요약 + 링크 자리 1회) → "
            "자주 묻는 질문 3~5개 → 해시태그 순으로 구성하세요. "
            "장점만 나열하지 말고 단점이나 이런 분께는 안 맞을 수 있다는 점도 최소 1곳 솔직하게 언급하세요. "
            "글 맨 앞에는 반드시 '본 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 "
            "제공받습니다.'라는 문구를 그대로 포함하세요. " + QUALITY_RULES + " " + IMAGE_PROMPT_RULES
        ),
    },
    "건강정보": {
        "format": "html",
        "topic_label": "건강 주제/키워드",
        "topic_placeholder": "예: 혈압 낮추는 법",
        "link_mode": "single",
        "link1_label": "참고 링크 (선택 — 없으면 CTA 버튼 없이 작성)",
        "system": (
            "당신은 20년차 SEO 전문가이자 건강 정보 콘텐츠 작가입니다. "
            "독자는 실생활에서 바로 실천할 수 있는 건강 관리법이 궁금해서 검색해 들어온 사람입니다. "
            "흔한 오해나 궁금증으로 도입부를 시작하고, 원인/배경 → 실천 방법(단계별 또는 리스트, "
            "jb-spot-list 카드 활용 가능) → 주의사항 → Q&A 순으로 구성하세요. "
            "특정 의약품명이나 복용량, 개별 진단/치료를 지시하는 문장은 절대 쓰지 마세요. "
            "운동·식습관·수면 같은 일반적인 생활습관 정보만 다루고, '~에 도움이 된다고 알려져 있습니다', "
            "'전문가들은 ~을 권장합니다'처럼 출처를 특정하지 않는 일반론으로 서술하세요. "
            "실존 여부가 불확실한 특정 연구·논문·저널명을 지어내 인용하지 마세요. "
            "글 맨 끝에는 반드시 '이 글은 일반적인 건강 정보 제공을 목적으로 하며, 개인의 의학적 진단이나 "
            "치료를 대체하지 않습니다. 증상이 있다면 반드시 전문의와 상담하세요.'라는 문구를 그대로 포함하세요. "
            + QUALITY_RULES + " " + AD_SLOT_RULES + " " + IMAGE_PROMPT_RULES
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
  : 명소/프로그램/추천항목 등 나열형 정보를 카드 리스트로 보여줄 때 사용 (3~4개 항목)
- <div class="jb-tip"><b>라벨</b> 설명글</div> : 꿀팁/주의사항 박스 (2~3개)
- <div class="jb-table-wrap"><table class="jb-table">...</table></div> : 비교/조건표 (선택)
- <div class="jb-qa"><div class="jb-qa-item"><div class="jb-qa-q">Q. 질문</div><div class="jb-qa-a">답변</div></div>...</div> : Q&A, 2~3문항
- <div class="jb-divider">· · ·</div> : 섹션 구분선 (선택)
- <div class="jb-img-slot">🖼️ [이미지N] 이 자리에 이미지를 삽입하세요</div>
  : 이미지가 들어갈 자리 표시 (번호는 실제 이미지 순서와 일치시킬 것)
- <span class="jb-highlight">강조 텍스트</span> : 본문 강조 inline span
- 일반 문단은 <p>텍스트</p>

작성 규칙:
- 본문 분량 목표에 맞춰 충분히 작성하고, 마지막에 반드시 ###END### 까지 도달할 것 (중간에 끊지 말 것)
- 모든 태그를 빠짐없이 닫을 것
- 코드펜스나 설명 문구 없이, 지정된 마커 형식으로만 응답할 것
"""

TEXT_RULES_DOC = """
작성 형식 (네이버 블로그용 순수 텍스트):
- HTML 태그, 마크다운 기호(#, *, ``` 등)를 절대 사용하지 말 것
- 소제목은 줄 앞에 이모지 1개 + 짧은 문구로 표시 (예: "✅ 핵심 스펙 비교")
- 표가 필요하면 "항목: 설명" 형태로 한 줄씩 나열
- 문단 사이는 빈 줄 하나로 구분
- 이미지가 들어갈 자리는 줄 단독으로 "[이미지1]"처럼 표시
- 링크를 넣을 자리는 반드시 아래 형식 그대로 표시:
  🛒 [상품명] 최저가 확인하기 → LINK
- 본문 분량 목표에 맞춰 충분히 작성하고, 마지막에 반드시 ###END### 까지 도달할 것 (중간에 끊지 말 것)
- 코드펜스나 설명 문구 없이, 지정된 마커 형식으로만 응답할 것
"""

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


def search_official_link(query):
    """Google Programmable Search(Custom Search JSON API)로 공식 페이지를 자동 검색.
    GOOGLE_CSE_KEY, GOOGLE_CSE_ID가 설정돼 있지 않으면 (None, 안내메시지)를 반환."""
    cse_key = st.secrets.get("GOOGLE_CSE_KEY", None) or os.environ.get("GOOGLE_CSE_KEY")
    cse_id = st.secrets.get("GOOGLE_CSE_ID", None) or os.environ.get("GOOGLE_CSE_ID")
    if not cse_key or not cse_id:
        return None, "미설정"
    try:
        resp = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"key": cse_key, "cx": cse_id, "q": f"{query} 공식 사이트", "num": 3},
            timeout=8,
        )
        items = resp.json().get("items", [])
        return (items[0]["link"], None) if items else (None, "검색 결과 없음")
    except Exception as e:
        return None, str(e)


def extract_between(text, start_marker, end_marker):
    s = text.find(start_marker)
    if s == -1:
        return ""
    frm = s + len(start_marker)
    e = text.find(end_marker, frm)
    return (text[frm:] if e == -1 else text[frm:e]).strip()


def generate_post(client, mode, topic, link1, link2, tone_key, length_key, extra):
    cfg = MODE_CONFIG[mode]
    tone = TONE_OPTIONS[tone_key]
    length = LENGTH_OPTIONS[length_key]
    rules_doc = SKIN_CLASSES_DOC if cfg["format"] == "html" else TEXT_RULES_DOC

    link_desc = f"링크1: {link1}" if cfg["link_mode"] == "single" else f"링크1(신청): {link1}\n링크2(자격조회): {link2}"
    has_real_link = link1 != "[링크 입력]"
    cta_note = (
        "링크가 준비되어 있으니 시스템 지침대로 CTA 버튼을 사용하세요."
        if has_real_link else
        "이번 글에는 실제 링크가 없으므로 jb-cta-wrap/jb-cta 버튼을 아예 넣지 마세요."
    )

    user_prompt = f"""
주제: {topic}
카테고리: {mode}
{link_desc}
CTA 안내: {cta_note}
말투: {tone}
분량: {length}
추가 반영사항: {extra or '없음'}

{rules_doc}

응답은 아래 마커 형식을 정확히 지켜 작성하세요 (마커 앞뒤 다른 텍스트 금지):
###TITLE###
(SEO 제목, 32자 이내, 핵심 키워드를 앞쪽에 배치)
###META###
(메타 설명, 80자 이내)
###TAGS###
(쉼표로 구분한 태그 5~7개)
###CONTENT###
(완성된 본문 — html 카테고리는 jb-post로 시작하는 HTML, text 카테고리는 순수 텍스트)
###IMAGES###
([이미지N] 영어 프롬프트 형식으로 한 줄씩, 본문의 자리 표시 번호와 일치)
###END###
"""

    def call_model(model_name, thinking_budget):
        model = client.GenerativeModel(model_name, system_instruction=cfg["system"])
        gen_kwargs = {"max_output_tokens": 8192, "temperature": 0.8}
        if thinking_budget is not None:
            # 최신 Gemini 모델은 기본적으로 '생각(thinking)' 토큰을 먼저 쓴다.
            # 완전히 0으로 끄면 다중 조건 준수(키워드 배치·구조·분량)의 품질이 떨어질 수 있어
            # 소량만 남겨두고, 그래도 모자라면 0으로, 그래도 안 되면 필드 자체를 빼고 재시도한다.
            gen_kwargs["thinking_config"] = genai.types.ThinkingConfig(thinking_budget=thinking_budget)
        resp = model.generate_content(
            user_prompt, generation_config=genai.types.GenerationConfig(**gen_kwargs)
        )
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
            if "###END###" in candidate:  # 마커까지 도달했는지로 '완결' 여부를 실제 확인
                raw = candidate
                break
        if raw:
            break
    if not raw:
        if not best:
            raise RuntimeError("모델 응답을 받지 못했습니다. 잠시 후 다시 시도해 주세요.")
        raw = best  # 완결 마커는 없지만 그나마 가장 긴 응답으로 대체 (아래에서 안전하게 파싱)

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

    if mode == "쿠팡파트너스" and DISCLOSURE_TEXT not in content:
        content = DISCLOSURE_TEXT + "\n\n" + content
    if mode == "건강정보" and HEALTH_DISCLAIMER not in content:
        content += f'<div class="jb-tip"><b>안내</b> {HEALTH_DISCLAIMER}</div>'

    # 애드센스 광고 자동 삽입 (html 카테고리만 해당)
    html_repaired = False
    if cfg["format"] == "html":
        ad_code = st.session_state.get("adsense_code", "").strip()
        replacement = f'<div class="jb-ad-slot">{ad_code}</div>' if ad_code else ""
        content = content.replace("<!--AD_SLOT-->", replacement)

        # 태그 균형 자동 보정: 모델이 가끔 div를 안 닫아서, Tistory가 이걸 다시 파싱할 때
        # 이후 내용(이미지 자리 포함)이 엉뚱한 위치로 밀려나는 문제를 방지한다.
        pre_open, pre_close = content.count("<div"), content.count("</div>")
        html_repaired = pre_open != pre_close
        try:
            content = str(BeautifulSoup(content, "html.parser"))
        except Exception:
            pass

    return title, meta, tags, content, images, html_repaired


def run_seo_check(mode, cfg, topic, title, meta, tags, content, images):
    checks = []
    plain = re.sub(r"<[^>]+>", " ", content)

    kw_count = plain.lower().count(topic.lower()) + title.lower().count(topic.lower())
    checks.append((
        "키워드 반복", "ok" if 5 <= kw_count <= 12 else ("warn" if kw_count > 0 else "bad"),
        f"'{topic}' {kw_count}회 등장 (목표 5~7회, 분량이 길면 다소 더 많아도 무방)",
    ))
    checks.append((
        "제목 길이/키워드", "ok" if len(title) <= 32 and topic.lower() in title.lower() else "warn",
        f"{len(title)}자, 키워드 포함 {'✔' if topic.lower() in title.lower() else '✘'}",
    ))
    checks.append((
        "메타설명 길이", "ok" if 40 <= len(meta) <= 100 else "warn",
        f"{len(meta)}자 (목표 40~100자)",
    ))
    tag_count = len([t for t in tags.split(",") if t.strip()])
    checks.append((
        "태그 개수", "ok" if 5 <= tag_count <= 8 else "warn",
        f"{tag_count}개 (목표 5~7개)",
    ))

    sentences = re.split(r"(?<=[.!?다요])\s+", plain)
    long_ratio = sum(1 for s in sentences if len(s.strip()) > 55) / max(len(sentences), 1)
    checks.append((
        "모바일 문장 길이", "ok" if long_ratio < 0.25 else "warn",
        f"55자 초과 문장 비율 {long_ratio:.0%}",
    ))

    if cfg["format"] == "html":
        h2_count = content.count("jb-h2")
        checks.append(("소제목 개수", "ok" if 4 <= h2_count <= 7 else "warn", f"jb-h2 {h2_count}개"))
        cta_count = content.count("jb-cta\"")
        checks.append(("CTA 버튼", "ok" if cta_count >= 2 else "warn", f"{cta_count}회 등장 (목표 2회)"))
        checks.append(("Q&A 포함", "ok" if "jb-qa" in content else "warn", "포함" if "jb-qa" in content else "미포함"))
        if mode == "축제/행사":
            spot_count = content.count("jb-spot-item")
            checks.append(("명소/프로그램 카드", "ok" if spot_count >= 3 else "warn", f"jb-spot-item {spot_count}개"))
        ad_code = st.session_state.get("adsense_code", "").strip()
        if ad_code:
            ad_count = content.count("jb-ad-slot")
            checks.append(("애드센스 삽입", "ok" if ad_count >= 2 else "warn", f"{ad_count}곳 삽입 (목표 3곳)"))
    else:
        link_count = content.count("→")
        checks.append(("링크 자리 표시", "ok" if link_count >= 2 else "warn", f"{link_count}회 등장 (목표 2회)"))
        checks.append(("FAQ 포함", "ok" if content.count("?") >= 3 else "warn", f"물음표 {content.count('?')}개"))
        if mode == "쿠팡파트너스":
            checks.append(("파트너스 고지 문구", "ok" if DISCLOSURE_TEXT in content else "bad",
                            "포함" if DISCLOSURE_TEXT in content else "누락 — 자동 보정됨"))
        if mode == "건강정보":
            checks.append(("건강정보 고지 문구", "ok" if HEALTH_DISCLAIMER in content else "bad",
                            "포함" if HEALTH_DISCLAIMER in content else "누락 — 자동 보정됨"))

    slot_count = len(re.findall(r"\[이미지\d+\]", content))
    checks.append((
        "이미지 자리/프롬프트 매칭", "ok" if slot_count > 0 and slot_count == len(images) else "warn",
        f"본문 자리 {slot_count}개 / 프롬프트 {len(images)}개",
    ))

    char_count = len(re.sub(r"\s+", "", plain))
    checks.append((
        "본문 글자수", "ok" if char_count >= 1400 else "warn",
        f"공백 제외 약 {char_count}자 (SEO 상 3,000자 이상 권장, '짧게' 선택 시 1,500자 이상)",
    ))

    return checks


# ────────────────────────────────────────────────────────────────
# UI
# ────────────────────────────────────────────────────────────────
st.title("📝 포스트팩토리 — SEO 블로그 자동작성")
st.caption("지원금 · 축제 · 일반 · 건강정보(티스토리 HTML) + 쿠팡파트너스(네이버 텍스트)를 자동 생성합니다")

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

with st.sidebar:
    st.caption("🆓 Gemini Flash 무료 티어 사용 중 (모델은 Google이 자동으로 최신 버전 유지)")
    st.divider()

    st.subheader("📢 애드센스 자동 삽입 (선택)")
    default_ad = st.secrets.get("ADSENSE_CODE", "") if hasattr(st, "secrets") else ""
    st.session_state["adsense_code"] = st.text_area(
        "애드센스 광고 코드 (ins/script 태그 그대로 붙여넣기)",
        value=st.session_state.get("adsense_code", default_ad),
        height=100,
        help="비워두면 광고 없이 생성됩니다. 티스토리(HTML) 카테고리에만 적용되며, "
             "도입부 CTA 직후·본문 중간·Q&A 직전 3곳에 자동으로 들어갑니다.",
    )
    st.caption("⚠️ 미리보기 화면(iframe)에서는 실제 광고가 안 뜰 수 있어요 — 정상입니다. "
               "실제 티스토리에 붙여넣으면 정상 노출됩니다.")

    st.divider()
    st.subheader("🔎 공식 링크 자동 검색 (선택)")
    cse_ready = bool(
        (st.secrets.get("GOOGLE_CSE_KEY", None) or os.environ.get("GOOGLE_CSE_KEY"))
        and (st.secrets.get("GOOGLE_CSE_ID", None) or os.environ.get("GOOGLE_CSE_ID"))
    )
    if cse_ready:
        st.success("자동 검색 사용 가능 — 링크를 비워두면 자동으로 채워집니다.")
    else:
        st.caption(
            "링크 입력칸을 비워도 자동으로 채우려면 Google Custom Search를 등록하세요:\n\n"
            "1. programmablesearchengine.google.com 에서 검색엔진 생성 (전체 웹 검색으로 설정) → 검색엔진 ID 확인\n"
            "2. console.cloud.google.com 에서 'Custom Search API' 활성화 후 API 키 발급 (무료, 하루 100건)\n"
            "3. Streamlit Secrets에 GOOGLE_CSE_ID, GOOGLE_CSE_KEY 등록"
        )

    st.divider()
    st.subheader("📦 공용 스킨 CSS (티스토리 전용)")
    st.caption("지원금·축제·일반 블로그(HTML) 글에만 적용됩니다. 티스토리 관리자 → 꾸미기 → 스킨 편집 → CSS 탭 맨 아래에 한 번만 붙여넣으세요.")
    st.code(SKIN_CSS.strip(), language="css")

col_input, col_output = st.columns([1, 1.6], gap="large")

with col_input:
    mode = st.pills("카테고리", list(MODE_CONFIG.keys()), default=list(MODE_CONFIG.keys())[0])
    if not mode:
        mode = list(MODE_CONFIG.keys())[0]
    cfg = MODE_CONFIG[mode]

    topic = st.text_input(cfg["topic_label"], placeholder=cfg["topic_placeholder"])

    if cfg["link_mode"] == "dual":
        link1_in = st.text_input(cfg["link1_label"], placeholder="https://... (비우면 자동 검색)")
        link2_in = st.text_input(cfg["link2_label"], placeholder="https://... (비우면 자동 검색)")
    else:
        link1_in = st.text_input(cfg["link1_label"], placeholder="https://...")
        link2_in = link1_in
        if mode == "쿠팡파트너스":
            st.caption("⚠️ 쿠팡 파트너스 이용약관상 링크는 실제 발급받은 파트너스 링크만 사용해야 합니다.")

    c1, c2 = st.columns(2)
    with c1:
        tone_key = st.selectbox("말투", list(TONE_OPTIONS.keys()))
    with c2:
        length_key = st.selectbox("분량", list(LENGTH_OPTIONS.keys()), index=1)
    extra = st.text_area("추가 반영사항 (선택)", placeholder="예: 청주 지역 특화, 2026년 기준 등")
    generate = st.button("✨ 블로그 글 생성하기", type="primary", use_container_width=True)

with col_output:
    if generate:
        if not topic.strip():
            st.error("주제를 입력해 주세요.")
        elif client is None:
            st.error("Google API 키가 필요합니다. 왼쪽 사이드바에서 입력하거나 Secrets에 등록하세요.")
        else:
            resolved_link1, resolved_link2 = link1_in.strip(), link2_in.strip()
            auto_used = []
            if cfg["format"] == "html":
                if not resolved_link1:
                    found, err = search_official_link(topic.strip())
                    if found:
                        resolved_link1 = found
                        auto_used.append(("링크1", found))
                    else:
                        resolved_link1 = "[링크 입력]"
                if cfg["link_mode"] == "dual" and not resolved_link2:
                    found, err = search_official_link(topic.strip())
                    if found:
                        resolved_link2 = found
                        auto_used.append(("링크2", found))
                    else:
                        resolved_link2 = "[링크 입력]"
            resolved_link1 = resolved_link1 or "[링크 입력]"
            resolved_link2 = resolved_link2 or resolved_link1

            with st.spinner("SEO 구조에 맞춰 글을 작성하는 중…"):
                try:
                    title, meta, tags, content, images, html_repaired = generate_post(
                        client, mode, topic.strip(), resolved_link1, resolved_link2,
                        tone_key, length_key, extra.strip(),
                    )
                    checks = run_seo_check(mode, cfg, topic.strip(), title, meta, tags, content, images)
                    st.session_state["result"] = {
                        "title": title, "meta": meta, "tags": tags,
                        "content": content, "format": cfg["format"], "mode": mode,
                        "checks": checks, "auto_used": auto_used, "images": images,
                        "html_repaired": html_repaired,
                    }
                except Exception as e:
                    st.error(f"생성 중 오류가 발생했습니다: {e}")

    result = st.session_state.get("result")
    if result:
        if result.get("auto_used"):
            for label, url in result["auto_used"]:
                st.info(f"🔎 {label}를 자동 검색으로 채웠습니다: {url} (필요하면 직접 수정하세요)")
        if result.get("html_repaired"):
            st.warning("⚠️ 원본 HTML에서 태그가 안 닫힌 부분이 감지되어 자동으로 정리했습니다. "
                       "이미지 자리나 구조가 이상해 보이면 다시 생성해보세요.")

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
            st.caption("이 글이 프롬프트 규칙(키워드 배치·구조·문장 길이 등)을 실제로 지켰는지 기계적으로 확인한 결과입니다. "
                       "백링크·블로그 지수·클릭률 같은 검색엔진의 실제 순위 요인은 발행 후에나 확인할 수 있어 여기 포함되지 않습니다.")
            for label, status, detail in checks:
                st.markdown(f"{ICONS.get(status, '•')} **{label}** — {detail}")

        if result["format"] == "html":
            tab_preview, tab_code = st.tabs(["미리보기", "HTML 코드"])
            with tab_preview:
                components.html(
                    f"<style>{SKIN_CSS}</style>{result['content']}",
                    height=1000, scrolling=True,
                )
            with tab_code:
                st.code(result["content"], language="html")
        else:
            st.caption("네이버 블로그 에디터에 그대로 붙여넣을 수 있는 순수 텍스트입니다.")
            st.code(result["content"], language=None)

        if result.get("images"):
            st.subheader("🖼️ 이미지 생성 프롬프트")
            st.caption("아래 프롬프트를 복사해서 Google Flow(또는 다른 이미지 생성 도구)에 붙여넣고, "
                       "마음에 드는 이미지를 골라 본문의 같은 번호 [이미지N] 자리에 넣어주세요.")
            for label, prompt in result["images"]:
                st.code(f"[{label}] {prompt}", language=None)
    else:
        st.info("왼쪽에서 카테고리와 주제를 입력하고 생성 버튼을 누르면 결과가 여기에 표시됩니다.")
