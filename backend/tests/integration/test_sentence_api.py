import json
from unittest.mock import patch

from django.test import Client, TestCase, override_settings

from core.models import GrammarMatch, Sentence, SentenceAnalysis, User, UserSentence


class SentenceAnalysisApiTests(TestCase):
    @patch("apps.analysis.views.analyze_grammar")
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

    def test_health_endpoint_is_available(self):
        response = self.client.get("/api/health/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
