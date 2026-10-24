"""확장 토큰: 웹 세션이 발급하고 확장이 Bearer로 분석 API를 부른다(#109)."""

import hashlib
from datetime import datetime, time, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.test import Client
from django.utils import timezone

from accounts import tokens
from accounts import views as account_views
from accounts.models import ExtensionToken
from analysis import views
from analysis.models import UsageLog
from tests.analysis.helpers import read_body

pytestmark = pytest.mark.django_db

User = get_user_model()
TOKENS = "/api/auth/extension-tokens/"
REVOKE = "/api/auth/extension-tokens/revoke/"


def web_session(email="me@example.com"):
    """로그인한 웹 브라우저(CSRF 검사함)와 그 CSRF 헤더"""
    user, _ = User.objects.get_or_create(username=email, defaults={"email": email})
    web = Client(enforce_csrf_checks=True)
    web.force_login(user)
    web.get("/api/auth/me/")
    return web, {"HTTP_X_CSRFTOKEN": web.cookies["csrftoken"].value}


def issue(web, headers):
    return web.post(TOKENS, **headers).json()["token"]


def bearer(token):
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def analyze(token=None, text="私は学生です。"):
    headers = bearer(token) if token else {}
    return Client().post(
        "/api/analyses/", {"text": text}, content_type="application/json", **headers
    )


def test_logged_in_web_session_gets_a_token_and_only_its_hash_is_stored():
    web, headers = web_session()

    response = web.post(TOKENS, **headers)

    token = response.json()["token"]
    assert response.status_code == 201
    # 확장이 다른 계정의 연결인지 가리는 바뀌지 않는 계정 식별자(이메일은 바뀌거나 겹칠 수 있다)
    assert response.json()["account"] == str(User.objects.get().pk)
    stored = ExtensionToken.objects.get()
    assert stored.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert token not in {stored.token_hash, stored.session_key}
    assert stored.user.email == "me@example.com"
    assert stored.session_key == web.session.session_key
    # 연결할 때마다 새 토큰이다. 같은 세션(같은 브라우저의 확장)이 예전에 발급한 토큰은 지워
    # 세션마다 하나만 남긴다.
    assert issue(web, headers) != token
    assert ExtensionToken.objects.count() == 1


def test_issuing_again_keeps_the_working_token_until_the_new_one_is_used(fake_llm):
    # 확장에 새 토큰을 넘기지 못해도(확장이 답하지 않음 등) 쓰던 연결은 끊기지 않는다.
    web, headers = web_session()
    previous = issue(web, headers)
    read_body(analyze(previous))

    current = issue(web, headers)
    assert analyze(previous).status_code == 200

    # 새 토큰이 처음 쓰이면 같은 세션의 예전 토큰을 지운다.
    read_body(analyze(current, "私は先生です。"))
    assert analyze(previous).status_code == 401
    assert ExtensionToken.objects.count() == 1


def test_repeated_issuing_without_use_does_not_pile_up_rows():
    web, headers = web_session()
    for _ in range(5):
        issue(web, headers)

    assert ExtensionToken.objects.count() == 1


def test_disabled_users_extension_logout_still_revokes_the_token():
    web, headers = web_session()
    token = issue(web, headers)
    User.objects.update(is_active=False)

    response = Client().post(REVOKE, **bearer(token))

    assert response.status_code == 204
    assert ExtensionToken.objects.get().revoked_at is not None


def test_issuing_needs_a_login_and_csrf():
    anonymous = Client(enforce_csrf_checks=True)
    anonymous.get("/api/auth/me/")
    response = anonymous.post(TOKENS, HTTP_X_CSRFTOKEN=anonymous.cookies["csrftoken"].value)
    assert (response.status_code, response.json()) == (401, {"error": "AUTH:LOGIN_REQUIRED"})

    web, _ = web_session()
    response = web.post(TOKENS)
    assert (response.status_code, response.json()) == (403, {"error": "AUTH:CSRF_FAILED"})
    assert not ExtensionToken.objects.exists()


def test_valid_token_analyzes_and_usage_log_records_its_owner(fake_llm):
    web, headers = web_session()

    response = analyze(issue(web, headers))

    assert response.status_code == 200
    read_body(response)
    owner = User.objects.get()
    assert {log.user for log in UsageLog.objects.all()} == {owner}
    assert set(UsageLog.objects.values_list("kind", flat=True)) == {"request", "llm"}


