"""구간 매칭 행 만들기와 저장 검사. 작업자와 재매칭이 함께 쓴다."""

from analysis import patterns
from analysis.models import GrammarPattern, ReviewStatus, SpanMatch, UsageRule
from analysis.sentence import _pattern_statuses
from errors import AnalysisError, BusinessError


def _usage_owner(pattern):
    """그 패턴의 구간에 새 용법을 더할 패턴. 연결된 회화체면 원형이다(#63)."""
    return pattern.variant_of or pattern


def _basis_changed(rows, rules):
    """판정 근거로 읽은 상태가 저장 직전에 바뀌어 이 구간들을 저장하면 안 되는가(#63).

    넷을 본다. 원형 연결이 분석할 때와 다른 구간이 있거나(_links_changed), LLM 없이 확정한
    구간의 용법 완결이 풀렸거나(이번 저장이 같은 원형에 새 용법을 더해 풀었을 수 있다), 판별
    규칙으로 확정한 근거(규칙·패턴·용법의 승인)가 무너졌거나, 분석할 때 읽은 승인된 판별
    규칙(rules, _approved_rules)에 없던 규칙이 그 구간들의 패턴에 승인됐다. 그대로
    저장하면 그 stale 처리가 이 트랜잭션의 구간을 보지 못해 다시 분석될 계기가 없다.
    """
    closed = {row.pattern_id for row in rows if row.decided_by == SpanMatch.DecidedBy.SINGLE_USAGE}
    opened = GrammarPattern.objects.filter(pk__in=closed, usage_closed=False).exists()
    # 판별 규칙으로 확정한 구간의 규칙·패턴(원형 포함)·용법이 그사이 승인 상태가 아니게 됐다(#55).
    ruled = UsageRule.objects.filter(
        pk__in={row.rule_id for row in rows if row.rule_id is not None}
    ).select_related("usage", "pattern__variant_of")
    unusable = any(
        rule.status != UsageRule.Status.APPROVED
        or rule.usage.status != ReviewStatus.APPROVED
        or _pattern_statuses(rule.pattern) != {ReviewStatus.APPROVED}
        for rule in ruled
    )
    read = {rule.pk for pattern_rules in rules.values() for rule in pattern_rules}
    approved = (
        UsageRule.objects.filter(
            status=UsageRule.Status.APPROVED,
            pattern__in={row.pattern_id for row in rows if row.pattern_id},
        )
        .exclude(pk__in=read)
        .exists()
    )
    return opened or unusable or approved or _links_changed(rows)


def _links_changed(rows):
    """구간마다 분석할 때 읽은 원형 연결이 지금과 다른가(#63). 판정 상태와 상관없이 모두 본다.

    분석하는 사이 연결·해제가 일어나면 후보·용법이 바뀐 패턴 기준이 된다. 그대로 저장하면 연결·
    해제의 stale 처리가 저장 전에 지나가 다시 분석될 계기가 없어서 저장하지 않는다. 저장하는
    트랜잭션은 맨 처음 patterns.lock_links()로 연결·해제와 직렬화하므로, 여기서 읽은 연결은
    커밋할 때까지 바뀌지 않는다.
    """
    read = [(row.pattern_id, row.pattern.variant_of_id) for row in rows if row.pattern_id]
    current = dict(
        GrammarPattern.objects.filter(pk__in={pk for pk, _ in read}).values_list(
            "pk", "variant_of_id"
        )
    )
    return any(current.get(pk) != base for pk, base in read)


def _stored_keys(analysis):
    """저장된 구간의 열쇠 (패턴 ID, 키 텍스트 start, end)들. 패턴이 있는 모든 상태를 센다(#41)."""
    return set(
        analysis.span_matches.filter(pattern__isnull=False).values_list(
            "pattern_id", "start_offset", "end_offset"
        )
    )


def _is_place_conflict(error):
    """같은 자리의 같은 패턴 구간을 두 번 넣어 구간 유일성 제약에 걸렸는가(#41)."""
    diag = getattr(error.__cause__, "diag", None)
    return getattr(diag, "constraint_name", None) == "span_match_place_unique"


class _PatternTaken(Exception):  # noqa: N818
    """새 패턴을 등록하는 사이 다른 요청이 같은 조건의 패턴을 먼저 등록했다."""


