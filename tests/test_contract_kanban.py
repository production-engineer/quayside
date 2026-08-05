import pytest

from tests.contract import create_project, create_task, status_ids


def test_get_kanban_groups_tasks(call, make_user):
    user = make_user()
    project = create_project(call, user)
    columns = status_ids(project)
    create_task(call, user, project["id"], name="A", statusId=columns[0], priority=0)
    create_task(call, user, project["id"], name="B", statusId=columns[0], priority=1)

    response = call(
        "get", f"/api/v1/kanban/?projectID={project['id']}", token=user.token
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert len(body["statuses"]) == 3
    assert len(body["taskLists"]) == 3
    assert sum(len(column) for column in body["taskLists"]) == 2


def test_get_kanban_requires_project_id(call, make_user):
    user = make_user()
    response = call("get", "/api/v1/kanban/", token=user.token)
    assert response.status_code == 400


def _status_of(call, user, task_id):
    response = call("get", "/api/v1/tasks/", token=user.token)
    return {t["id"]: t["statusId"] for t in response.json()}[task_id]


def test_update_kanban_moves_task(call, make_user):
    user = make_user()
    project = create_project(call, user)
    columns = status_ids(project)
    create_task(call, user, project["id"], name="A", statusId=columns[0], priority=0)
    moving = create_task(call, user, project["id"], name="B", statusId=columns[0], priority=1)

    response = call(
        "put",
        "/api/v1/kanban/",
        token=user.token,
        body={"id": moving["id"], "statusId": columns[1], "priority": 0},
    )
    assert response.status_code == 200, response.content
    assert _status_of(call, user, moving["id"]) == columns[1]


def test_update_kanban_move_persists_with_null_priority(call, make_user):
    """The board sends priority=null on a plain column move; the status change must
    still persist (regression: None comparison previously aborted the save)."""
    user = make_user()
    project = create_project(call, user)
    columns = status_ids(project)
    moving = create_task(call, user, project["id"], name="A", statusId=columns[0], priority=0)

    response = call(
        "put",
        "/api/v1/kanban/",
        token=user.token,
        body={"id": moving["id"], "statusId": columns[2], "priority": None},
    )
    assert response.status_code == 200, response.content
    assert _status_of(call, user, moving["id"]) == columns[2]


def test_update_kanban_requires_priority(call, make_user):
    user = make_user()
    project = create_project(call, user)
    task = create_task(call, user, project["id"])
    response = call(
        "put",
        "/api/v1/kanban/",
        token=user.token,
        body={"id": task["id"], "statusId": status_ids(project)[0]},
    )
    assert response.status_code == 400


@pytest.mark.fix
def test_get_kanban_empty_project(call, make_user):
    user = make_user()
    project = create_project(call, user)
    response = call(
        "get", f"/api/v1/kanban/?projectID={project['id']}", token=user.token
    )
    assert response.status_code == 200, response.content
    assert sum(len(column) for column in response.json()["taskLists"]) == 0
