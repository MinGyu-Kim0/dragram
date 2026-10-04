import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.analysis.llm import analyze_grammar


class OpenAiSdkTests(TestCase):
    @override_settings(OPENAI_API_KEY="test-key")
    @patch("apps.analysis.llm.OpenAI")
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
