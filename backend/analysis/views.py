import hashlib
import re
import unicodedata

from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from analysis import llm
from analysis.models import SentenceAnalysis
from analysis.morphology import morphemes
from analysis.normalize import (
    NORMALIZE_VERSION,
    analysis_text,
    has_all_placeholders,
    has_only_known_placeholders,
    key_pieces,
    number_ends,
    restore_numbers,
)
from analysis.positions import key_offsets, to_analysis, to_key, to_original, utf16_offsets
from analysis.ruby import ruby_pieces
from errors import AnalysisError, BusinessError


def _numbers_before_particle(text, morphs):
    """원문에서 바로 뒤에 조사(助詞)가 오는 숫자의 자리표시자 번호."""
    particle_starts = {m.begin for m in morphs if m.pos == "助詞"}
    return {n for n, end in enumerate(number_ends(text), start=1) if end in particle_starts}


def _is_text(value):
    if not isinstance(value, str) or value.strip() == "":
        return False
    try:
        # JSON에는 단독 서로게이트(\ud800 등)가 들어올 수 있지만 UTF-8로는 인코딩할 수 없다.
        value.encode()
    except UnicodeEncodeError:
        return False
    return True


def _is_token_id(value, token_count):
    # bool은 int의 하위 타입이라 따로 거른다.
    return type(value) is int and 0 <= value < token_count


def _validate_grammar(grammar, numbers, token_count):
    """LLM이 고른 문법 항목을 검증한다. 하나라도 틀리면 None."""
    if not isinstance(grammar, list):
        return None
    items = []
    for item in grammar:
        if not isinstance(item, dict):
            return None
        start, end = item.get("start_token_id"), item.get("end_token_id")
        if not (_is_token_id(start, token_count) and _is_token_id(end, token_count)):
            return None
        if start > end:
            return None
        name, explanation = item.get("name"), item.get("explanation_ko")
        if not (_is_text(name) and _is_text(explanation)):
            return None
        # 이름·설명도 응답할 때 숫자를 되돌리므로 없는 번호의 자리표시자는 받지 않는다.
        if not all(has_only_known_placeholders(t, numbers) for t in (name, explanation)):
            return None
        items.append(
            {"start_token": start, "end_token": end, "name": name, "explanation_ko": explanation}
        )
    return items


_WORD_TEXTS = ("lemma", "reading", "meaning_ko")

# 읽기는 가나(장음 ー, 반복 부호 포함)로만 쓰고 가나가 한 글자는 있어야 한다. 가타카나 블록의
# 문장부호(・ ゠)는 가나가 아니다. 숫자와 겹치는 토큰은 단어에서 빠지므로 자리표시자도 받지
# 않는다. 외래어(사전에 없는 새 말 포함)는 가타카나 그대로 두므로 히라가나로 바꾸지 않는다.
_KANA = "\u3041-\u3096\u309d\u309e\u30a1-\u30fa\u30fd\u30fe\u31f0-\u31ff"
_READING = re.compile(rf"[{_KANA}\u30fc]*[{_KANA}][{_KANA}\u30fc]*")


def _validate_words(words, numbers, token_count, is_vocabulary):
    """LLM이 고른 단어 항목을 검증한다. 하나라도 틀리면 None.

    학습할 단어가 아닌 토큰(is_vocabulary가 거짓)을 고른 항목은 나머지를 보지 않고 뺀다.
    지침을 어긴 단어 하나 때문에 번역·문법까지 버리면 같은 문장마다 LLM을 다시 불러야 해서다.
    """
    if not isinstance(words, list):
        return None
    items = []
    seen = set()
    for item in words:
        if not isinstance(item, dict) or not _is_token_id(item.get("token_id"), token_count):
            return None
        # 같은 토큰을 다시 고른 항목은 뺀다(토큰마다 이 문장에서의 뜻은 하나다).
        if not is_vocabulary(item["token_id"]) or item["token_id"] in seen:
            continue
        seen.add(item["token_id"])
        texts = [item.get(field) for field in _WORD_TEXTS]
        if not all(_is_text(text) for text in texts):
            return None
        if not _READING.fullmatch(item["reading"]):
            return None
        # 사전형·뜻도 응답할 때 숫자를 되돌리므로 없는 번호의 자리표시자는 받지 않는다.
        if not all(has_only_known_placeholders(text, numbers) for text in texts):
            return None
        items.append({"token": item["token_id"], **{field: item[field] for field in _WORD_TEXTS}})
    return items


