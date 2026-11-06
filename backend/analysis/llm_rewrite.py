"""예문 다시 쓰기의 지시문과 응답 스키마."""

# 원문을 베껴 거부된 새 예문을 다시 쓰게 하는 지침
REWRITE_INSTRUCTIONS = """\
You help build Japanese example sentences for grammar usages.
You receive a Japanese sentence that a learner is reading, and examples. Each example has an
id (example_id), a grammar pattern (pattern_name), a usage (usage_name, explanation_ko) and an
example sentence (rejected_example) that was rejected because it copied the learner's sentence.
For each example, write a new short Japanese sentence (example_ja) that uses the same grammar
pattern with the same usage. Write a sentence of your own about a different topic. Do not copy
the learner's sentence or any of its phrases; only the grammar pattern itself may appear in
both. Do not write number placeholders (⟨N1⟩). Answer every example_id you received.
"""

REWRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "examples": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "example_id": {"type": "integer"},
                    "example_ja": {"type": "string"},
                },
                "required": ["example_id", "example_ja"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["examples"],
    "additionalProperties": False,
}
