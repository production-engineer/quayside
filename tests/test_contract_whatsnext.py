from app.templatetags.whatsnext import whats_next, whats_next_all
from tests.contract import create_project, create_task, status_ids


def test_whats_next_for_seeded_project(call, make_user):
    user = make_user()
    project = create_project(call, user)
    columns = status_ids(project)
    create_task(call, user, project["id"], name="A", statusId=columns[0], priority=0)
    create_task(call, user, project["id"], name="B", statusId=columns[1], priority=0)

    result = whats_next(project["id"])
    assert result["available"] is True
    assert result["total"] == 2
    assert len(result["segments"]) == 3


def test_whats_next_invalid_project_is_unavailable(call, make_user):
    make_user()
    assert whats_next("not-an-objectid")["available"] is False


def test_whats_next_all_for_user(call, make_user):
    user = make_user()
    project = create_project(call, user)
    create_task(call, user, project["id"], name="A")
    result = whats_next_all(user.id)
    assert result["available"] is True
    assert isinstance(result["projects"], list)


def test_whats_next_all_empty_user_is_unavailable(call):
    assert whats_next_all("")["available"] is False
