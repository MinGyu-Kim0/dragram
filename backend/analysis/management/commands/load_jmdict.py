"""JMdict를 word·word_sense에 한 번 적재한다(design-decisions 24절).

원본 파일과 내용은 보관하지 않고 재적재하지 않는다. 적재한 판본은 설정값 JMDICT_EDITION
한 줄로 남기고, 적재 직후 DB를 백업한다(운영 절차). 변환표가 바뀌면 --update-tags로
이미 적재한 행의 tags만 다시 계산한다(#235).
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
        parser.add_argument(
            "--update-tags",
            action="store_true",
            help="이미 적재한 단어·뜻의 tags만 지금 변환표로 다시 계산한다(#235)",
        )

    def handle(self, path, update_tags=False, **options):
        if not settings.JMDICT_EDITION:
            raise CommandError("적재할 판본 이름(JMDICT_EDITION)이 설정되지 않음")
        opener = gzip.open if path.endswith(".gz") else open
        try:
            # 중간에 실패하면 아무것도 남기지 않는다. 남으면 다시 적재할 수 없다.
            with transaction.atomic(), opener(path, "rt", encoding="utf-8") as lines:
                loaded = Word.objects.filter(jmdict_seq__isnull=False).exists()
                if update_tags and not loaded:
                    raise CommandError("적재한 JMdict 단어가 없음. 먼저 적재한다")
                if not update_tags and (Word.objects.exists() or WordSense.objects.exists()):
                    raise CommandError("word·word_sense가 이미 차 있음. 다시 적재하지 않는다")
                write = _update_tags if update_tags else _save
                words, senses = 0, 0
                for entries in batched(jmdict.parse(lines), BATCH_SIZE, strict=False):
                    words, senses = words + len(entries), senses + write(entries)
        except (OSError, ParseError, UnicodeDecodeError) as e:
            raise CommandError(f"JMdict 파일을 읽지 못함: {e}") from e
        except jmdict.JMdictError as e:
            raise CommandError(str(e)) from e
        action = "태그 갱신" if update_tags else "적재"
        edition = settings.JMDICT_EDITION
        self.stdout.write(f"JMdict {edition} {action}: 단어 {words}개, 뜻 {senses}개")


def _update_tags(entries):
    """항목 묶음과 jmdict_seq·뜻 번호가 같은 행의 tags만 고치고 고친 뜻 수를 돌려준다.

    LLM이 만든 단어·뜻(jmdict_seq 없음, sense_origin llm)은 건드리지 않는다.
    """
    by_seq = {entry.seq: entry for entry in entries}
    words = list(Word.objects.filter(jmdict_seq__in=by_seq))
    for word in words:
        word.tags = by_seq[word.jmdict_seq].tags
    Word.objects.bulk_update(words, ["tags"])
    sense_tags = {
        (entry.seq, sense.index): sense.tags for entry in entries for sense in entry.senses
    }
    senses = list(
        WordSense.objects.filter(
            word__jmdict_seq__in=by_seq, sense_origin=WordSense.Origin.JMDICT
        ).select_related("word")
    )
    for sense in senses:
        sense.tags = sense_tags.get((sense.word.jmdict_seq, sense.jmdict_sense_index), sense.tags)
    WordSense.objects.bulk_update(senses, ["tags"])
    return len(senses)


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
