import pytest

from tests.contract import create_project


def test_create_feedback(call, make_user):
    user = make_user()
    project = create_project(call, user)
    response = call(
        "post",
        "/api/v1/feedback/",
        token=user.token,
        body={"userID": user.id, "projectID": project["id"], "mood": 4, "explanation": "ok"},
    )
    assert response.status_code == 201, response.content
    assert response.json()["projectID"] == project["id"]


def test_create_feedback_for_other_user_is_rejected(call, make_user):
    user = make_user()
    other = make_user()
    project = create_project(call, user)
    response = call(
        "post",
        "/api/v1/feedback/",
        token=user.token,
        body={"userID": other.id, "projectID": project["id"], "mood": 1},
    )
    assert response.status_code == 401


def test_create_feedback_requires_user_and_project(call, make_user):
    user = make_user()
    response = call(
        "post", "/api/v1/feedback/", token=user.token, body={"mood": 2}
    )
    assert response.status_code == 400


def _seed_feedback(call, user, project_id):
    return call(
        "post",
        "/api/v1/feedback/",
        token=user.token,
        body={"userID": user.id, "projectID": project_id, "mood": 3},
    ).json()


@pytest.mark.fix
def test_get_feedback_by_project(call, make_user):
    user = make_user()
    project = create_project(call, user)
    _seed_feedback(call, user, project["id"])
    response = call(
        "get", f"/api/v1/feedback/?projectID={project['id']}", token=user.token
    )
    assert response.status_code == 200, response.content
    assert len(response.json()) == 1


@pytest.mark.fix
def test_delete_feedback_by_id(call, make_user):
    user = make_user()
    project = create_project(call, user)
    feedback = _seed_feedback(call, user, project["id"])
    response = call("delete", f"/api/v1/feedback/?id={feedback['id']}", token=user.token)
    assert response.status_code == 200, response.content


@pytest.mark.fix
def test_delete_feedback_by_project(call, make_user):
    user = make_user()
    project = create_project(call, user)
    _seed_feedback(call, user, project["id"])
    response = call(
        "delete", f"/api/v1/feedback/?projectID={project['id']}", token=user.token
    )
    assert response.status_code == 200, response.content
