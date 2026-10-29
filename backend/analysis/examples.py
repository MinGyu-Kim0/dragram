"""새 예문 검사와 다시 쓰기."""

from django.conf import settings

from analysis import patterns
from analysis.answers import _letters, _quotes_whole_sentence, _validate_rewrites
from analysis.models import (
    GrammarUsage,
)
from analysis.normalize import (
    analysis_text,
    has_only_known_placeholders,
    key_pieces,
)
from analysis.positions import key_offsets, to_key
from analysis.span_rows import _usage_owner
from analysis.words import fixed_morphemes
from errors import AnalysisError, BusinessError
from errors.handler import log_business_error


def _copy_units(key, fixed_spans, aligned):
    """복사 검사에 쓰는 키 텍스트의 (단위, 길이에 세는가)들. 기호·공백은 지운다.

    fixed_spans는 패턴에서 고정한 토큰의 (패턴 안 순서, 키 텍스트 start, end) 목록이고, 그
    글자는 길이에 세지 않는다. aligned면 고정 토큰 하나를 그 순서를 표시로 한 단위로 묶어,
    표기가 달라도(くる·来る, 활용형) 같은 자리의 고정 토큰끼리 같게 한다. 아니면 글자 그대로
    둔다.
    """
    marks = {}
    for seq, start, end in fixed_spans:
        for i in range(start, end):
            marks.setdefault(i, (seq, start))
    units = []
    for i, ch in enumerate(key):
        if i in marks and aligned:
            if marks[i] != marks.get(i - 1):
                units.append((marks[i][:1], False))
        elif _letters(ch):
            units.append((ch, i not in marks))
    return units


def _copies_part(example, original):
    """예문이 원문의 연속된 일부를 기준 길이 이상 그대로 썼는가. 둘 다 _copy_units의 단위다.

    예문에는 그 문법이 들어갈 수밖에 없으므로 원문의 고정 토큰은 길이에 세지 않는다. 다만
    고정 토큰을 사이에 두고 앞뒤를 이어서 베낀 것은 한 번의 복사로 센다. 구간 안의 아무거나
    토큰은 원문 글자라 센다.
    """
    length = settings.EXAMPLE_COPY_LENGTH
    example = [unit for unit, _ in example]
    # counted[j]: 원문 앞 단위와 예문 j번째 단위에서 끝나는 공통 연속 구간의 센 글자 수
    # (공통이 아니면 None)
    counted = [None] * len(example)
    for unit, counts in original:
        previous = [None, *counted[:-1]]
        counted = [
            (previous[j] or 0) + counts if example[j] == unit else None for j in range(len(example))
        ]
        if any(c is not None and c >= length for c in counted):
            return True
    return False


# 새 예문 검사 결과. 원문을 베껴 거부된 예문만 다시 쓰게 한다.
_EXAMPLE_OK, _EXAMPLE_COPIED, _EXAMPLE_UNUSABLE = "ok", "copied", "unusable"


def _fixed_runs(conditions, key_range):
    """이어진 고정 토큰 묶음마다 (묶음 순서, 키 텍스트 start, end). key_range(i, j)는 패턴 안
    i~j번째 토큰의 키 텍스트 구간이다. 아무거나 토큰은 묶음을 끊고, 그 글자는 복사 길이에 센다.
    """
    runs, first = [], None
    for i, c in enumerate([*conditions, patterns.ANY]):
        if c != patterns.ANY and first is None:
            first = i
        elif c == patterns.ANY and first is not None:
            runs.append((len(runs), *key_range(first, i - 1)))
            first = None
    return runs


def _example_verdict(example, conditions, key_text, content_tokens, fixed_spans, by_runs=False):
    """새 예문을 검사한다. 패턴에 걸리지 않는 등 원문과 상관없이 쓸 수 없으면 unusable, 그렇지
    않은데 원문을 베꼈으면 copied(다시 쓰게 함), 쓸 수 있으면 ok다.

    by_runs면 고정 토큰을 토큰마다가 아니라 이어진 묶음마다(_fixed_runs) 맞춘다. 연결된 회화체
    구간의 새 용법 예문은 원형 조건으로 검사하는데, 회화체(ちゃう)와 원형(て·しまう)은 토큰 수가
    달라 토큰끼리 맞추면 문법 앞뒤로 이어 베낀 것이 끊겨 보인다. 그때 fixed_spans도 원문의 회화체
    고정 토큰 묶음이다(#63).
    """
    if len(example) > patterns.EXAMPLE_MAX_LENGTH or not has_only_known_placeholders(example, ()):
        return _EXAMPLE_UNUSABLE
    text, _ = analysis_text(example)
    if not text:
        return _EXAMPLE_UNUSABLE
    pieces, _ = key_pieces(text)
    example_key = "".join(pieces)
    # 원문 키 텍스트와 같거나 전체를 포함하면 베낀 것이다(문장 인용과 같은 비교). 형태소가
    # 하나뿐인 원문은 포함만 허용하고, 원문 그대로인 예문은 형태소 수와 상관없이 거부한다.
    # 다시 써도 원문을 베끼지 않는 것만 고쳐지므로, 쓸 수 없는 예문은 베낀 것보다 먼저 가린다.
    morphs = fixed_morphemes(text)
    starts = patterns.match_starts(conditions, morphs)
    if not starts:
        return _EXAMPLE_UNUSABLE
    if _letters(example_key) == _letters(key_text):
        return _EXAMPLE_COPIED
    if _quotes_whole_sentence([example_key], key_text, content_tokens):
        return _EXAMPLE_COPIED
    offsets = key_offsets(pieces)
    if by_runs:
        example_fixed = [
            run
            for start in starts
            for run in _fixed_runs(
                conditions,
                lambda i, j, start=start: to_key(
                    offsets, morphs[start + i].begin, morphs[start + j].end
                ),
            )
        ]
    else:
        example_fixed = [
            (seq, *to_key(offsets, morphs[start + seq].begin, morphs[start + seq].end))
            for start in starts
            for seq, c in enumerate(conditions)
            if c != patterns.ANY
        ]
    # 예문의 패턴 매치와 맞춰 보고, 매치 밖에서 원문 고정 토큰을 같은 글자로 베낀 것도 본다.
    for aligned in (True, False):
        if _copies_part(
            _copy_units(example_key, example_fixed if aligned else [], aligned),
            _copy_units(key_text, fixed_spans, aligned),
        ):
            return _EXAMPLE_COPIED
    return _EXAMPLE_OK


