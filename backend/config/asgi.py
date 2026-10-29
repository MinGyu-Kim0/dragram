"""
ASGI config for config project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os

from django.conf import settings
from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_asgi_application()
# runserver가 하던 정적 파일(관리자 CSS·JS) 제공을 개발용 uvicorn에서도 한다. 운영은 nginx가 맡는다.
if settings.DEBUG:
    application = ASGIStaticFilesHandler(application)
