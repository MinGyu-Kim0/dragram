import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import Client, TestCase, override_settings

from .models import GrammarMatch, Sentence, SentenceAnalysis, User, UserSentence
from .services import analyze_grammar, create_morphology, normalize_sentence, sentence_hash


class MorphemeTests(TestCase):
    def test_normalization_and_sudachi_tokens_are_stored(self):
        self.assertEqual(normalize_sentence("  Ａ  から\n学校へ  "), "A から 学校へ")
        text = "雨が降ったから、家に帰った。"
        sentence = Sentence.objects.create(text=text, normalized_text=text, text_hash=sentence_hash(text))

        morphology = create_morphology(sentence)
        tokens = list(morphology.tokens.all())

        self.assertIn("から", [token.surface for token in tokens])
        self.assertTrue(all(token.begin_offset < token.end_offset for token in tokens))


class OpenAiSdkTests(TestCase):
    @override_settings(OPENAI_API_KEY="test-key")
    @patch("core.services.OpenAI")
    def test_analyze_grammar_uses_responses_sdk(self, openai):
        token = SimpleNamespace(
            position=0,
            surface="食べ",
            normalized_form="食べる",
            dictionary_form="食べる",
            reading_form="タベ",
            pos1="動詞",
            pos2="一般",
            pos3="",
            pos4="",
            pos5="",
            pos6="",
        )
        morphology = SimpleNamespace(tokens=SimpleNamespace(all=lambda: [token]))
        expected = {"normalized_text": "食べる。", "meaning_ko": "먹는다.", "explanation": "", "grammars": []}
        openai.return_value.responses.create.return_value = SimpleNamespace(
            status="completed", output_text=json.dumps(expected, ensure_ascii=False)
        )

        result = analyze_grammar("食べる。", morphology, "gpt-5.6-luna")

        self.assertEqual(result, expected)
        openai.assert_called_once_with(api_key="test-key", timeout=60)
        payload = openai.return_value.responses.create.call_args.kwargs
        self.assertEqual(payload["model"], "gpt-5.6-luna")
        self.assertFalse(payload["store"])


class SentenceAnalysisApiTests(TestCase):
    @patch("core.views.analyze_grammar")
    def test_analysis_is_cached_saved_and_available_for_review(self, analyze_grammar):
        analyze_grammar.return_value = {
            "normalized_text": "行きます。",
            "meaning_ko": "갑니다.",
            "explanation": "정중한 현재형 문장입니다.",
            "grammars": [
                {
                    "canonical_name_ja": "〜ます",
                    "name_ko": "정중형",
                    "summary": "동사를 정중하게 표현합니다.",
                    "start_token": 1,
                    "end_token": 2,
                    "confidence": 0.99,
                    "evidence": "ます가 정중형을 나타냅니다.",
                }
            ],
        }
        payload = json.dumps(
            {"text": "行きます。", "source_url": "https://example.com/article", "source_title": "예문"}
        )

        first = self.client.post("/api/sentences/analyze/", payload, content_type="application/json")
        second = self.client.post("/api/sentences/analyze/", payload, content_type="application/json")
        terra = self.client.post(
            "/api/sentences/analyze/",
            json.dumps(
                {
                    "text": "行きます。",
                    "source_url": "https://example.com/article",
                    "source_title": "예문",
                    "model": "gpt-5.6-terra",
                }
            ),
            content_type="application/json",
        )
        invalid = self.client.post(
            "/api/sentences/analyze/",
            json.dumps({"text": "行きます。", "model": "gpt-5.6-sol"}),
            content_type="application/json",
        )
        review = self.client.get("/api/sentences/")

        self.assertEqual(first.status_code, 200)
        self.assertFalse(first.json()["cached"])
        self.assertTrue(second.json()["cached"])
        self.assertEqual(first.json()["model"], "gpt-5.6-luna")
        self.assertEqual(terra.status_code, 200)
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(first.json()["grammars"][0]["name_ja"], "〜ます")
        self.assertGreater(len(first.json()["vocabulary"]), 1)
        self.assertEqual(review.status_code, 200)
        self.assertEqual(review.json()["sentences"][0]["source_title"], "예문")
        self.assertEqual(Sentence.objects.count(), 1)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(UserSentence.objects.count(), 1)
        self.assertEqual(SentenceAnalysis.objects.count(), 2)
        self.assertEqual(GrammarMatch.objects.count(), 2)
        self.assertEqual(
            [call.args[2] for call in analyze_grammar.call_args_list],
            ["gpt-5.6-luna", "gpt-5.6-terra"],
        )

    @override_settings(CORS_ALLOWED_ORIGINS=["chrome-extension://abcdefghijklmnopabcdefghijklmnop"])
    def test_extension_origin_passes_cors(self):
        origin = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
        client = Client(enforce_csrf_checks=True)
        response = client.post(
            "/api/sentences/analyze/",
            json.dumps({"text": "English"}),
            content_type="application/json",
            HTTP_ORIGIN=origin,
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response["Access-Control-Allow-Origin"], origin)
