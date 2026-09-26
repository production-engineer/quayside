import pytest

from tests.contract import create_project, status_ids


def test_get_statuses_for_member_project(call, make_user):
    user = make_user()
    project = create_project(call, user)
    response = call(
        "get", f"/api/v1/statuses/?projectID={project['id']}", token=user.token
    )
    assert response.status_code == 200
    names = sorted(s["name"] for s in response.json())
    assert names == ["Done", "In-Progress", "Todo"]


@pytest.mark.fix
def test_create_status(call, make_user):
    user = make_user()
    project = create_project(call, user)
    response = call(
        "post",
        "/api/v1/statuses/",
        token=user.token,
        body={"projectID": project["id"], "name": "Backlog", "color": "A1B2C3", "order": 4},
    )
    assert response.status_code == 201, response.content
    listed = call(
        "get", f"/api/v1/statuses/?projectID={project['id']}", token=user.token
    ).json()
    assert "Backlog" in [s["name"] for s in listed]


@pytest.mark.fix
def test_update_status_persists_rename(call, make_user):
    user = make_user()
    project = create_project(call, user)
    target = status_ids(project)[0]
    response = call(
        "put",
        "/api/v1/statuses/",
        token=user.token,
        body={"projectID": project["id"], "id": target, "name": "Renamed", "color": "323232", "order": 1},
    )
    assert response.status_code == 200, response.content
    listed = call(
        "get", f"/api/v1/statuses/?projectID={project['id']}", token=user.token
    ).json()
    assert "Renamed" in [s["name"] for s in listed]


@pytest.mark.fix
def test_delete_status(call, make_user):
    user = make_user()
    project = create_project(call, user)
    target = status_ids(project)[0]
    response = call(
        "delete",
        f"/api/v1/statuses/?projectID={project['id']}&id={target}",
        token=user.token,
    )
    assert response.status_code == 200, response.content
    listed = call(
        "get", f"/api/v1/statuses/?projectID={project['id']}", token=user.token
    ).json()
    assert target not in [s["id"] for s in listed]
    projects = call("get", "/api/v1/projects/", token=user.token).json()
    assert len(projects) == 1
