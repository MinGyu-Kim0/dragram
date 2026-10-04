from django.contrib.auth import get_user_model

LOCAL_USERNAME = "local"


def local_user():
    return get_user_model().objects.get_or_create(username=LOCAL_USERNAME)[0]