def _validate(result, numbers, token_count, is_vocabulary):
    """LLM 응답에서 쓸 값만 꺼낸다. 형식이 틀리거나 자리표시자가 맞지 않으면 ANALYSIS:FAILED."""
    if not isinstance(result, dict) or not _is_text(result.get("translation_ko")):
        raise BusinessError(AnalysisError.FAILED, "LLM 응답 검증 실패: 번역")
    # 자리표시자가 맞지 않는 번역은 숫자가 틀렸을 수 있어 보여주지도 저장하지도 않는다.
    if not has_all_placeholders(result["translation_ko"], numbers):
        raise BusinessError(AnalysisError.FAILED, "LLM 응답 검증 실패: 번역 자리표시자")
    grammar = _validate_grammar(result.get("grammar"), numbers, token_count)
    if grammar is None:
        raise BusinessError(AnalysisError.FAILED, "LLM 응답 검증 실패: 문법")
    words = _validate_words(result.get("words"), numbers, token_count, is_vocabulary)
    if words is None:
        raise BusinessError(AnalysisError.FAILED, "LLM 응답 검증 실패: 단어")
    return {"translation_ko": result["translation_ko"], "grammar": grammar, "words": words}


def _stored_grammar(grammar, morphs, offsets):
    """토큰 ID로 고른 문법 항목을 키 텍스트 구간으로 바꿔 저장할 모양으로 만든다."""
    stored = []
    for item in grammar:
        begin = morphs[item["start_token"]].begin
        end = morphs[item["end_token"]].end
        key_start, key_end = to_key(offsets, begin, end)
        stored.append(
            {
                "start": key_start,
                "end": key_end,
                "name": item["name"],
                "explanation_ko": item["explanation_ko"],
            }
        )
    return stored


# 학습할 단어가 아닌 토큰의 품사(문장부호, 공백, 문법 쪽에서 다루는 조사·조동사)
_NON_WORD_POS = {"補助記号", "空白", "助詞", "助動詞"}


def _stored_words(words, morphs, offsets):
    """토큰 ID로 고른 단어 항목을 키 텍스트 구간으로 바꿔 저장할 모양으로 만든다."""
    stored = []
    for item in words:
        morph = morphs[item["token"]]
        begin, end = morph.begin, morph.end
        key_start, key_end = to_key(offsets, begin, end)
        stored.append(
            {"start": key_start, "end": key_end, **{field: item[field] for field in _WORD_TEXTS}}
        )
    return stored


def _quotes_whole_sentence(texts, key_text, token_count):
    """LLM이 쓴 글(문법 이름·설명, 단어 사전형·읽기·뜻)이 문장 전체(키 텍스트)를 인용했는가.

    기호·공백을 뺀 형태소가 하나뿐인 문장(です, 行く！ 등)이면 그 토큰을 인용하는 것과 같고,
    단어 하나는 사전 표제어 수준의 공용 정보라 허용한다. 형태소가 여럿이면 구간이 문장
    전체여도 원문을 옮긴 것이다. token_count는 기호·공백을 뺀 형태소 수다.
    """
    if token_count <= 1:
        return False
    # 형태소 사이에 공백·가운데점·보이지 않는 문자를 넣어 인용해도(私・は・学生) 원문을
    # 옮긴 것이므로, 양쪽에서 문장부호·기호·공백·형식 문자를 지우고 비교한다.
    compact_key = _letters(key_text)
    if not compact_key:
        # 기호만으로 된 문장은 지우면 비어서 모든 글에 "포함"된다. 인용으로 보지 않는다.
        return False
    return any(compact_key in _letters(text) for text in texts)


def _letters(text):
    """문장부호·기호·공백·형식 문자(유니코드 P·S·Z·C 분류)를 지운다."""
    return "".join(ch for ch in text if unicodedata.category(ch)[0] not in "PSZC")


def _grammar_response(stored, offsets, origins, utf16, restore):
    """저장된 문법 항목의 키 텍스트 구간을 이 요청 원문의 UTF-16 위치로 바꾼다.

    같은 분석을 표기가 다른 원문(앞 공백, 괄호, 숫자 자릿수 등)이 함께 쓰므로, 요청마다
    그 원문 기준으로 다시 계산한다. 이름·설명의 자리표시자도 번역처럼 이 원문의 숫자로
    되돌린다(restore).
    """
    grammar = []
    for item in stored:
        start, end = to_original(origins, utf16, *to_analysis(offsets, item["start"], item["end"]))
        grammar.append(
            {
                "start": start,
                "end": end,
                "name": restore(item["name"]),
                "explanation_ko": restore(item["explanation_ko"]),
                # 이 단위의 문법은 모두 LLM이 썼고 아직 아무도 검수하지 않았다.
                "review_status": "pending",
            }
        )
    return grammar


def _words_response(stored, offsets, origins, utf16, restore):
    """저장된 단어 항목을 이 요청 원문 기준으로 바꾼다(_grammar_response와 같은 방식)."""
    words = []
    for item in stored:
        start, end = to_original(origins, utf16, *to_analysis(offsets, item["start"], item["end"]))
        words.append(
            {
                "start": start,
                "end": end,
                **{field: restore(item[field]) for field in _WORD_TEXTS},
                # JMdict 없이 LLM이 만든 뜻이라 검수 전이다(#10).
                "review_status": "pending",
            }
        )
    return words


def _ruby_response(pieces, origins, utf16):
    """분석 텍스트 기준 루비 조각을 이 요청 원문의 UTF-16 위치로 바꾼다."""
    ruby = []
    for start, end, reading in pieces:
        start, end = to_original(origins, utf16, start, end)
        ruby.append({"start": start, "end": end, "reading": reading})
    return ruby