def closed_rows(sentence, saved, closed):
    """LLM 없이 확정한 구간(구간, 후보 ID, 용법, 판별 규칙)들의 구간 매칭."""
    rows = []
    for span, candidate_id, usage, rule in closed:
        start, end = sentence.key_span(span.start_token, span.end_token)
        rows.append(
            SpanMatch(
                analysis=saved,
                pattern=span.pattern,
                usage=usage,
                start_offset=start,
                end_offset=end,
                state=SpanMatch.State.DECIDED,
                decided_by=(SpanMatch.DecidedBy.RULE if rule else SpanMatch.DecidedBy.SINGLE_USAGE),
                rule=rule,
                candidates=[{"candidate_id": candidate_id, "usage_id": usage.id}],
            )
        )
    return rows


def judged_rows(sentence, saved, span_list, answers, alternatives):
    """LLM이 판정한 후보 구간들의 구간 매칭. 미발견 구간의 새 용법은 이때 더한다.

    (구간 매칭들, 매칭 자격을 새로 얻은 패턴이 있는가)를 돌려준다. 자격을 얻었으면 호출하는
    쪽이 분석 행을 잠그기 전에 패턴 세트 버전을 올린다. alternatives는 해석 갈림 구간의
    {순번: [(대안 용법, 대안 번역)]}이다.
    """
    judged = list(zip(span_list, answers, strict=True))
    # 기존 용법으로 설명되지 않는 구간은 같은 패턴 아래 새 용법을 더한다. 동시 요청이 같은
    # 이름의 용법을 서로 다른 순서로 더하면 유일성 대기가 엇갈려 교착이 나므로 (패턴, 이름)
    # 순서로 더한다. 이 응답에서 이미 더한 (패턴, 이름)이면 그 용법을 함께 쓴다.
    # 연결된 회화체 구간의 새 용법은 원형 아래에 더하고, 이름과 순서도 원형 기준이다(#63).
    additions = sorted(
        (_usage_owner(span.pattern).morpheme_key, new_usage["usage_name"], index)
        for index, (span, (_, _, new_usage)) in enumerate(judged)
        if new_usage is not None
    )
    # 새 용법을 더할 패턴들(과 그 회화체들)을 처음에 한 번에 잠근다. 하나씩 잠그면 연결·해제나
    # 다른 분석과 잠금 순서가 엇갈릴 수 있다(#63).
    if additions:
        patterns.lock_families(*(_usage_owner(judged[index][0].pattern) for *_, index in additions))
    # 용법 예문은 같은 (패턴, 이름)의 답 중 검사를 통과한 첫 예문이다(check_examples).
    usage_examples = {}
    for _, name, index in additions:
        span, (_, _, new_usage) = judged[index]
        owner = _usage_owner(span.pattern)
        if usage_examples.get((owner.id, name)) is None:
            usage_examples[owner.id, name] = new_usage["checked_example"]
    added, new_usages = {}, {}
    activated = False
    for _, name, index in additions:
        span, (_, _, new_usage) = judged[index]
        owner = _usage_owner(span.pattern)
        # 같은 원형을 가리키는 회화체 구간들은 같은 새 용법을 함께 쓴다. 나머지 구간의 연결
        # 상태는 저장 직전에 함께 본다(_links_changed).
        if (owner.id, name) not in added:
            added[owner.id, name], matchable = patterns.add_usage(
                owner,
                name,
                new_usage["explanation_ko"],
                usage_examples[owner.id, name],
                matched=span.pattern,
                korean_equivalent=new_usage["korean_equivalent"],
                function_tags=new_usage["function_tags"],
            )
            activated |= matchable
        new_usages[index] = added[owner.id, name]
    rows = []
    for index, (span, (state, usage, new_usage)) in enumerate(judged):
        start, end = sentence.key_span(span.start_token, span.end_token)
        if new_usage is not None:
            usage = new_usages[index]
            if usage is not None:
                state = SpanMatch.State.DECIDED
        alts = None
        if state == SpanMatch.State.DIVERGENT:
            alts = [
                {"usage_id": alt.id, "translation_ko": translation}
                for alt, translation in alternatives[index]
            ]
        rows.append(
            SpanMatch(
                analysis=saved,
                pattern=span.pattern,
                usage=usage,
                start_offset=start,
                end_offset=end,
                state=state,
                decided_by=SpanMatch.DecidedBy.LLM,
                candidates=[
                    {"candidate_id": candidate_id, "usage_id": u.id}
                    for candidate_id, u in span.candidates
                ],
                alternatives=alts,
            )
        )
    return rows, activated


