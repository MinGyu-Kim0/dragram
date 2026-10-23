from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """사용자(schema users, ADR 0004). 같은 사람인지는 이메일이 아니라 google_sub로 판단한다.

    createsuperuser로 만든 관리자는 google_sub가 없고 비밀번호로 admin에 들어간다. Google로
    가입한 사용자는 비밀번호를 쓸 수 없다.
    """

    google_sub = models.CharField(max_length=255, null=True, unique=True)  # noqa: DJ001