def _check_examples(validated, client, key_text, content_tokens, key_span, discarded):
    """새 패턴·새 용법의 예문을 저장 전에 검사해, 쓸 수 있는 예문을 "checked_example"에
    둔다(없으면 None). validated 안의 제안·새 용법을 제자리에서 고친다.

    원문을 베껴 거부된 예문은 한 번에 묶어 한 번만 다시 쓰게 하고, 다시 쓴 예문도 같은
    검사를 통과해야 쓴다. 같은 용법에 이미 통과한 예문이 있으면 다시 쓰지 않는다(그 예문을
    쓴다). 다시 쓰기가 실패하면 예문 없이 둔다. 보조 호출 하나 때문에 분석 전체를 버리지
    않는다. 이미 검사한 예문은 다시 보지 않는다(다시 묻기 뒤 재시도). LLM 호출이라 저장
    트랜잭션 밖에서 부른다.

    discarded()가 참이면 이 결과가 버려질 것이라 다시 쓰기를 보내지 않는다. 첫 분석은 작업을
    시작한 뒤 세대 번호가 올랐는지(#98), 재매칭은 이번 새 구간이 이미 저장됐는지 본다(#41).
    """

    def fixed_spans(start_token, conditions):
        """패턴에서 고정한 토큰의 (패턴 안 순서, 키 텍스트 start, end)들"""
        return [
            (i, *key_span(start_token + i, start_token + i))
            for i, c in enumerate(conditions)
            if c != patterns.ANY
        ]

    # (예문을 담은 제안·새 용법, 같은 용법인지 가르는 열쇠, 패턴 이름, 형태소 조건,
    #  고정 토큰 구간, 매치 전체를 한 단위로 맞추는가)
    targets = [
        (
            p,
            (patterns.morpheme_key(p["conditions"]), p["usage_name"]),
            p["pattern_name"],
            p["conditions"],
            fixed_spans(p["tokens"][0][0], p["conditions"]),
            False,
        )
        for p in validated["new_patterns"]
        if "checked_example" not in p and p["existing"] is None and p["conditions"] is not None
    ]
    # 새 용법은 그 용법이 들어갈 패턴(연결된 회화체면 원형)의 조건에 걸려야 한다. 연결된 회화체
    # 구간은 원문과 예문의 고정 토큰을 이어진 묶음마다 맞춘다(#63).
    for span, (_, _, n) in zip(validated["span_list"], validated["spans"], strict=True):
        if n is None or "checked_example" in n:
            continue
        owner = _usage_owner(span.pattern)
        linked = owner is not span.pattern
        targets.append(
            (
                n,
                (owner.id, n["usage_name"]),
                owner.name,
                patterns.conditions_of(owner),
                _fixed_runs(
                    span.conditions,
                    lambda i, j, start=span.start_token: key_span(start + i, start + j),
                )
                if linked
                else fixed_spans(span.start_token, span.conditions),
                linked,
            )
        )
    # 기존 패턴에 이미 있는 이름의 새 용법은 더하지 않으므로(patterns.add_usage) 검사하지
    # 않는다. 다시 쓰기를 보내도 버려진다.
    taken = set(
        GrammarUsage.objects.filter(
            pattern__in=[_usage_owner(span.pattern) for span in validated["span_list"]]
        ).values_list("pattern_id", "name")
    )
    copied, usable = [], set()
    for holder, usage_key, pattern_name, conditions, fixed, whole in targets:
        if usage_key in taken:
            holder["checked_example"] = None
            continue
        verdict = _example_verdict(
            holder["example_ja"], conditions, key_text, content_tokens, fixed, whole
        )
        holder["checked_example"] = holder["example_ja"] if verdict == _EXAMPLE_OK else None
        if verdict == _EXAMPLE_OK:
            usable.add(usage_key)
        elif verdict == _EXAMPLE_COPIED:
            copied.append((holder, usage_key, pattern_name, conditions, fixed, whole))
    copied = [item for item in copied if item[1] not in usable]
    if not copied or discarded():
        return
    try:
        result = client.rewrite_examples(
            key_text,
            [
                {
                    "example_id": example_id,
                    "pattern_name": pattern_name,
                    "usage_name": holder["usage_name"],
                    "explanation_ko": holder["explanation_ko"],
                    "rejected_example": holder["example_ja"],
                }
                for example_id, (holder, _, pattern_name, *_) in enumerate(copied)
            ],
        )
        rewritten = _validate_rewrites(result, len(copied))
        if rewritten is None:
            raise BusinessError(AnalysisError.FAILED, "LLM 응답 검증 실패: 예문 다시 쓰기")
    except BusinessError as e:
        log_business_error(e)
        return
    for (holder, _, _, conditions, fixed, whole), text in zip(copied, rewritten, strict=True):
        verdict = _example_verdict(text, conditions, key_text, content_tokens, fixed, whole)
        if verdict == _EXAMPLE_OK:
            holder["checked_example"] = text
