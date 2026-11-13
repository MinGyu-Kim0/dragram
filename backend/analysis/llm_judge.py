"""다시 묻기·재판정의 지시문과 응답 스키마."""

from analysis.llm_rules import (
    COLLOQUIAL_RULE,
    FUNCTION_TAGS_RULE,
    KOREAN_EQUIVALENT_RULE,
    USAGE_NAME_RULE,
    span_answers_schema,
)

# 첫 응답의 해석 갈림·미확정 구간과, 같은 형태소 조건의 패턴이 이미 있는 구간을 한 번에 다시
# 묻는 지침(#40). 이 호출이 마지막이라 여기서 받은 해석 갈림·미확정은 다시 묻지 않는다.
JUDGE_INSTRUCTIONS = (
    """\
You help a Korean learner of Japanese read one Japanese sentence.
You receive the sentence, its tokens, each with an id, its Korean translation (translation_ko),
decided_spans, recheck_spans and spans. A span is a run of tokens (start_token_id to
end_token_id) that matched a registered grammar pattern, with candidate usages of that pattern.
decided_spans are already explained (with the usage name). Do not answer them, and keep their
reading as it is.
Answer every span in recheck_spans and in spans, each by its span_id. Give a verdict:
- "usage": one candidate explains the span. Give its candidate_id.
- "not_applicable": there is no grammar to learn at that place.
- "unfound": only for spans in spans. The span has grammar to learn but no candidate explains
  it. Give new_usage: a short Korean name of the usage (usage_name), a Korean explanation of the
  usage in general so that it fits every sentence with this usage, not of this sentence
  (explanation_ko), a new short Japanese example sentence of your own with the same usage
  (example_ja), and korean_equivalent and function_tags as described below.
"""
    + USAGE_NAME_RULE
    + """ For a pattern of one particle
  or auxiliary verb, explain what that word itself does, not the meaning of the word after it.
- "divergent": the sentence alone can really be read with more than one candidate. Give the
  candidate_id of the main reading and, in alternatives, each other candidate that also fits:
  its candidate_id, the Korean translation of the whole sentence read that way
  (translation_ko), and basis: in Korean, what earlier context would make that reading right.
- "unresolved": you cannot tell which candidate explains the span, or you cannot write a basis
  for the other readings.
If something in the sentence decides the reading, choose one candidate with "usage". Use
"divergent" only when the readings truly split, and write a basis for every alternative.
Use null for candidate_id unless the verdict is "usage" or "divergent", null for new_usage
unless the verdict is "unfound", and null for alternatives unless the verdict is "divergent".
Use only candidate ids given for that span. An alternative must be a candidate other than the
main one, and its translation must differ from the translation of the whole sentence.
"""
    + COLLOQUIAL_RULE
    + """\
If you receive recheck_spans, also return in translation_ko the Korean translation of the
whole sentence with your main readings.
In usage_name, explanation_ko and korean_equivalent, quote Japanese only from that span's own
tokens. Never quote the whole sentence or long parts of it. Do not write number placeholders
(⟨N1⟩) there.
"""
    + KOREAN_EQUIVALENT_RULE
    + FUNCTION_TAGS_RULE
)


def judge_schema(with_translation):
    """다시 묻기 응답. 첫 응답의 해석 갈림·미확정 구간을 다시 물을 때만 번역을 받는다."""
    properties = {"spans": span_answers_schema(True)}
    if with_translation:
        properties = {"translation_ko": {"type": "string"}, **properties}
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }
