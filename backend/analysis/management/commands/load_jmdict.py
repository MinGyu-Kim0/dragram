"""JMdict를 word·word_sense에 한 번 적재한다(design-decisions 24절).

원본 파일과 내용은 보관하지 않고 재적재하지 않는다. 적재한 판본은 설정값 JMDICT_EDITION
한 줄로 남기고, 적재 직후 DB를 백업한다(운영 절차).
"""

import gzip
from itertools import batched
from xml.etree.ElementTree import ParseError

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from analysis import jmdict
from analysis.models import ReviewStatus, Word, WordSense

# 행이 수십만 개라 이만큼씩 일괄 삽입한다.
BATCH_SIZE = 2000


class Command(BaseCommand):
    help = "JMdict XML(.xml 또는 .gz)을 word·word_sense에 한 번 적재한다. 다시 적재하지 않는다."

    def add_arguments(self, parser):
        parser.add_argument("path", help="JMdict XML 파일 경로")

    def handle(self, path, **options):
        if not settings.JMDICT_EDITION:
            raise CommandError("적재할 판본 이름(JMDICT_EDITION)이 설정되지 않음")
        opener = gzip.open if path.endswith(".gz") else open
        try:
            # 중간에 실패하면 아무것도 남기지 않는다. 남으면 다시 적재할 수 없다.
            with transaction.atomic(), opener(path, "rt", encoding="utf-8") as lines:
                if Word.objects.filter(jmdict_seq__isnull=False).exists():
                    raise CommandError("JMdict가 이미 적재됨. 다시 적재하지 않는다")
                words, senses = 0, 0
                for entries in batched(jmdict.parse(lines), BATCH_SIZE, strict=False):
                    words, senses = words + len(entries), senses + _save(entries)
        except (OSError, ParseError) as e:
            raise CommandError(f"JMdict 파일을 읽지 못함: {e}") from e
        self.stdout.write(f"JMdict {settings.JMDICT_EDITION} 적재: 단어 {words}개, 뜻 {senses}개")


def _save(entries):
    """항목 묶음을 단어·뜻으로 넣고 넣은 뜻 수를 돌려준다."""
    saved = Word.objects.bulk_create(
        Word(
            jmdict_seq=entry.seq,
            dictionary_form=entry.dictionary_form,
            reading=entry.reading,
            forms=entry.forms,
            readings=entry.readings,
            is_common=entry.is_common,
            reading_restrictions=entry.reading_restrictions,
            pos=entry.pos,
            tags=entry.tags,
        )
        for entry in entries
    )
    senses = WordSense.objects.bulk_create(
        WordSense(
            word=word,
            jmdict_sense_index=sense.index,
            gloss_en=sense.gloss_en,
            tags=sense.tags,
            applies_to=sense.applies_to,
            sense_origin=WordSense.Origin.JMDICT,
            sense_status=ReviewStatus.APPROVED,
            meaning_status=WordSense.MeaningStatus.AI,
        )
        for word, entry in zip(saved, entries, strict=True)
        for sense in entry.senses
    )
    return len(senses)
