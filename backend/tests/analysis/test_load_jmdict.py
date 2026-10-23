"""JMdict 1회 적재 관리 명령(#95). 실제 JMdict 전체 파일은 쓰지 않는다."""

import gzip
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from analysis import jmdict
from analysis.management.commands import load_jmdict
from analysis.models import Word, WordSense
from tests.analysis.test_jmdict import SAMPLE

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def edition(settings):
    settings.JMDICT_EDITION = "JMdict_e 2026-10-01"


def load(path=SAMPLE):
    out = StringIO()
    call_command("load_jmdict", str(path), stdout=out)
    return out.getvalue()


def snapshot():
    return (
        list(Word.objects.order_by("id").values()),
        list(WordSense.objects.order_by("id").values()),
    )


def test_sample_fills_words_and_senses_as_parsed():
    out = load()

    assert "JMdict_e 2026-10-01" in out
    assert Word.objects.count() == 5
    assert WordSense.objects.count() == 9
    word = Word.objects.get(jmdict_seq=1576260)
    assert (word.dictionary_form, word.reading) == ("朔日", "ついたち")
    assert word.forms == ["朔日", "一日", "いちにち", "ついたち", "ツイタチ"]
    assert word.readings == ["いちにち", "ついたち"]
    assert word.is_common
    assert word.reading_restrictions == {"いちにち": ["一日"], "ツイタチ": []}
    assert word.pos == "n,n-adv"
    assert word.tags == ["noun"]
    first, second = word.senses.order_by("jmdict_sense_index")
    assert (first.jmdict_sense_index, first.gloss_en, first.applies_to) == (
        1,
        ["one day"],
        {"forms": ["一日"], "readings": ["いちにち"]},
    )
    assert (second.jmdict_sense_index, second.applies_to) == (2, None)
    assert Word.objects.get(jmdict_seq=1202450).senses.get(jmdict_sense_index=2).tags == [
        "transitive"
    ]


def test_senses_are_approved_jmdict_senses_without_korean_meaning():
    load()

    assert set(
        WordSense.objects.values_list(
            "sense_origin", "sense_status", "meaning_ko", "meaning_source", "meaning_status"
        )
    ) == {("jmdict", "approved", None, None, "ai")}


def test_second_load_is_refused_and_changes_nothing():
    load()
    before = snapshot()

    with pytest.raises(CommandError):
        load()

    assert snapshot() == before


def test_load_without_an_edition_name_is_refused(settings):
    settings.JMDICT_EDITION = ""

    with pytest.raises(CommandError):
        load()

    assert not Word.objects.exists()


def test_broken_file_loads_nothing(tmp_path, monkeypatch):
    # 일괄 삽입 묶음이 몇 번 들어간 뒤 깨져도 하나도 남기지 않는다.
    monkeypatch.setattr(load_jmdict, "BATCH_SIZE", 2)
    broken = tmp_path / "broken.xml"
    broken.write_text(SAMPLE.read_text(encoding="utf-8").replace("</JMdict>", "<entry>"))

    with pytest.raises(CommandError):
        load(broken)

    assert not Word.objects.exists()
    assert not WordSense.objects.exists()


def test_small_batches_load_every_entry(monkeypatch):
    monkeypatch.setattr(load_jmdict, "BATCH_SIZE", 2)

    load()

    assert Word.objects.count() == 5
    assert WordSense.objects.count() == 9


def test_gzip_file_is_read_as_it_is(tmp_path):
    # JMdict는 gzip으로 배포된다.
    packed = tmp_path / "JMdict_e.gz"
    packed.write_bytes(gzip.compress(SAMPLE.read_bytes()))

    load(packed)

    assert Word.objects.count() == 5


def test_tags_are_from_the_allowed_list():
    load()

    tags = {tag for tags in Word.objects.values_list("tags", flat=True) for tag in tags}
    tags |= {tag for tags in WordSense.objects.values_list("tags", flat=True) for tag in tags}
    assert tags <= jmdict.ALLOWED_TAGS
