"""확장 버전: 확장이 요청마다 X-Dragram-Version을 보내면 토큰에 남기고, 최소 확장 버전보다
낮으면 EXTENSION:UPDATE_REQUIRED로 거부한다(#349)."""

import pytest
from django.test import Client

from accounts.models import ExtensionToken
from tests.accounts.test_extension_tokens import REVOKE, bearer, issue, web_session

pytestmark = pytest.mark.django_db

NAMES = "/api/names/"
UPDATE_REQUIRED = (426, {"error": "EXTENSION:UPDATE_REQUIRED"})


def token():
    return issue(*web_session())


def get_names(token, version=None):
    headers = bearer(token)
    if version is not None:
        headers["HTTP_X_DRAGRAM_VERSION"] = version
    return Client().get(NAMES, **headers)


def stored_version():
    return ExtensionToken.objects.get().extension_version


@pytest.mark.parametrize("version", [None, "0.0.1", "garbage"])
def test_without_a_minimum_every_version_is_served(version):
    assert get_names(token(), version).status_code == 200


@pytest.mark.parametrize(
    ("version", "status"),
    [
        ("0.2.9", 426),
        ("0.3.0", 200),
        ("0.3", 200),
        ("0.3.0.1", 200),
        ("1.0.0", 200),
        # 자리마다 숫자로 비교한다.
        ("0.10.0", 200),
        # 헤더가 없거나 형식이 틀리면 낮은 버전과 같다.
        (None, 426),
        ("", 426),
        ("0.3.0-beta", 426),
        ("1.2.3.4.5", 426),
        ("v1.0.0", 426),
    ],
)
def test_versions_below_the_minimum_need_an_update(settings, version, status):
    settings.MIN_EXTENSION_VERSION = "0.3.0"

    response = get_names(token(), version)

    assert response.status_code == status
    if status == 426:
        assert (response.status_code, response.json()) == UPDATE_REQUIRED


def test_dotted_numbers_compare_by_each_part(settings):
    settings.MIN_EXTENSION_VERSION = "0.10.0"

    assert get_names(token(), "0.9.0").status_code == 426


def test_update_required_does_not_disconnect_the_extension(settings):
    settings.MIN_EXTENSION_VERSION = "0.3.0"
    current = token()

    assert get_names(current, "0.2.0").status_code == 426
    assert get_names(current, "0.3.0").status_code == 200


def test_unusable_token_needs_login_before_an_update(settings):
    settings.MIN_EXTENSION_VERSION = "0.3.0"

    response = get_names("unknown-token", "0.2.0")

    assert (response.status_code, response.json()) == (401, {"error": "AUTH:LOGIN_REQUIRED"})


def test_extension_logout_works_on_an_old_extension(settings):
    settings.MIN_EXTENSION_VERSION = "0.3.0"

    response = Client().post(REVOKE, **bearer(token()))

    assert response.status_code == 204
    assert ExtensionToken.objects.get().revoked_at is not None


def test_token_keeps_the_last_extension_version():
    current = token()
    assert stored_version() is None

    get_names(current, "0.3.0")
    assert stored_version() == "0.3.0"

    get_names(current, "0.4.0")
    assert stored_version() == "0.4.0"

    # 헤더가 없거나 형식이 틀리면 헤더를 보내지 않은 확장(0.2.0 이하)으로 남긴다.
    get_names(current, "garbage")
    assert stored_version() is None


def test_rejected_requests_still_record_the_version(settings):
    settings.MIN_EXTENSION_VERSION = "0.3.0"
    current = token()

    get_names(current, "0.2.5")

    assert stored_version() == "0.2.5"


def test_same_version_is_not_written_again(django_assert_num_queries):
    current = token()
    get_names(current, "0.3.0")

    # 토큰 읽기, 이름 목록. 마지막 사용 시각도 오늘 이미 바뀌었다.
    with django_assert_num_queries(2):
        get_names(current, "0.3.0")


def test_admin_lists_and_filters_tokens_by_extension_version(admin_client):
    old, new = token(), issue(*web_session("other@example.com"))
    get_names(old, "0.2.0")
    get_names(new, "0.3.0")
    url = "/admin/accounts/extensiontoken/"

    page = admin_client.get(url).content.decode()
    filtered = admin_client.get(url, {"extension_version": "0.2.0"}).content.decode()

    assert "0.2.0" in page and "0.3.0" in page
    assert "me@example.com" in filtered and "other@example.com" not in filtered
    # 토큰 해시는 보이지 않는다.
    assert ExtensionToken.objects.first().token_hash not in page
