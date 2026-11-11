"""검수 액션은 변경 권한이 있어야 보인다(#409). 보기 권한만 있는 staff가 미검수 지식을 승인·반려하지
못하게 한다.
"""

import pytest
from django.contrib.auth.models import Permission

pytestmark = pytest.mark.django_db

# (모델, 액션) 액션을 만드는 방식마다 하나씩
ACTIONS = [
    ("grammarpattern", "approve"),  # _review_action
    ("grammarusage", "approve"),  # _review_action
    ("grammarpattern", "link_variant"),
    ("usagerule", "approve"),
    ("word", "mark_reviewed"),  # _meaning_action
    ("wordsense", "approve_senses"),  # _sense_action
]


def offered_actions(client, django_user_model, model, *perms):
    staff = django_user_model.objects.create_user("staff", password="pw", is_staff=True)
    staff.user_permissions.add(
        *Permission.objects.filter(codename__in=[f"{perm}_{model}" for perm in perms])
    )
    client.force_login(staff)
    response = client.get(f"/admin/analysis/{model}/")
    assert response.status_code == 200
    form = response.context["action_form"]
    return set() if form is None else {name for name, _ in form.fields["action"].choices}


@pytest.mark.parametrize(("model", "action"), ACTIONS)
def test_review_action_is_hidden_from_view_only_staff(client, django_user_model, model, action):
    assert action not in offered_actions(client, django_user_model, model, "view")


@pytest.mark.parametrize(("model", "action"), ACTIONS)
def test_review_action_is_offered_to_staff_who_can_change(
    client, django_user_model, model, action
):
    assert action in offered_actions(client, django_user_model, model, "view", "change")
