"""자정이 지난 탈퇴 계정의 사용량 행을 지운다. 매일 예약 실행한다(#252)."""

from django.core.management.base import BaseCommand

from analysis import usage


class Command(BaseCommand):
    help = "자정(Asia/Seoul)이 지난 탈퇴 계정의 사용량 행을 지운다."

    def handle(self, *args, **options):
        usage.purge_withdrawn()
