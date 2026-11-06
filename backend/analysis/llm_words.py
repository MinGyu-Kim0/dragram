"""단어의 한국어 뜻과 새 단어 정의의 지시문·응답 스키마."""

from analysis.jmdict import SENSE_TAG_NAMES, WHOLE_WORD_TAGS

# JMdict 뜻의 한국어 뜻을 만드는 지침(#97). 근거는 사전 칸뿐이다.
GLOSS_INSTRUCTIONS = """\
You translate Japanese dictionary senses for a Korean learner of Japanese.
You receive senses. Each has an id (sense_id), the headword (dictionary_form), its reading,
the part of speech code of the word (pos), the English glosses of this sense (gloss_en) and
sense tags. For each sense, write one short Korean meaning (meaning_ko) of that sense only,
as a dictionary would. Join close synonyms with ", " (for example "먹다, 식사하다"). Do not
write explanations, examples, readings or the Japanese headword. Answer every sense_id you
received.
"""

GLOSS_SCHEMA = {
    "type": "object",
    "properties": {
        "senses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "sense_id": {"type": "integer"},
                    "meaning_ko": {"type": "string"},
                },
                "required": ["sense_id", "meaning_ko"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["senses"],
    "additionalProperties": False,
}

# 사전에 없는 단어의 2단계(#134). 서버가 다시 찾은 후보에서 고르거나 새 뜻을 만든다.
DEFINE_INSTRUCTIONS = """\
You help a Korean learner of Japanese with words that the dictionary lookup missed.
You receive a Japanese sentence and words of it. Each word has an id (word_id), the token
(token_id), its dictionary form, its reading and candidate senses of a dictionary entry as
"sense id: meaning". The candidates may be empty.
For each word give its word_id and:
- sense_id: the candidate with the meaning the word has in this sentence, or null if no
  candidate fits or there are none.
- meaning_ko: when sense_id is null, one short Korean meaning of the word as used in this
  sentence, written as a dictionary would, not an explanation of the sentence. Otherwise "".
- sense_tags: tags of that meaning from the allowed list, if any.
- word_tags: tags of the whole word from the allowed list (part of speech, verb group, proper
  noun).
Answer every word_id you received.
"""

DEFINE_SCHEMA = {
    "type": "object",
    "properties": {
        "words": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "word_id": {"type": "integer"},
                    "sense_id": {"type": ["integer", "null"]},
                    "meaning_ko": {"type": "string"},
                    "sense_tags": {
                        "type": "array",
                        "items": {"type": "string", "enum": sorted(SENSE_TAG_NAMES)},
                    },
                    "word_tags": {
                        "type": "array",
                        "items": {"type": "string", "enum": sorted(WHOLE_WORD_TAGS)},
                    },
                },
                "required": ["word_id", "sense_id", "meaning_ko", "sense_tags", "word_tags"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["words"],
    "additionalProperties": False,
}