def span_matches(sentence, saved, validated, final):
    """판정한 후보 구간과 새 구문을 구간 매칭으로 만든다. 새 구문은 이때 등록한다. 넣을 구간
    매칭을 돌려주고, 호출하는 쪽이 분석 행을 잠근 뒤 넣는다.

    패턴 생성 규칙을 어긴 새 구문은 미발견으로 남겨 보이지 않는다. 그사이 다른 요청이 같은
    조건의 패턴을 먼저 등록했으면 _PatternTaken을 던져 다시 묻게 한다(final이면 미발견).
    """
    # 다른 요청이 먼저 저장해 다시 묻기를 건너뛰었는데, 그 행이 저장 전에 stale이 되어 이
    # 결과로 다시 채우게 된 경우다. 다시 묻지 않은 해석 갈림·미확정은 저장하지 않는다.
    if not validated.get("rechecked") and any(
        state in (SpanMatch.State.DIVERGENT, SpanMatch.State.UNRESOLVED)
        for state, _, _ in validated["spans"]
    ):
        raise BusinessError(AnalysisError.FAILED, "다시 묻지 않은 해석 갈림·미확정 구간")
    rows, activated = judged_rows(
        sentence,
        saved,
        validated["span_list"],
        validated["spans"],
        validated.get("alternatives", {}),
    )
    rows = closed_rows(sentence, saved, sentence.closed_spans) + rows

    # 동시 요청이 같은 패턴들을 서로 다른 순서로 등록하면 morpheme_key 유일성 대기가
    # 엇갈려 교착이 나므로, 등록은 morpheme_key 순서로 한다.
    def order(proposal):
        conditions = proposal["conditions"]
        return patterns.morpheme_key(conditions) if conditions is not None else ""

    # 같은 조건이 이 응답에서 두 번 나오면 패턴은 한 번만 등록한다. 뒤 자리는 용법 이름이
    # 같으면 그 용법을 함께 쓰고, 다르면 같은 패턴 아래 새 용법으로 더한다. 이 패턴은 이번
    # 트랜잭션에서 만들어 다른 요청이 용법을 더할 수 없으므로 순서를 맞출 필요가 없다.
    registered = {}
    proposals = sorted(validated["new_patterns"], key=order)
    # 같은 조건의 제안 중 검사를 통과한 첫 예문(check_examples)이 패턴의 활성화 근거가
    # 되고, 같은 조건·같은 용법 이름의 제안 중 통과한 첫 예문이 그 용법의 예문이 된다(다른
    # 용법의 예문은 용법 예문으로 쓰지 않는다).
    examples = [p.get("checked_example") for p in proposals]
    test_examples, usage_examples = {}, {}
    for proposal, example in zip(proposals, examples, strict=True):
        if example is not None:
            test_examples.setdefault(order(proposal), example)
            usage_examples.setdefault((order(proposal), proposal["usage_name"]), example)
    for proposal in proposals:
        example = usage_examples.get((order(proposal), proposal["usage_name"]))
        ids = [token for token, _ in proposal["tokens"]]
        start, end = sentence.key_span(min(ids), max(ids))
        pattern, usage = proposal["existing"], None
        if order(proposal) in registered:
            pattern, usages = registered[order(proposal)]
            name = proposal["usage_name"]
            if name not in usages and usages:
                usages[name], _ = patterns.add_usage(
                    pattern,
                    name,
                    proposal["explanation_ko"],
                    example,
                    korean_equivalent=proposal["korean_equivalent"],
                    function_tags=proposal["function_tags"],
                )
            usage = usages.get(name)
        elif pattern is None and proposal["conditions"] is not None:
            pattern, usage = patterns.register(
                proposal["conditions"],
                proposal["pattern_name"],
                proposal["usage_name"],
                proposal["explanation_ko"],
                example,
                test_examples.get(order(proposal)),
                proposal["korean_equivalent"],
                proposal["function_tags"],
                connection_form=proposal["connection_form"],
            )
            if usage is None and not final:
                raise _PatternTaken
            registered[order(proposal)] = (
                pattern,
                {proposal["usage_name"]: usage} if usage else {},
            )
            activated |= usage is not None and pattern.is_active
        rows.append(
            SpanMatch(
                analysis=saved,
                pattern=pattern,
                usage=usage,
                start_offset=start,
                end_offset=end,
                state=SpanMatch.State.DECIDED if usage else SpanMatch.State.UNFOUND,
                decided_by=SpanMatch.DecidedBy.LLM,
            )
        )
    if activated:
        # 버전 행은 등록을 모두 마친 뒤 마지막에 잠근다(잠근 채 다른 패턴을 기다리지 않게).
        patterns.raise_pattern_set_version()
    return rows
