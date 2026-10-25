"""사용 중인 평가 문장 전체를 실제 분석 흐름으로 돌려 평가 실행 하나로 남긴다(FR-A26, #177).

유료 API를 부르므로 --yes 없이는 돌릴 문장 수만 알리고 끝낸다.
"""

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from analysis.evaluation import evaluate_sentence
from analysis.models import EvalRun, EvalSentence


class Command(BaseCommand):
    help = "평가 세트를 돌려 평가 실행을 남긴다. 유료 API를 부르므로 --yes가 있어야 돈다."

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true", help="LLM을 불러 실제로 돌린다")
        parser.add_argument("--note", default="", help="실행 메모(무엇을 바꿨는지)")

    def handle(self, yes, note, **options):
        sentences = list(EvalSentence.objects.filter(is_active=True).order_by("id"))
        if not yes:
            self.stdout.write(f"평가 문장 {len(sentences)}개. 유료 API를 부르려면 --yes를 붙인다.")
            return
        run = EvalRun.objects.create(model=settings.OPENAI_MODEL, note=note)
        try:
            failed = sum(evaluate_sentence(run, sentence).failed for sentence in sentences)
        except BaseException:
            run.status = EvalRun.Status.FAILED
            raise
        else:
            run.status = EvalRun.Status.COMPLETE
        finally:
            run.finished_at = timezone.now()
            run.save(update_fields=["status", "finished_at"])
        self.stdout.write(f"평가 실행 #{run.pk}: 문장 {len(sentences)}개, 실패 {failed}개.")
