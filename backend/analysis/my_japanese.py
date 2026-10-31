"""내 일본어: 내 문장들에서 만난 용법을 모아 본다(FR-M10, ADR 0002, #313).

본인 user_id의 문장만 모으고 LLM을 부르지 않는다. 사이드 패널과 같은 규칙을 쓴다: 활성 정정을
적용하고, 반려된 용법·패턴은 빼고, 미검수면 pending이다(ADR 0003). 해석 갈림은 주 용법으로 세고,
미확정은 넣지 않는다.
"""

from collections import defaultdict

from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from accounts.views import SessionUser
from analysis.models import MatchCorrection, SpanMatch, UserSentence
from analysis.my_sentences import _login_required
from analysis.presenter import _SHOWN_STATES, _review_status, corrected


@api_view(["GET"])
@authentication_classes([SessionUser])
@permission_classes([])
def my_grammar(request):
    """내 문장에 나온 용법. 만난 문장이 많은 순이고, 문장은 최근 분석 순이다."""
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
    spans = SpanMatch.objects.filter(
        analysis_id__in=by_analysis, state__in=_SHOWN_STATES
    ).select_related("pattern__variant_of", "usage__pattern")

    met = {}
    for span in spans:
        if not corrected(span, corrections[span.analysis_id]):
            continue
        review_status = _review_status(span.pattern, span.usage)
        if span.state == SpanMatch.State.UNRESOLVED or review_status is None:
            continue
        usage, statuses, ids = met.setdefault(span.usage_id, (span.usage, set(), set()))
        statuses.add(review_status)
        ids.update(s.pk for s in by_analysis[span.analysis_id])

    usages = sorted(met.values(), key=lambda m: (-len(m[2]), m[0].pk))
    return Response(
        {
            "usages": [
                {
                    "usage_id": usage.pk,
                    "pattern_name": usage.pattern.name,
                    "name": usage.name,
                    "explanation_ko": usage.explanation_ko,
                    "korean_equivalent": usage.korean_equivalent,
                    "korean_equivalent_review_status": usage.korean_equivalent_status,
                    "review_status": "pending" if "pending" in statuses else "approved",
                    "sentences": [
                        {"id": s.pk, "text": s.original_text} for s in sentences if s.pk in ids
                    ],
                }
                for usage, statuses, ids in usages
            ]
        }
    )