@pytest.fixture
def no_analysis(monkeypatch, fake_llm):
    """인증 전에 거부되면 형태소 분석도 LLM도 부르지 않는다."""

    def fail(*args, **kwargs):
        raise AssertionError("형태소 분석을 불렀다")

    monkeypatch.setattr(views, "morphemes", fail)
    yield
    assert fake_llm.all_requests() == []
    assert not UsageLog.objects.exists()


def expire(token):
    ExtensionToken.objects.update(last_used_at=timezone.now() - timedelta(days=91))
    return token


def revoke(token):
    ExtensionToken.objects.update(revoked_at=timezone.now())
    return token


@pytest.mark.parametrize(
    "make_token",
    [lambda token: None, lambda token: "unknown-token", revoke, expire],
    ids=["none", "unknown", "revoked", "expired"],
)
def test_requests_without_a_usable_token_need_login(no_analysis, make_token):
    web, headers = web_session()

    response = analyze(make_token(issue(web, headers)))

    assert (response.status_code, response.json()) == (401, {"error": "AUTH:LOGIN_REQUIRED"})


def test_token_used_within_90_days_still_works(fake_llm):
    web, headers = web_session()
    token = issue(web, headers)
    ExtensionToken.objects.update(last_used_at=timezone.now() - timedelta(days=89))

    assert analyze(token).status_code == 200


def test_last_used_time_changes_once_a_day(fake_llm):
    web, headers = web_session()
    token = issue(web, headers)
    yesterday = timezone.now() - timedelta(days=1)
    ExtensionToken.objects.update(last_used_at=yesterday)

    read_body(analyze(token))
    first = ExtensionToken.objects.get().last_used_at
    read_body(analyze(token, "私は先生です。"))

    assert first > yesterday
    assert ExtensionToken.objects.get().last_used_at == first


def test_extension_logout_revokes_only_that_token(fake_llm):
    # 같은 사용자가 두 브라우저에서 연결했다.
    web, headers = web_session()
    other_web, other_headers = web_session()
    first, second = issue(web, headers), issue(other_web, other_headers)

    response = Client().post(REVOKE, **bearer(first))

    assert response.status_code == 204
    assert analyze(first).status_code == 401
    assert analyze(second).status_code == 200
    assert web.get("/api/auth/me/").json() == {"user": {"email": "me@example.com"}}


def test_extension_logout_needs_a_usable_token():
    response = Client().post(REVOKE, **bearer("unknown-token"))

    assert (response.status_code, response.json()) == (401, {"error": "AUTH:LOGIN_REQUIRED"})


def test_web_logout_revokes_only_tokens_issued_by_that_session(fake_llm):
    web, headers = web_session()
    other_web, other_headers = web_session()
    mine, others = issue(web, headers), issue(other_web, other_headers)

    web.post("/api/auth/logout/", **headers)

    assert analyze(mine).status_code == 401
    assert analyze(others).status_code == 200


def test_issuing_is_refused_when_the_session_logged_out_while_waiting(monkeypatch):
    # 같은 세션의 로그아웃이 먼저 잠금을 잡고 끝난 뒤에 발급이 이어지는 경우
    web, headers = web_session()
    lock = account_views._lock_user

    def logout_wins(user):
        lock(user)
        Session.objects.filter(session_key=web.session.session_key).delete()

    monkeypatch.setattr(account_views, "_lock_user", logout_wins)

    response = web.post(TOKENS, **headers)

    assert (response.status_code, response.json()) == (401, {"error": "AUTH:LOGIN_REQUIRED"})
    assert not ExtensionToken.objects.exists()


def at_local(days_ago, hour, minute):
    """현지 날짜로 days_ago일 전 hour:minute"""
    day = timezone.localdate() - timedelta(days=days_ago)
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


def test_expiry_counts_days_because_last_use_is_kept_once_a_day(fake_llm):
    # 마지막 사용 시각은 그날 처음 쓴 때라, 그날 늦게 또 썼을 수 있다. 90일째 날까지는 쓴다.
    web, headers = web_session()
    token = issue(web, headers)

    ExtensionToken.objects.update(last_used_at=at_local(90, 0, 1))
    assert analyze(token).status_code == 200

    ExtensionToken.objects.update(last_used_at=at_local(91, 23, 59))
    assert analyze(token).status_code == 401


