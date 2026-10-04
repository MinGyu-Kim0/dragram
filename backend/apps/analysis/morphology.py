from functools import lru_cache
from importlib.metadata import version

from django.db import transaction
from sudachipy import dictionary, tokenizer

from core.models import Morpheme, MorphologicalAnalysis


@lru_cache(maxsize=1)
def sudachi_tokenizer():
    return dictionary.Dictionary().create()


@transaction.atomic
def create_morphology(sentence):
    analyzer_version = version("SudachiPy")
    dictionary_version = version("SudachiDict-core")
    morphology, created = MorphologicalAnalysis.objects.get_or_create(
        sentence=sentence,
        analyzer_version=analyzer_version,
        dictionary_version=dictionary_version,
        split_mode="C",
    )
    if not created:
        return morphology

    tokens = []
    for position, morpheme in enumerate(
        sudachi_tokenizer().tokenize(sentence.text, tokenizer.Tokenizer.SplitMode.C)
    ):
        pos = list(morpheme.part_of_speech()) + [""] * 6
        tokens.append(
            Morpheme(
                morphology=morphology,
                position=position,
                surface=morpheme.surface(),
                normalized_form=morpheme.normalized_form(),
                dictionary_form=morpheme.dictionary_form(),
                reading_form=morpheme.reading_form(),
                pos1=pos[0],
                pos2=pos[1],
                pos3=pos[2],
                pos4=pos[3],
                pos5=pos[4],
                pos6=pos[5],
                begin_offset=morpheme.begin(),
                end_offset=morpheme.end(),
            )
        )
    Morpheme.objects.bulk_create(tokens)
    return morphology
