"""평가 결과에서 매칭 정정(FR-A21, #221).

공용 분석에는 원문이 없어 admin에서 문장을 고를 수 없다. 평가 문장은 관리자가 쓴 문장이고 그
결과도 같은 공용 캐시에 남으므로, 평가 항목에서 정정한다. 적용은 분석할 때 한다(Sentence).
"""

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from analysis.evaluation import flat_items
from analysis.models import GrammarUsage, MatchCorrection, ReviewStatus, SentenceAnalysis
from analysis.normalize import analysis_text
from analysis.presenter import Presenter
from analysis.review import Refused
from analysis.sentence import Sentence


def target(item):
    """평가 항목이 가리키는 지금 분석의 (분석 행, 구간 행). 분석 요청과 같은 정규화로 찾고,
    저장 구간을 항목과 같은 원문 UTF-16 위치·패턴으로 맞춘다.
    """
    original = item.result.text
    text, origins = analysis_text(original)
    sentence = Sentence(text)
    row = sentence.existing
    if row is None or row.status != SentenceAnalysis.Status.COMPLETE:
        raise Refused("분석이 없거나 처리 중이라 정정할 수 없습니다")
    # 해제한 구간도 찾아야 다시 평가하지 않고 다른 용법으로 고칠 수 있다(PR #320 리뷰).
    grammar, spans = Presenter(sentence, original, origins).grammar_spans(row, released=True)
    for entry in flat_items(grammar):
        span = spans[id(entry)]
        if (entry["start"], entry["end"], span.pattern_id) == (
            item.start,
            item.end,
            item.pattern_ref,
        ):
            return row, span
    raise Refused("지금 분석에 그 구간이 없습니다(다시 평가해 주세요)")


def choices(span):
    """정정 후 용법으로 고를 수 있는 용법. 그 구간 패턴(회화체면 연결된 원형)의 반려되지 않은
    용법이다. 분석할 때 그 구간의 후보와 같다.
    """
    owner = span.pattern.variant_of or span.pattern
    return GrammarUsage.objects.filter(pattern=owner).exclude(status=ReviewStatus.REJECTED)


@transaction.atomic
def correct(item, after_usage_id, user):
    """평가 항목의 구간을 정정한다. after_usage_id가 None이면 매칭 해제다.

    같은 자리·패턴을 다시 정정하면 같은 행을 고친다(정정 전 용법은 처음 정정한 때의 값). 분석을
    stale로 만들고 세대 번호를 올려, 다음 요청이 다시 분석하고 그사이 분석은 저장하지 않게 한다.
    """
    row, span = target(item)
    after = None
    if after_usage_id is not None:
        after = choices(span).filter(pk=after_usage_id).first()
        if after is None:
            raise Refused("이 구간에 고를 수 없는 용법입니다")
    # 분석 저장과 같이 분석 행을 잠근 뒤 쓴다.
    locked = SentenceAnalysis.objects.select_for_update(no_key=True).get(pk=row.pk)
    if locked.status != SentenceAnalysis.Status.COMPLETE:
        raise Refused("분석이 없거나 처리 중이라 정정할 수 없습니다")
    correction, _ = MatchCorrection.objects.update_or_create(
        analysis=locked,
        start_offset=span.start_offset,
        end_offset=span.end_offset,
        pattern_id=span.pattern_id,
        defaults={
            "after_usage": after,
            "status": MatchCorrection.Status.ACTIVE,
            "corrected_by": user,
        },
        create_defaults={
            "before_usage_id": span.usage_id,
            "after_usage": after,
            "corrected_by": user,
        },
    )
    _make_stale(locked.pk)
    return correction


def _make_stale(analysis_id):
    SentenceAnalysis.objects.filter(pk=analysis_id).update(
        is_stale=True, generation=F("generation") + 1
    )


@transaction.atomic
def set_status(correction, status):
    """정정을 멈추거나(suspended) 다시 켠다(active, #223). 바뀌었으면 분석을 stale로 만들고 세대
    번호를 올려 다음 분석부터 반영한다. 이미 그 상태면 아무것도 바꾸지 않고 False다.
    """
    SentenceAnalysis.objects.select_for_update(no_key=True).get(pk=correction.analysis_id)
    changed = (
        MatchCorrection.objects.filter(pk=correction.pk)
        .exclude(status=status)
        .update(status=status, updated_at=timezone.now())
    )
    if changed:
        _make_stale(correction.analysis_id)
    return bool(changed)
