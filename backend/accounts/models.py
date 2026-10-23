from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """사용자(schema users, ADR 0004). 같은 사람인지는 이메일이 아니라 google_sub로 판단한다.

    createsuperuser로 만든 관리자는 google_sub가 없고 비밀번호로 admin에 들어간다. Google로
    가입한 사용자는 비밀번호를 쓸 수 없다.
    """

    google_sub = models.CharField(max_length=255, null=True, unique=True)  # noqa: DJ001


class ExtensionToken(models.Model):
    """확장이 분석 API를 부를 때 쓰는 토큰(#109). 웹에서 연결할 때마다 하나 만든다.

    원본은 발급 응답에만 싣고 DB에는 SHA-256 해시만 둔다. 마지막 사용 후 90일이 지나거나
    폐기되면 쓸 수 없다.
    """

    token_hash = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="extension_tokens")
    # 발급한 웹 로그인 세션. 웹 로그아웃이 그 세션이 발급한 토큰만 폐기한다.
    session_key = models.CharField(max_length=40)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True)

    class Meta:
        indexes = [models.Index(fields=["session_key"], name="extension_token_session")]

    def __str__(self):
        return f"확장 토큰 {self.pk}"
