import os
import re
import streamlit as st
import streamlit.components.v1 as components
import google.generativeai as genai

# ────────────────────────────────────────────────────────────────
# 설정
# ────────────────────────────────────────────────────────────────
st.set_page_config(page_title="포스트팩토리 — 티스토리 블로그 자동작성", page_icon="📝", layout="wide")

MODE_CONFIG = {
    "지원금/제도": {
        "topic_label": "지원금/제도 이름",
        "topic_placeholder": "예: 청년월세지원",
        "system": (
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
        "system": (
            "당신은 20년차 SEO 전문가이자 지역 축제 여행 콘텐츠 작가입니다. "
            "독자는 이 축제에 가볼지 결정하려는 사람입니다. "
            "핵심 명소 → 기본 정보(기간/장소/교통/주차) → 방문 꿀팁 → 함께 즐기면 좋은 다른 행사 순으로, "
            "현장감 있고 구체적인 문장으로 구성하세요."
        ),
    },
    "일반 블로그": {
        "topic_label": "주제/키워드",
        "topic_placeholder": "예: 겨울철 난방비 절약 방법",
        "system": (
            "당신은 20년차 SEO 전문가이자 정보성 블로그 작가입니다. "
            "검색 의도에 정확히 부합하는 실용적인 정보를 다루세요. "
            "왜 중요한지(도입) → 핵심 정보/방법을 섹션별로 → 실수하기 쉬운 점(팁 박스) → Q&A 순으로 구성하세요."
        ),
    },
}

SKIN_CLASSES_DOC = """
사용 가능한 스킨 클래스 (이 클래스만 사용해서 HTML을 작성할 것. 새로운 class나 인라인 style은 만들지 말 것):
- <div class="jb-post"> : 전체 글 감싸는 최외곽 wrapper (필수, 1개)
- <div class="jb-hero"><span class="jb-hero-tag">태그</span><div class="jb-hero-title">제목</div><div class="jb-hero-perf"></div><div class="jb-hero-meta">부가정보 · 부가정보</div></div> : 글 맨 위 히어로 배너 (필수, 1개)
- <div class="jb-cta-wrap"><a class="jb-cta" href="LINK">버튼 텍스트👆</a></div> : CTA 버튼 (중간과 마지막에 각 1회, 총 2회)
- <div class="jb-h2">섹션 제목</div> : 섹션 제목, 어울리는 이모지 1개 포함. 3~4개 사용
- <div class="jb-info"><div class="jb-info-row"><div class="jb-info-label">라벨</div><div class="jb-info-val">내용</div></div>...</div> : 기본정보 요약 카드 (선택)
- <div class="jb-tip"><b>라벨</b> 설명글</div> : 꿀팁/주의사항 박스 (2~3개)
- <div class="jb-table-wrap"><table class="jb-table"><tr><th>..</th></tr><tr><td>..</td></tr></table></div> : 비교/조건표 (선택)
- <div class="jb-qa"><div class="jb-qa-item"><div class="jb-qa-q">Q. 질문</div><div class="jb-qa-a">답변</div></div>...</div> : Q&A, 2~3문항
- <div class="jb-divider">· · ·</div> : 섹션 구분선 (선택)
- <span class="jb-highlight">강조 텍스트</span> : 본문 강조 inline span
- 일반 문단은 <p>텍스트</p>

작성 규칙:
- 전체 응답은 900토큰 이내로 끝나야 하므로 섹션은 3~4개로 제한하고 간결하게 쓸 것 (반드시 ###END### 까지 도달)
- 모든 태그를 빠짐없이 닫을 것
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
"""

TONE_OPTIONS = {
    "친근한 존댓말": "친근하고 다정한 존댓말, 어려운 용어를 풀어서 설명",
    "담백한 존댓말": "정보 전달에 집중하는 담백하고 정중한 존댓말",
    "전문적 문어체": "전문적이고 신뢰감 있는 문어체",
}
LENGTH_OPTIONS = {
    "짧게": "핵심 위주로 짧고 간결하게",
    "보통": "보통 분량으로 핵심과 배경 설명 포함",
}


def get_client():
    """Gemini는 무료 티어가 있는 Google AI Studio API 키를 사용합니다.
    https://aistudio.google.com/app/apikey 에서 신용카드 없이 발급 가능."""
    api_key = st.secrets.get("GOOGLE_API_KEY", None) or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        api_key = st.session_state.get("manual_api_key", "")
    if not api_key:
        return None
    genai.configure(api_key=api_key)
    return genai


def extract_between(text, start_marker, end_marker):
    s = text.find(start_marker)
    if s == -1:
        return ""
    frm = s + len(start_marker)
    e = text.find(end_marker, frm)
    return (text[frm:] if e == -1 else text[frm:e]).strip()


def generate_post(client, mode, topic, link, tone_key, length_key, extra):
    cfg = MODE_CONFIG[mode]
    tone = TONE_OPTIONS[tone_key]
    length = LENGTH_OPTIONS[length_key]

    user_prompt = f"""
주제: {topic}
카테고리: {mode}
CTA 링크: {link}
말투: {tone}
분량: {length}
추가 반영사항: {extra or '없음'}

{SKIN_CLASSES_DOC}

응답은 아래 마커 형식을 정확히 지켜 작성하세요 (마커 앞뒤 다른 텍스트 금지):
###TITLE###
(SEO 제목, 32자 이내, 핵심 키워드를 앞쪽에 배치)
###META###
(메타 설명, 80자 이내)
###TAGS###
(쉼표로 구분한 태그 5~7개)
###HTML###
(jb-post로 시작하는 완성된 HTML)
###END###
"""

    model = client.GenerativeModel(
        "gemini-2.5-flash",  # 무료 티어 사용 가능 모델
        system_instruction=cfg["system"],
    )
    resp = model.generate_content(
        user_prompt,
        generation_config=genai.types.GenerationConfig(max_output_tokens=1500, temperature=0.8),
    )
    text = resp.text

    title = extract_between(text, "###TITLE###", "###META###")
    meta = extract_between(text, "###META###", "###TAGS###")
    tags = extract_between(text, "###TAGS###", "###HTML###")
    html = extract_between(text, "###HTML###", "###END###")
    if not html:
        html = text.split("###HTML###")[-1]
    html = re.sub(r"```html|```", "", html).strip()
    return title, meta, tags, html


# ────────────────────────────────────────────────────────────────
# UI
# ────────────────────────────────────────────────────────────────
st.title("📝 포스트팩토리 — 티스토리 블로그 자동작성")
st.caption("지원금 · 축제 · 일반 블로그 글을 하나의 공용 스킨으로 자동 생성합니다")

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
    st.caption("🆓 Gemini 2.5 Flash 무료 티어 사용 중 — 분당 10회, 하루 250회 요청까지 무료")
    st.divider()
    st.subheader("📦 공용 스킨 CSS")
    st.caption("티스토리 관리자 → 꾸미기 → 스킨 편집 → CSS 탭 맨 아래에 한 번만 붙여넣으세요.")
    st.code(SKIN_CSS.strip(), language="css")

col_input, col_output = st.columns([1, 1.6], gap="large")

with col_input:
    mode = st.radio("카테고리", list(MODE_CONFIG.keys()), horizontal=True)
    cfg = MODE_CONFIG[mode]
    topic = st.text_input(cfg["topic_label"], placeholder=cfg["topic_placeholder"])
    link = st.text_input("공식 신청/참고 링크 (선택)", placeholder="https://...")
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
            with st.spinner("SEO 구조에 맞춰 글을 작성하는 중…"):
                try:
                    title, meta, tags, html = generate_post(
                        client, mode, topic.strip(), link.strip() or "[링크 입력]",
                        tone_key, length_key, extra.strip(),
                    )
                    st.session_state["result"] = {"title": title, "meta": meta, "tags": tags, "html": html}
                except Exception as e:
                    st.error(f"생성 중 오류가 발생했습니다: {e}")

    result = st.session_state.get("result")
    if result:
        st.markdown(f"**제목** {result['title']}")
        st.markdown(f"**메타설명** {result['meta']}")
        tag_chips = " ".join(f"`#{t.strip()}`" for t in result["tags"].split(",") if t.strip())
        st.markdown(f"**태그** {tag_chips}")

        tab_preview, tab_code = st.tabs(["미리보기", "HTML 코드"])
        with tab_preview:
            components.html(
                f"<style>{SKIN_CSS}</style>{result['html']}",
                height=900, scrolling=True,
            )
        with tab_code:
            st.code(result["html"], language="html")
    else:
        st.info("왼쪽에서 카테고리와 주제를 입력하고 생성 버튼을 누르면 결과가 여기에 표시됩니다.")
