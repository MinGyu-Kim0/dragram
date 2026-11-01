"""대응 표현(#152)이나 기능 태그(#151)를 채운 적 없는 용법을 LLM으로 채운다.

근거는 패턴 이름·형태소 조건·용법 이름·설명·예문이고 문장 원문은 쓰지 않는다. 다시 돌려도 이미
채운 칸은 부르지도 덮지도 않는다. 반려된 용법과 반려된 패턴의 용법은 보이지 않으므로 채우지
않는다. 용법 상태는 바꾸지 않는다.
"""

from itertools import batched

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from analysis import llm, patterns
from analysis.answers import function_tags, korean_equivalent
from analysis.models import GrammarUsage, ReviewStatus, UsageLog
from errors import BusinessError

# 한 번에 묻는 용법 수
BATCH_SIZE = 20


def _record(seconds=None, **call):
    """사용자 요청이 아니라 user·analysis 없이 llm 행만 남긴다. 걸린 시간은 남기지 않는다."""
    UsageLog.objects.create(kind=UsageLog.Kind.LLM, **call)


class Command(BaseCommand):
    help = "대응 표현이나 기능 태그를 채운 적 없는 용법을 LLM으로 채운다. 채운 칸은 덮지 않는다."

    def add_arguments(self, parser):
        parser.add_argument("--batch", type=int, default=BATCH_SIZE, help="한 번에 묻는 용법 수")

    def handle(self, batch, **options):
        usages = (
            GrammarUsage.objects.filter(
                Q(korean_equivalent_filled=False) | Q(function_tags_filled=False)
            )
            .exclude(status=ReviewStatus.REJECTED)
            .exclude(pattern__status=ReviewStatus.REJECTED)
            .select_related("pattern")
            .prefetch_related("pattern__morphemes")
            .order_by("id")
        )
        filled = 0
        for group in batched(usages, batch, strict=False):
            # 클라이언트는 만들 때부터 요청 마감을 세므로 묶음마다 새로 만든다.
            client = llm.get_client(_record)
            try:
                answer = client.fill_usages(
                    [
                        {
                            "usage_id": usage.pk,
                            "pattern_name": usage.pattern.name,
                            "morphemes": [
                                {
                                    "lemma": c.lemma,
                                    "pos1": c.pos1,
                                    "conjugation_form": c.conjugation_form,
                                }
                                for c in patterns.conditions_of(usage.pattern)
                            ],
                            "usage_name": usage.name,
                            "explanation_ko": usage.explanation_ko,
                            "example_ja": usage.example_ja,
                        }
                        for usage in group
                    ]
                )
            except BusinessError as e:
                # 이 묶음은 채운 적 없음으로 남아 다음 실행이 다시 묻는다.
                self.stderr.write(f"용법 {group[0].pk}~{group[-1].pk} 채우기 실패: {e}")
                continue
            filled += _save({usage.pk for usage in group}, answer)
        self.stdout.write(f"용법 {filled}개를 채웠다")


def _save(asked, answer):
    """물은 용법(asked)의 답만 저장하고 저장한 용법 수를 돌려준다. 답이 없는 용법은 채운 적
    없음으로 남는다. 틀린 값은 비운 채 채운다(새 용법과 같은 규칙). 칸마다 아직 채운 적 없을
    때만 쓰므로, 이미 채웠거나 그사이 관리자가 채운 칸은 덮지 않는다. 승인된 용법이라도 나중에
    채운 값은 따로 승인할 때까지 미검수다.
    """
    items = answer.get("usages") if isinstance(answer, dict) else None
    saved = 0
    for item in items if isinstance(items, list) else []:
        usage_id = item.get("usage_id") if isinstance(item, dict) else None
        if type(usage_id) is not int or usage_id not in asked:
            continue
        asked.discard(usage_id)
        equivalent = korean_equivalent(item.get("korean_equivalent"))
        tags = function_tags(item.get("function_tags"))
        now = timezone.now()
        updated = GrammarUsage.objects.filter(pk=usage_id, korean_equivalent_filled=False).update(
            korean_equivalent=equivalent,
            korean_equivalent_filled=True,
            korean_equivalent_status=patterns.filled_status(equivalent),
            updated_at=now,
        )
        updated += GrammarUsage.objects.filter(pk=usage_id, function_tags_filled=False).update(
            function_tags=tags,
            function_tags_filled=True,
            function_tags_status=patterns.filled_status(tags),
            updated_at=now,
        )
        saved += bool(updated)
    return saved
