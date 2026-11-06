"""선점한 분석 행을 이번 결과로 바꾸는 저장."""

from django.db import IntegrityError, transaction

from analysis import patterns
from analysis.models import SentenceAnalysis, SpanMatch
from analysis.span_rows import _basis_changed, _is_place_conflict, span_matches


def _sense_ids(word_spans):
    """word_spans의 뜻 ID를 중복 없이 모은다."""
    return sorted({span["sense_id"] for span in word_spans})


def store(sentence, validated, final):
    """검증한 결과를 공용 캐시에 저장한다. 시작 뒤 세대 번호나 판정 근거가 바뀌어 저장을 되돌렸으면
    참이다. 그사이 다른 요청이 같은 조건의 패턴을 먼저 등록했으면 _PatternTaken을 그대로 올린다.
    """
    stored_words = sentence.word_spans(validated["words"])
    with transaction.atomic():
        outdated = _save_once(sentence, validated, stored_words, final)
        if outdated:
            transaction.set_rollback(True)
    return outdated


def _save_once(sentence, validated, stored_words, final):
    """선점한 분석 행을 이번 결과로 통째로 바꾸고 완료로 둔다. 시작 뒤 세대 번호나 판정 근거가
    바뀌었으면 참이다(호출하는 쪽이 되돌린다). 호출하는 쪽이 트랜잭션을 연다.

    상태 전이(analysis.review)가 패턴 → 패턴 세트 버전 → 분석 순서로 잠그므로, 분석 행은 패턴
    쪽을 다 쓴 뒤 잠근다. 구간은 분석 행을 잠근 뒤 지우고 넣는다. 구간을 쓰는 모든 경로가 이
    순서라 같은 구간이 겹쳐 들어가지 않는다(#41).
    """
    s = sentence
    patterns.lock_links()
    try:
        with transaction.atomic():
            rows = span_matches(s, s.existing, validated, final)
            locked = SentenceAnalysis.objects.select_for_update(no_key=True).get(pk=s.existing.pk)
            locked.span_matches.all().delete()
            SpanMatch.objects.bulk_create(rows)
    except IntegrityError as e:
        # 순서를 지키지 않은 쓰기가 같은 구간을 먼저 넣었다. 저장하지 못한 채 끝나 run이
        # 실패로 알린다.
        if not _is_place_conflict(e):
            raise
        return False
    locked.status = SentenceAnalysis.Status.COMPLETE
    locked.translation_ko = validated["translation_ko"]
    locked.processing_translation_ko = None
    locked.word_spans = stored_words
    locked.name_spans = s.name_spans(validated["name_spans"])
    locked.sense_ids = _sense_ids(stored_words)
    locked.is_stale = False
    # 세대 번호가 같으면 그사이 더 높은 버전으로 저장된 적이 없지만, 값은 낮추지 않는다.
    locked.matcher_version = max(locked.matcher_version, s.matcher_version)
    locked.save(
        update_fields=[
            "status",
            "translation_ko",
            "processing_translation_ko",
            "word_spans",
            "name_spans",
            "sense_ids",
            "is_stale",
            "matcher_version",
            "updated_at",
        ]
    )
    # 다시 선점하면 세대 번호가 오르므로, 옛 시도의 저장은 여기서 되돌려진다(#99).
    return locked.generation != s.started_generation or _basis_changed(rows, s.rules)
