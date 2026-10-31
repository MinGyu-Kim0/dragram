"""내 일본어: 내 문장들에 나온 용법을 모아 본다(FR-M10, ADR 0002, #313).

본인 user_id의 문장만 모으고 LLM을 부르지 않는다. 문장 화면(사이드 패널, 내 기록의 분석 보기)과
같은 규칙을 쓴다: 활성 정정을 적용하고, 반려된 용법·패턴은 빼고, 미검수면 pending이다(ADR 0003).
바깥 패턴이 show_parts를 끈 구성 문법은 문장 화면처럼 뺀다(#65). 해석 갈림은 주 용법으로 세고,
미확정은 넣지 않는다. 용법 단위로 묶으므로 회화체로 나와도 원형 패턴 이름으로 보인다.
"""

from collections import defaultdict

from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from accounts.views import SessionUser
from analysis.models import MatchCorrection, SpanMatch, UserSentence
from analysis.my_sentences import _login_required
from analysis.presenter import _SHOWN_STATES, _review_status, _with_parts, apply_correction


@api_view(["GET"])
@authentication_classes([SessionUser])
@permission_classes([])
def my_grammar(request):
    """내 문장에 나온 용법. 나온 문장이 많은 순이고, 문장은 최근 분석 순이다."""
    _login_required(request)
    # shortcut: 페이지 없이 전부 모은다. 기록이 많아져 느려지면 집계를 DB로 옮기거나 나눈다.
    sentences = UserSentence.objects.filter(user=request.user).order_by("-last_analyzed_at", "-id")
    by_analysis = defaultdict(list)
    for sentence in sentences:
        by_analysis[sentence.analysis_id].append(sentence)
    corrections = defaultdict(dict)
    for c in MatchCorrection.objects.filter(
        analysis_id__in=by_analysis, status=MatchCorrection.Status.ACTIVE
    ).select_related("before_usage", "after_usage__pattern"):
        corrections[c.analysis_id][(c.start_offset, c.end_offset)] = c
    spans = (
        SpanMatch.objects.filter(analysis_id__in=by_analysis, state__in=_SHOWN_STATES)
        .select_related("pattern__variant_of", "usage__pattern")
        .order_by("analysis_id", "start_offset", "end_offset", "id")
    )

    # 분석마다 문장 화면에 보일 항목: (항목, 매칭된 패턴의 show_parts). _with_parts가 숨길 구성
    # 문법을 가른다. 미확정은 바깥이 될 수 없어 숨김에 영향이 없으므로 처음부터 넣지 않는다.
    entries = defaultdict(list)
    for span in spans:
        if not apply_correction(span, corrections[span.analysis_id]):
            continue
        review_status = _review_status(span.pattern, span.usage)
        if span.state == SpanMatch.State.UNRESOLVED or review_status is None:
            continue
        item = {
            "start": span.start_offset,
            "end": span.end_offset,
            "state": span.state,
            "span": span,
            "review_status": review_status,
        }
        entries[span.analysis_id].append((item, span.pattern.show_parts))

    by_usage = {}
    for analysis_id, items in entries.items():
        for top in _with_parts(items):
            for item in (top, *top.get("parts", [])):
                usage = item["span"].usage
                seen = by_usage.setdefault(
                    usage.pk, {"usage": usage, "statuses": set(), "sentence_ids": set()}
                )
                seen["statuses"].add(item["review_status"])
                seen["sentence_ids"].update(s.pk for s in by_analysis[analysis_id])

    ordered = sorted(by_usage.values(), key=lambda u: (-len(u["sentence_ids"]), u["usage"].pk))
    return Response(
        {
            "usages": [
                {
                    "usage_id": u["usage"].pk,
                    "pattern_name": u["usage"].pattern.name,
                    "name": u["usage"].name,
                    "explanation_ko": u["usage"].explanation_ko,
                    "korean_equivalent": u["usage"].korean_equivalent,
                    "korean_equivalent_review_status": u["usage"].korean_equivalent_status,
                    "review_status": "pending" if "pending" in u["statuses"] else "approved",
                    "sentences": [
                        {"id": s.pk, "text": s.original_text}
                        for s in sentences
                        if s.pk in u["sentence_ids"]
                    ],
                }
                for u in ordered
            ]
        }
    )
