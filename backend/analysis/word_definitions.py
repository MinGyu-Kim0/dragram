"""사전에 없는 단어의 뜻 고르기·만들기와 뜻의 한국어 뜻 만들기."""

from analysis import words
from analysis.answers import _quotes_whole_sentence, _validate_definitions, _validate_meanings
from errors import BusinessError
from errors.handler import log_business_error


def define_new_words(sentence, client, new_words, job_outdated):
    """사전에 없던 토큰의 2단계(#134). {토큰: 사전형·읽기}를 받아 {토큰: 뜻 ID}를 돌려준다.

    받은 사전형·읽기로 다시 찾아, 기존 단어면 그 후보에서 고르게 하고 맞는 뜻이 없으면 그 단어
    아래 미검수 뜻을 더한다. 기존 단어가 없으면 사전 항목 없는 단어와 뜻을 만든다. 호출이
    실패하거나 답이 틀린 단어는 빼고, 분석은 계속한다.
    """
    s = sentence
    # 사전형·읽기는 공용 word에 들어가므로 문장 전체를 인용한 답은 묻기 전에 뺀다.
    new_words = {
        token: answer
        for token, answer in new_words.items()
        if not _quotes_whole_sentence(answer, s.key_text, s.content_tokens)
    }
    if not new_words or job_outdated():
        return {}
    asked, items = [], []
    for word_id, (token, (form, reading)) in enumerate(sorted(new_words.items())):
        candidates = words.find_again(form, reading)
        asked.append((token, form, reading, candidates))
        items.append(
            {
                "word_id": word_id,
                "token_id": token,
                "dictionary_form": form,
                "reading": reading,
                "candidates": words.llm_candidates(candidates),
            }
        )
    try:
        result = client.define_words(s.key_text, items)
    except BusinessError as e:
        log_business_error(e)
        return {}
    answers = _validate_definitions(
        result, {i: {c.sense.id for c in cands} for i, (*_, cands) in enumerate(asked)}
    )
    chosen = {}
    for word_id, (sense_id, meaning, sense_tags, word_tags) in answers.items():
        token, form, reading, candidates = asked[word_id]
        # 새 뜻은 공용 테이블에 들어가므로 문장 전체를 인용한 뜻은 그 단어만 뺀다.
        if meaning and _quotes_whole_sentence([meaning], s.key_text, s.content_tokens):
            continue
        if sense_id is None:
            # 다시 찾은 단어가 여럿이면 앞의 것(흔한 단어 → JMdict 번호 순)에 더한다.
            word = (
                candidates[0].sense.word
                if candidates
                else words.get_or_make_word(form, reading, word_tags)
            )
            sense_id = words.add_llm_sense(word, meaning, sense_tags).id
        chosen[token] = sense_id
    return chosen


def make_meanings(client, sense_ids):
    """고른 뜻 가운데 한국어 뜻이 없는 뜻을 LLM 호출 한 번(word_gloss)으로 만든다(#97).

    실패하거나 응답이 틀리면 만들지 못한 뜻만 생성 실패로 둔다.
    """
    senses = words.missing_meanings(sense_ids)
    if not senses:
        return
    asked = [sense.id for sense in senses]
    try:
        result = client.gloss_words([words.gloss_input(sense) for sense in senses])
    except BusinessError as e:
        log_business_error(e)
        result = None
    words.save_meanings(asked, _validate_meanings(result, set(asked)))