def dev_login(web, headers, email):
    return web.post(
        "/api/auth/dev-login/", {"email": email}, content_type="application/json", **headers
    )


@pytest.fixture
def dev_login_on(settings):
    settings.DEBUG = True
    settings.DEV_LOGIN_ENABLED = True


def fresh_csrf(web):
    web.get("/api/auth/me/")
    return {"HTTP_X_CSRFTOKEN": web.cookies["csrftoken"].value}


def test_logging_in_as_someone_else_revokes_the_previous_users_tokens(fake_llm, dev_login_on):
    web, headers = web_session("a@example.com")
    previous = issue(web, headers)

    dev_login(web, headers, "b@example.com")

    assert analyze(previous).status_code == 401


def test_logging_in_again_as_the_same_user_keeps_tokens_for_the_next_logout(fake_llm, dev_login_on):
    web = Client(enforce_csrf_checks=True)
    dev_login(web, fresh_csrf(web), "a@example.com")
    token = issue(web, fresh_csrf(web))

    dev_login(web, fresh_csrf(web), "a@example.com")

    assert analyze(token).status_code == 200
    # 세션 키가 바뀌어도 다음 웹 로그아웃이 그 토큰을 폐기한다.
    web.post("/api/auth/logout/", **fresh_csrf(web))
    assert analyze(token).status_code == 401


def test_moved_tokens_are_revoked_by_the_new_session_logout():
    # 다시 로그인해 세션 키가 바뀐 경우(테스트 클라이언트는 키를 바꾸지 않아 직접 옮긴다)
    user = User.objects.create(username="a", email="a@example.com")
    raw = tokens.issue(user, "old-session")

    tokens.hand_over_session(user, "old-session", "new-session")
    tokens.revoke_session(user, "new-session")

    assert ExtensionToken.objects.get().revoked_at is not None
    assert raw


def test_logging_in_over_a_disabled_users_session_still_revokes_their_tokens(
    fake_llm, dev_login_on
):
    web, headers = web_session("a@example.com")
    previous = issue(web, headers)
    User.objects.filter(email="a@example.com").update(is_active=False)

    dev_login(web, headers, "b@example.com")
    User.objects.filter(email="a@example.com").update(is_active=True)

    assert analyze(previous).status_code == 401


def test_first_use_racing_a_reissue_does_not_delete_the_new_token(monkeypatch, fake_llm):
    # 확장이 토큰 B를 처음 쓰려고 읽은 직후, 다른 탭이 재발급해 B를 지우고 C를 만든 경우
    web, headers = web_session()
    b_token = issue(web, headers)
    read = tokens._usable_row
    reissued = {}

    def reissue_after_read(request, **kwargs):
        row = read(request, **kwargs)
        reissued["c"] = tokens.issue(row.user, row.session_key)
        return row

    monkeypatch.setattr(tokens, "_usable_row", reissue_after_read)
    assert analyze(b_token).status_code == 401

    monkeypatch.setattr(tokens, "_usable_row", read)
    assert analyze(reissued["c"]).status_code == 200


def test_second_concurrent_first_use_does_not_delete_a_token_issued_in_between(
    monkeypatch, fake_llm
):
    # 같은 새 토큰 B로 두 요청이 동시에 처음 쓰였다. 첫 요청이 정리를 마치고 재발급이 C를
    # 만든 뒤, B를 아직 안 쓴 것으로 읽어 둔 두 번째 요청이 잠금을 잡는다.
    web, headers = web_session()
    b_token = issue(web, headers)
    read = tokens._usable_row
    stale = {}

    def read_before_first_use(request, **kwargs):
        if "row" not in stale:
            stale["row"] = read(request, **kwargs)
            return stale["row"]
        return stale["row"]

    read_body(analyze(b_token))
    c_token = issue(web, headers)
    stale["row"] = ExtensionToken.objects.get(
        token_hash=hashlib.sha256(b_token.encode()).hexdigest()
    )
    stale["row"].last_used_at = None
    monkeypatch.setattr(tokens, "_usable_row", read_before_first_use)

    assert analyze(b_token).status_code == 200

    monkeypatch.setattr(tokens, "_usable_row", read)
    assert analyze(c_token, "私は先生です。").status_code == 200
