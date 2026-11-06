"""여러 용도의 프롬프트가 함께 쓰는 규칙과 판정 스키마."""

from analysis.models import FunctionTag

# 새 용법의 대응 표현(#152). 새 구문·미발견·다시 묻기·용법 채우기가 같은 규칙을 쓴다.
KOREAN_EQUIVALENT_RULE = """\
- korean_equivalent: how this usage is usually rendered in Korean, as one short string, for
  the usage in general and not for one sentence. Join several Korean expressions with " · ".
  If the Korean expression depends on the verb or other words, add a short condition with a
  few typical examples in parentheses. Examples: に for time "~에", に for the other party of
  an action "~에게 · ~을/를 (会う·乗る 등)", で for means "~(으)로", が for the subject
  "~이/가 · ~을/를 (好き·できる 등)", ました "~었습니다". Write "" if no Korean expression fits.
  For a pattern of one particle or auxiliary verb, render only that word, not the word after
  it: に for the result of a change is "~(으)로", not "~이/가 되다" (that is なる).
"""

# 새 용법의 기능 태그(#151). 새 용법을 만드는 경로와 용법 채우기가 같은 규칙을 쓴다.
FUNCTION_TAGS_RULE = """\
- function_tags: the functions of this usage in general, chosen only from the allowed values
  (for example passive, past, progressive, polite, negative, conditional, cause, topic,
  subject, object, place, means). Choose every value that fits the usage itself, in any
  number, and an empty list if none fits. Do not choose a value for the content of one
  sentence.
"""

# 기능 태그 답. 허용 목록 밖 값은 서버도 버린다(answers.function_tags).
FUNCTION_TAGS_SCHEMA = {"type": "array", "items": {"type": "string", "enum": FunctionTag.values}}

# 번역(다시 묻기의 번역과 대안 번역 포함)에 숫자 자리표시자를 옮기는 규칙
NUMBER_RULES = """\
Numbers in the sentence are replaced with placeholders such as ⟨N1⟩ and ⟨N2⟩.
Copy every placeholder into each Korean translation exactly as written, with the same brackets
and number. Do not turn a placeholder into digits or words, drop it, or add a placeholder that
is not in the sentence. Example: "⟨N1⟩人で行く" → "⟨N1⟩명이서 간다".
The same translation is reused for sentences that differ only in their numbers, so keep
number notation exactly as in the sentence. Do not turn "⟨N1⟩:⟨N2⟩", "⟨N1⟩/⟨N2⟩" or
"⟨N1⟩.⟨N2⟩" into words such as 시/분, 월/일 or 대: "⟨N1⟩:⟨N2⟩です" → "⟨N1⟩:⟨N2⟩입니다".
"""

# 후보 구간 판정. usage는 후보 하나를 고른 것(decided)이다. divergent는 문장만으로 해석이
# 갈리는 것(주 용법은 번역과 같은 해석), unresolved는 판단하지 못한 것이다(#40).
SPAN_VERDICTS = ("usage", "not_applicable", "unfound", "divergent", "unresolved")

# 해석 갈림의 대안. 다시 묻기에서만 받는다. 근거(basis)는 비었는지만 보고 버린다.
ALTERNATIVES_SCHEMA = {
    "anyOf": [
        {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "candidate_id": {"type": "integer"},
                    "translation_ko": {"type": "string"},
                    "basis": {"type": "string"},
                },
                "required": ["candidate_id", "translation_ko", "basis"],
                "additionalProperties": False,
            },
        },
        {"type": "null"},
    ]
}


def span_answers_schema(with_alternatives):
    """후보 구간마다의 판정. 첫 분석과 다시 묻기가 함께 쓰고, 다시 묻기만 대안을 받는다."""
    item = {
        "type": "object",
        "properties": {
            "span_id": {"type": "integer"},
            "verdict": {"type": "string", "enum": list(SPAN_VERDICTS)},
            "candidate_id": {"type": ["integer", "null"]},
            "new_usage": {
                "anyOf": [
                    {
                        "type": "object",
                        "properties": {
                            "usage_name": {"type": "string"},
                            "explanation_ko": {"type": "string"},
                            "example_ja": {"type": "string"},
                            "korean_equivalent": {"type": "string"},
                            "function_tags": FUNCTION_TAGS_SCHEMA,
                        },
                        "required": [
                            "usage_name",
                            "explanation_ko",
                            "example_ja",
                            "korean_equivalent",
                            "function_tags",
                        ],
                        "additionalProperties": False,
                    },
                    {"type": "null"},
                ]
            },
        },
        "required": ["span_id", "verdict", "candidate_id", "new_usage"],
        "additionalProperties": False,
    }
    if with_alternatives:
        item["properties"]["alternatives"] = ALTERNATIVES_SCHEMA
        item["required"].append("alternatives")
    return {"type": "array", "items": item}
