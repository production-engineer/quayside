import json
import os
import uuid
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEBUG_BOOL", "True")
os.environ["API_SECRET"] = "UvVKcHXorpBbljC0-1MpcjFLjeAhr5CLDJIk6O-nIeA"

try:
    import mongoengine
    import mongomock
except ImportError:
    mongoengine = None
    mongomock = None

_MONGO_ALIAS = "default"


def _connect_mongomock():
    mongoengine.connect(
        "quayside",
        alias=_MONGO_ALIAS,
        mongo_client_class=mongomock.MongoClient,
        uuidRepresentation="standard",
    )


if mongoengine is not None:
    import api.apps

    if hasattr(api.apps.ApiConfig, "connect_database"):
        def _patched_connect(self):
            _connect_mongomock()

        api.apps.ApiConfig.connect_database = _patched_connect


def _backend_is_django():
    from django.db.models import Model
    from api.models import User

    return isinstance(User, type) and issubclass(User, Model)


@pytest.fixture(autouse=True)
def backend(request):
    if _backend_is_django():
        request.getfixturevalue("db")
        yield
        return
    mongoengine.disconnect_all()
    _connect_mongomock()
    yield
    mongoengine.disconnect_all()


@pytest.fixture
def make_user():
    from api.models import User
    from api.utils import createEncodedApiKey, encryptApiKey

    def _make(**overrides):
        fields = {
            "email": overrides.pop("email", f"u-{uuid.uuid4().hex[:10]}@example.com"),
            "username": overrides.pop("username", "user"),
            "firstName": overrides.pop("firstName", ""),
            "lastName": overrides.pop("lastName", ""),
        }
        fields.update(overrides)
        user = User(**fields)
        user.save()
        uid = str(user.id)
        token = createEncodedApiKey(uid)
        user.apiKey = encryptApiKey(token)
        user.save()
        return SimpleNamespace(obj=user, id=uid, token=token, email=fields["email"])

    return _make


@pytest.fixture
def call(client):
    def _call(method, path, token=None, body=None):
        kwargs = {}
        if token is not None:
            kwargs["HTTP_AUTHORIZATION"] = token
        if body is not None:
            kwargs["data"] = json.dumps(body)
            kwargs["content_type"] = "application/json"
        return getattr(client, method.lower())(path, **kwargs)

    return _call
