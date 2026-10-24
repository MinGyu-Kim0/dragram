"""분석 LLM 작업을 실행하는 작업자를 띄운다(#98)."""

from django.core.management.base import BaseCommand

from analysis import jobs


class Command(BaseCommand):
    help = "분석 작업 큐의 작업을 실행한다."

    def handle(self, *args, **options):
        jobs.work()
