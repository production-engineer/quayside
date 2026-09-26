"""Shared helpers for the backend-agnostic contract suite.

Every helper drives the public HTTP API so the same call works against the Mongo
(old) and Postgres (new) backends without modification.
"""


def create_project(call, user, **extra):
    body = {"name": "Project", "userIDs": [user.id]}
    body.update(extra)
    response = call("post", "/api/v1/projects/", token=user.token, body=body)
    assert response.status_code == 201, response.content
    return response.json()


def create_task(call, user, project_id, **extra):
    body = {"projectID": project_id, "name": "Task", "durationMinutes": 5}
    body.update(extra)
    response = call("post", "/api/v1/tasks/", token=user.token, body=body)
    assert response.status_code == 201, response.content
    return response.json()[0]


def status_ids(project):
    return [status["id"] for status in sorted(project["taskStatuses"], key=lambda s: s["order"])]


def list_tasks(call, user):
    response = call("get", "/api/v1/tasks/", token=user.token)
    assert response.status_code == 200, response.content
    return {task["id"]: task for task in response.json()}