# 테스트 단계라 로그인 없이 연다. 로그인 없는 사용을 정식으로 허용한다는 결정은 아니다(#10).
@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
def analyze(request):
    sentence = request.data.get("text") if isinstance(request.data, dict) else None
    if not _is_text(sentence):
        raise BusinessError(AnalysisError.TEXT_REQUIRED, "분석할 문장이 없음")

    text_to_analyze, origins = analysis_text(sentence)
    if not text_to_analyze:
        raise BusinessError(AnalysisError.TEXT_REQUIRED, "정규화 후 빈 문장")
    pieces, numbers = key_pieces(text_to_analyze)
    key_text = "".join(pieces)
    sentence_hash = hashlib.sha256(key_text.encode()).hexdigest()

    # 형태소 분석은 숫자가 그대로인 분석 텍스트로 한다. 숫자 뒤 조사 교정에 쓰므로 캐시를
    # 재사용할 때도 한다. 원문은 로그에 남기지 않는다.
    morphs = morphemes(text_to_analyze)
    particle_numbers = _numbers_before_particle(text_to_analyze, morphs)

    offsets = key_offsets(pieces)
    utf16 = utf16_offsets(sentence)

    def restore(text):
        return restore_numbers(text, numbers, particle_numbers)

    # 루비는 SudachiPy 읽기라 LLM·캐시와 상관없이 요청마다 이 원문 기준으로 계산한다.
    ruby = _ruby_response(ruby_pieces(text_to_analyze, morphs), origins, utf16)

    def respond(saved):
        return Response(
            {
                "translation_ko": restore(saved.translation_ko),
                "grammar": _grammar_response(
                    saved.draft_analysis["grammar"], offsets, origins, utf16, restore
                ),
                "words": _words_response(
                    saved.draft_analysis["words"], offsets, origins, utf16, restore
                ),
                "ruby": ruby,
            }
        )

    # 임시 분석을 받기 전에 저장된 행(draft_analysis가 NULL)은 다시 분석한다.
    cached = SentenceAnalysis.objects.filter(
        sentence_hash=sentence_hash, draft_analysis__isnull=False
    ).first()
    if cached:
        return respond(cached)

    # LLM에는 키 텍스트 기준 표층형을 보내 원문 숫자가 가지 않게 한다.
    tokens = [{"id": i, "surface": "".join(pieces[m.begin : m.end])} for i, m in enumerate(morphs)]
    result = llm.get_client().analyze(key_text, tokens)

    def is_vocabulary(token):
        # 숫자는 학습할 단어가 아니고, 숫자열과 겹치는 토큰(X12의 X1, 2)은 LLM이 사전형에
        # 숫자를 지어내면 숫자만 다른 문장에 잘못 재사용된다. 숫자열은 자리표시자 조각과
        # 빈 조각(뒤쪽 숫자)으로 이뤄진다.
        m = morphs[token]
        overlaps_number = any(piece == "" or "⟨N" in piece for piece in pieces[m.begin : m.end])
        return m.pos not in _NON_WORD_POS and not overlaps_number

    validated = _validate(result, numbers, len(morphs), is_vocabulary)
    draft = {
        "grammar": _stored_grammar(validated["grammar"], morphs, offsets),
        "words": _stored_words(validated["words"], morphs, offsets),
    }
    llm_texts = [
        item[field] for item in validated["grammar"] for field in ("name", "explanation_ko")
    ]
    llm_texts += [item[field] for item in validated["words"] for field in _WORD_TEXTS]
    content_tokens = sum(m.pos not in {"補助記号", "空白"} for m in morphs)
    if _quotes_whole_sentence(llm_texts, key_text, content_tokens):
        # 이 글들은 공용 테이블에 들어가므로 원문을 통째로 옮긴 결과는 저장하지 않는다.
        raise BusinessError(AnalysisError.FAILED, "LLM이 쓴 글이 문장 전체를 인용함")

    # 같은 문장이 동시에 저장되면 먼저 들어간 행을 쓴다.
    saved, created = SentenceAnalysis.objects.get_or_create(
        sentence_hash=sentence_hash,
        defaults={
            "normalize_version": NORMALIZE_VERSION,
            "normalized_length": len(key_text),
            "status": SentenceAnalysis.Status.COMPLETE,
            "translation_ko": validated["translation_ko"],
            "draft_analysis": draft,
        },
    )
    if not created and saved.draft_analysis is None:
        # 임시 분석을 받기 전에 저장된 행이면 이번 결과로 채운다. 그사이 다른 요청이 먼저
        # 채웠으면 그 값을 쓴다(NULL일 때만 갱신).
        SentenceAnalysis.objects.filter(pk=saved.pk, draft_analysis__isnull=True).update(
            translation_ko=validated["translation_ko"],
            draft_analysis=draft,
            updated_at=timezone.now(),
        )
        saved.refresh_from_db()
    return respond(saved)
