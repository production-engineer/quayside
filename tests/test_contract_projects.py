import pytest

from tests.contract import create_project


def test_create_project_seeds_default_statuses(call, make_user):
    user = make_user()
    project = create_project(call, user, name="Launch")
    assert project["name"] == "Launch"
    names = sorted(s["name"] for s in project["taskStatuses"])
    assert names == ["Done", "In-Progress", "Todo"]


def test_create_project_requires_only_own_userid(call, make_user):
    user = make_user()
    response = call("post", "/api/v1/projects/", token=user.token, body={"name": "X"})
    assert response.status_code == 400


def test_create_project_rejects_foreign_userid(call, make_user):
    user = make_user()
    other = make_user()
    response = call(
        "post",
        "/api/v1/projects/",
        token=user.token,
        body={"name": "X", "userIDs": [user.id, other.id]},
    )
    assert response.status_code == 400


def test_list_projects_returns_member_projects(call, make_user):
    user = make_user()
    create_project(call, user, name="Mine")
    response = call("get", "/api/v1/projects/", token=user.token)
    assert response.status_code == 200
    assert "Mine" in [p["name"] for p in response.json()]


def test_list_projects_excludes_non_member(call, make_user):
    owner = make_user()
    create_project(call, owner, name="Secret")
    outsider = make_user()
    response = call("get", "/api/v1/projects/", token=outsider.token)
    assert response.status_code == 400


def test_update_project_by_member(call, make_user):
    user = make_user()
    project = create_project(call, user)
    response = call(
        "put",
        "/api/v1/projects/",
        token=user.token,
        body={"id": project["id"], "name": "Renamed"},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Renamed"


def test_update_project_by_non_member_is_forbidden(call, make_user):
    owner = make_user()
    project = create_project(call, owner)
    outsider = make_user()
    response = call(
        "put",
        "/api/v1/projects/",
        token=outsider.token,
        body={"id": project["id"], "name": "Hijack"},
    )
    assert response.status_code == 403


def test_update_project_requires_id(call, make_user):
    user = make_user()
    response = call("put", "/api/v1/projects/", token=user.token, body={"name": "X"})
    assert response.status_code == 400


@pytest.mark.mongomock_gap
def test_update_missing_project_is_404(call, make_user):
    user = make_user()
    response = call(
        "put",
        "/api/v1/projects/",
        token=user.token,
        body={"id": "0123456789abcdef01234567", "name": "X"},
    )
    assert response.status_code == 404


def test_delete_project_by_member(call, make_user):
    user = make_user()
    project = create_project(call, user)
    response = call("delete", f"/api/v1/projects/?id={project['id']}", token=user.token)
    assert response.status_code == 200
    assert call("get", "/api/v1/projects/", token=user.token).status_code == 400


def test_delete_project_by_non_member_is_rejected(call, make_user):
    owner = make_user()
    project = create_project(call, owner)
    outsider = make_user()
    response = call(
        "delete", f"/api/v1/projects/?id={project['id']}", token=outsider.token
    )
    assert response.status_code == 401


def test_delete_project_requires_id(call, make_user):
    user = make_user()
    response = call("delete", "/api/v1/projects/", token=user.token)
    assert response.status_code == 400
