"""첫 분석의 지시문과 응답 스키마."""

from analysis.llm_rules import (
    COLLOQUIAL_RULE,
    FUNCTION_TAGS_RULE,
    FUNCTION_TAGS_SCHEMA,
    KOREAN_EQUIVALENT_RULE,
    USAGE_NAME_RULE,
    span_answers_schema,
)

INSTRUCTIONS = (
    """\
You help a Korean learner of Japanese read one Japanese sentence.
You receive the sentence, its tokens, each with an id, spans, decided_spans, words and
unknown_words.
Return the Korean translation of the whole sentence in translation_ko.

In spans, answer every span you received. A span is a run of tokens (start_token_id to
end_token_id) that matched a registered grammar pattern, with candidate usages of that pattern.
For each span give its span_id and a verdict:
- "usage": one candidate explains the span with the same reading as your translation. Give its
  candidate_id.
- "not_applicable": there is no grammar to learn at that place (for example の inside a name).
- "unfound": the span has grammar to learn but no candidate explains it. Give new_usage: the
  usage that explains it, which will be added to the same pattern, with usage_name,
  explanation_ko, example_ja, korean_equivalent and function_tags written as described for
  new_patterns below.
- "divergent": the sentence alone can be read with more than one candidate, and nothing in it
  tells which. Give the candidate_id of the candidate with the same reading as your
  translation. Use it only for a span with two or more candidates.
- "unresolved": you cannot tell which candidate explains the span, or the place is outside
  what you can judge.
Use null for candidate_id unless the verdict is "usage" or "divergent", and null for new_usage
unless the verdict is "unfound". Use only candidate ids given for that span.
"""
    + COLLOQUIAL_RULE
    + """
In new_patterns, list grammar points of the sentence that no span explains: particles,
auxiliary verbs, conjugations and grammatical expressions a learner needs. Do not list plain
content words or grammar that a span already explains. decided_spans are grammar points already
explained (start_token_id to end_token_id, with the usage name); do not answer them and do not
list them in new_patterns. A span or decided span explains only its own tokens: when a
grammatical expression of several tokens (such as になる after a noun, or ことができる) is only
partly covered by spans, list the whole expression. For 先生になる, list に and なる together
even if a span already covers に (なる marked "lemma"). For each one:
- tokens: every token of the grammar point in order, from its first to its last token with no
  gap, each with a mark (fix). "lemma" means the same word in any conjugation, "form" means the
  same word in the same conjugated form, "any" means any single token. The first and last
  tokens cannot be "any". Fix only the tokens that form the grammar: particles, auxiliary
  verbs and words that are part of a grammatical expression (such as 居る in ている, or こと and
  出来る in ことができる). Leave out the content of the sentence, such as the noun being
  modified or the verb being conjugated, or mark it "any" when it lies between grammar tokens:
  for 勝ちました list only ます and た. If the grammar point
  cannot be written without fixing such a token as its first or last token, do not list it.
  Do not list structures made only of content words, such as a verb or noun modifying a noun.
- pattern_name: a short name of the pattern, such as ている or 명사+で. Write word classes and
  conjugated forms in Korean (명사, 동사 보통형, 형용동사 어간), and grammar words in Japanese.
- connection_form: a concise, general attachment formula in Korean, such as 동사 て형 + いる.
  State the exact word class and conjugation without duplicating an ending
  (not 동사 て형 + ている).
  Cover the pattern's valid attachment forms, not this sentence's surface. Do not quote the user's
  words or names. Use null if no reliable general formula can be given. Use at most 255 characters.
- usage_name: a short Korean name of this usage, such as 진행.
"""
    + USAGE_NAME_RULE
    + """
- explanation_ko: a Korean explanation of the usage in general, so that it fits every sentence
  with this usage. Do not explain this sentence or its content. For a pattern of one particle
  or auxiliary verb, explain what that word itself does, not the meaning of the word after it.
- example_ja: a new short Japanese example sentence with the same grammar and usage. Write a
  sentence of your own. Do not reuse this sentence or its words.
"""
    + KOREAN_EQUIVALENT_RULE
    + FUNCTION_TAGS_RULE
    + """\
In pattern_name, usage_name, explanation_ko and korean_equivalent, quote Japanese only from that
grammar point's own tokens. Never quote the whole sentence or long parts of it. Do not write number
placeholders (⟨N1⟩) there. If the sentence has no new grammar to learn, return an empty list.

In words, answer every token you received in words. Each has candidate senses of that word as
"sense id: English glosses". Give its token_id and the sense_id of the candidate with the
meaning the token has in this sentence. Use only sense ids given for that token.

unknown_words are ids of tokens that are not in the dictionary. In new_words, answer each of
them that is a word a learner can look up: its token_id, its dictionary form as usually
written (dictionary_form) and the reading of that dictionary form in hiragana (reading). Do
not answer names of people, places, works or organizations, or tokens that are not words.

In name_spans, list every proper noun as it is used in this sentence: names of people,
places, organizations and works, and other names. For each give token_ids (every token of the
name in order, with no gap) and its type: "person", "place", "org", "work" or "other". Judge
by the meaning in this sentence: a word that can be a name but is a common word here (春 as
the season) is not a name. If the sentence has no name, return an empty list.

"""
)

# 새 구문 토큰 표시: lemma 고정 / 활용형도 고정 / 아무거나
TOKEN_FIXES = ("lemma", "form", "any")

# 이름 구간 종류(#140): 사람 / 장소 / 조직 / 작품 / 기타
NAME_TYPES = ("person", "place", "org", "work", "other")

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "translation_ko": {"type": "string"},
        "spans": span_answers_schema(False),
        "words": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "token_id": {"type": "integer"},
                    "sense_id": {"type": "integer"},
                },
                "required": ["token_id", "sense_id"],
                "additionalProperties": False,
            },
        },
        "new_patterns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tokens": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "token_id": {"type": "integer"},
                                "fix": {"type": "string", "enum": list(TOKEN_FIXES)},
                            },
                            "required": ["token_id", "fix"],
                            "additionalProperties": False,
                        },
                    },
                    "pattern_name": {"type": "string"},
                    "connection_form": {"type": ["string", "null"]},
                    "usage_name": {"type": "string"},
                    "explanation_ko": {"type": "string"},
                    "example_ja": {"type": "string"},
                    "korean_equivalent": {"type": "string"},
                    "function_tags": FUNCTION_TAGS_SCHEMA,
                },
                "required": [
                    "tokens",
                    "pattern_name",
                    "connection_form",
                    "usage_name",
                    "explanation_ko",
                    "example_ja",
                    "korean_equivalent",
                    "function_tags",
                ],
                "additionalProperties": False,
            },
        },
        "new_words": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "token_id": {"type": "integer"},
                    "dictionary_form": {"type": "string"},
                    "reading": {"type": "string"},
                },
                "required": ["token_id", "dictionary_form", "reading"],
                "additionalProperties": False,
            },
        },
        "name_spans": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "token_ids": {"type": "array", "items": {"type": "integer"}},
                    "type": {"type": "string", "enum": list(NAME_TYPES)},
                },
                "required": ["token_ids", "type"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["translation_ko", "spans", "words", "new_patterns", "new_words", "name_spans"],
    "additionalProperties": False,
}
