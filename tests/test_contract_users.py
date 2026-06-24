import json

import pytest


def test_unauthenticated_request_is_rejected(call):
    assert call("get", "/api/v1/users/").status_code == 401


def test_invalid_token_is_rejected(call):
    assert call("get", "/api/v1/users/", token="not-a-real-token").status_code == 401


def test_user_can_fetch_own_full_record(call, make_user):
    user = make_user(firstName="Ada")
    response = call("get", f"/api/v1/users/?id={user.id}", token=user.token)
    assert response.status_code == 200
    record = response.json()[0]
    assert record["id"] == user.id
    assert record["email"] == user.email
    assert record["firstName"] == "Ada"


def test_fetching_other_user_returns_limited_fields(call, make_user):
    owner = make_user()
    other = make_user(firstName="Grace")
    response = call("get", f"/api/v1/users/?id={other.id}", token=owner.token)
    assert response.status_code == 200
    record = response.json()[0]
    assert set(record.keys()) == {"id", "email", "username"}
    assert record["id"] == other.id


def test_fetch_other_user_by_email(call, make_user):
    owner = make_user()
    other = make_user()
    response = call("get", f"/api/v1/users/?email={other.email}", token=owner.token)
    assert response.status_code == 200
    assert response.json()[0]["id"] == other.id


def test_get_users_without_filters_is_rejected(call, make_user):
    user = make_user()
    assert call("get", "/api/v1/users/", token=user.token).status_code == 400


def test_create_user_requires_json_content_type(call, make_user, client):
    user = make_user()
    response = client.post(
        "/api/v1/users/",
        data="email=x@y.com",
        content_type="application/x-www-form-urlencoded",
        HTTP_AUTHORIZATION=user.token,
    )
    assert response.status_code == 400


def test_create_user_succeeds(call, make_user):
    user = make_user()
    response = call(
        "post",
        "/api/v1/users/",
        token=user.token,
        body={"email": "new@example.com", "username": "newbie"},
    )
    assert response.status_code == 201, response.content
    assert response.json()["email"] == "new@example.com"


def test_update_own_user(call, make_user):
    user = make_user()
    response = call(
        "put",
        "/api/v1/users/",
        token=user.token,
        body={"id": user.id, "firstName": "Renamed"},
    )
    assert response.status_code == 200
    assert response.json()["firstName"] == "Renamed"


def test_update_other_user_is_forbidden(call, make_user):
    owner = make_user()
    other = make_user()
    response = call(
        "put",
        "/api/v1/users/",
        token=owner.token,
        body={"id": other.id, "firstName": "Hacked"},
    )
    assert response.status_code == 401


def test_update_user_requires_id(call, make_user):
    user = make_user()
    response = call("put", "/api/v1/users/", token=user.token, body={"firstName": "X"})
    assert response.status_code == 400


@pytest.mark.mongomock_gap
def test_duplicate_email_is_rejected(call, make_user):
    """Unique-email enforcement. Correct on real Mongo and Postgres; mongomock does
    not enforce unique indexes, so this is excluded from the Mongo green proof."""
    user = make_user()
    call(
        "post",
        "/api/v1/users/",
        token=user.token,
        body={"email": "dup@example.com", "username": "a"},
    )
    response = call(
        "post",
        "/api/v1/users/",
        token=user.token,
        body={"email": "dup@example.com", "username": "b"},
    )
    assert response.status_code == 400
