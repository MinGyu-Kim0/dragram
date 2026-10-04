from django.test import TestCase

from apps.analysis.morphology import create_morphology
from apps.library.text import normalize_sentence, sentence_hash
from core.models import Sentence


class MorphemeTests(TestCase):
    def test_normalization_and_sudachi_tokens_are_stored(self):
        self.assertEqual(normalize_sentence("  Ａ  から\n学校へ  "), "A から 学校へ")
        text = "雨が降ったから、家に帰った。"
        sentence = Sentence.objects.create(text=text, normalized_text=text, text_hash=sentence_hash(text))

        morphology = create_morphology(sentence)
        tokens = list(morphology.tokens.all())

        self.assertIn("から", [token.surface for token in tokens])
        self.assertTrue(all(token.begin_offset < token.end_offset for token in tokens))
