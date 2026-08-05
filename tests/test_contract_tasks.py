import pytest

from tests.contract import create_project, create_task, list_tasks


def test_create_task_in_member_project(call, make_user):
    user = make_user()
    project = create_project(call, user)
    task = create_task(call, user, project["id"], name="Write spec")
    assert task["name"] == "Write spec"
    assert task["projectID"] == project["id"]


def test_create_task_requires_project_id(call, make_user):
    user = make_user()
    response = call(
        "post", "/api/v1/tasks/", token=user.token, body={"name": "x", "durationMinutes": 1}
    )
    assert response.status_code == 400


def test_create_task_for_foreign_project_is_forbidden(call, make_user):
    owner = make_user()
    project = create_project(call, owner)
    outsider = make_user()
    response = call(
        "post",
        "/api/v1/tasks/",
        token=outsider.token,
        body={"projectID": project["id"], "name": "x", "durationMinutes": 1},
    )
    assert response.status_code == 403


def test_list_tasks_returns_member_tasks(call, make_user):
    user = make_user()
    project = create_project(call, user)
    create_task(call, user, project["id"], name="Visible")
    tasks = list_tasks(call, user)
    assert any(t["name"] == "Visible" for t in tasks.values())


def test_list_tasks_empty_is_rejected(call, make_user):
    user = make_user()
    create_project(call, user)
    assert call("get", "/api/v1/tasks/", token=user.token).status_code == 400


def test_update_task_by_member(call, make_user):
    user = make_user()
    project = create_project(call, user)
    task = create_task(call, user, project["id"])
    response = call(
        "put",
        "/api/v1/tasks/",
        token=user.token,
        body={"id": task["id"], "name": "Updated"},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Updated"


def test_update_task_requires_id(call, make_user):
    user = make_user()
    response = call("put", "/api/v1/tasks/", token=user.token, body={"name": "x"})
    assert response.status_code == 400


@pytest.mark.mongomock_gap
def test_update_missing_task_is_404(call, make_user):
    user = make_user()
    create_project(call, user)
    response = call(
        "put",
        "/api/v1/tasks/",
        token=user.token,
        body={"id": "0123456789abcdef01234567", "name": "x"},
    )
    assert response.status_code == 404


def test_update_task_in_foreign_project_is_forbidden(call, make_user):
    owner = make_user()
    project = create_project(call, owner)
    task = create_task(call, owner, project["id"])
    outsider = make_user()
    response = call(
        "put",
        "/api/v1/tasks/",
        token=outsider.token,
        body={"id": task["id"], "name": "x"},
    )
    assert response.status_code == 403


def test_delete_task_default_reparents_children(call, make_user):
    user = make_user()
    project = create_project(call, user)
    grandparent = create_task(call, user, project["id"], name="A")
    parent = create_task(call, user, project["id"], name="B", parentTaskID=grandparent["id"])
    child = create_task(call, user, project["id"], name="C", parentTaskID=parent["id"])

    response = call("delete", f"/api/v1/tasks/?id={parent['id']}", token=user.token)
    assert response.status_code == 200

    tasks = list_tasks(call, user)
    assert parent["id"] not in tasks
    assert tasks[child["id"]]["parentTaskID"] == grandparent["id"]


def test_delete_task_with_children_removes_subtree(call, make_user):
    user = make_user()
    project = create_project(call, user)
    root = create_task(call, user, project["id"], name="A")
    middle = create_task(call, user, project["id"], name="B", parentTaskID=root["id"])
    create_task(call, user, project["id"], name="C", parentTaskID=middle["id"])

    response = call(
        "delete", f"/api/v1/tasks/?id={root['id']}&deleteChildren=true", token=user.token
    )
    assert response.status_code == 200
    assert call("get", "/api/v1/tasks/", token=user.token).status_code == 400


def test_delete_tasks_by_project(call, make_user):
    user = make_user()
    project = create_project(call, user)
    create_task(call, user, project["id"], name="A")
    create_task(call, user, project["id"], name="B")

    response = call(
        "delete", f"/api/v1/tasks/?projectID={project['id']}", token=user.token
    )
    assert response.status_code == 200
    assert call("get", "/api/v1/tasks/", token=user.token).status_code == 400


def test_delete_tasks_requires_id_or_project(call, make_user):
    user = make_user()
    response = call("delete", "/api/v1/tasks/", token=user.token)
    assert response.status_code == 400
