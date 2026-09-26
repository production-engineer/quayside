"""End-to-end UI tests: browser -> Django view -> ORM -> PostgreSQL -> rendered template.

These prove the real rendered app works against Postgres after the Mongo->Postgres migration.
They drive a real Chromium browser against pytest-django's `live_server` (a real server
thread sharing a transactional DB) so the JS-rendered pages (kanban board, project name)
and the server-rendered "what's next" components are exercised end to end.

Run only this group:
    DATABASE_URL="postgres://erikwilliams@localhost:5432/quayside" DEBUG_BOOL=True \\
        ./venv/bin/python -m pytest tests/test_ui.py -q

Skip the group (e.g. CI without a browser):
    pytest -m "not ui"
"""

import os

os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

import pytest

from api.models import Project, Status, Task, User
from api.utils import createEncodedApiKey, encryptApiKey

pytestmark = [pytest.mark.ui, pytest.mark.django_db(transaction=True)]


@pytest.fixture(autouse=True)
def plain_static(settings):
    """Serve static files with the basic (non-manifest) storage during UI tests.

    Production uses whitenoise's CompressedManifestStaticFilesStorage, which needs a
    `collectstatic` manifest. Without it the `{% static %}` tag raises and every page
    500s. That is a build-artifact prerequisite, unrelated to the Mongo->Postgres port,
    so for the browser tests we swap in the plain storage and reset Django's cached
    lazy storage objects so the override takes effect immediately.
    """
    from django.contrib.staticfiles import storage as staticfiles_storage_module
    from django.core.files import storage as files_storage_module
    from django.utils.functional import empty

    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
    settings.STATICFILES_STORAGE = (
        "django.contrib.staticfiles.storage.StaticFilesStorage"
    )

    files_storage_module.storages._storages = {}
    staticfiles_storage_module.staticfiles_storage._wrapped = empty
    yield


def seed():
    """Create one user, one project with the 3 default statuses, and recognizable tasks.

    Committed directly via the ORM so the live_server thread (separate DB connection)
    can see the rows. Returns the handles the tests assert against.
    """
    user = User.objects.create(email="ui-tester@example.com", username="uitester")
    api_token = createEncodedApiKey(str(user.id))
    user.apiKey = encryptApiKey(api_token)
    user.save()

    project = Project.objects.create(name="Harbor Build", userIDs=[user.id])

    statuses = {}
    for spec in Project.create_default_task_statuses():
        statuses[spec["name"]] = Status.objects.create(
            project=project,
            name=spec["name"],
            color=spec["color"],
            order=spec["order"],
        )

    todo_task = Task.objects.create(
        projectID=project, name="Pour the foundation",
        statusId=statuses["Todo"], priority=0,
    )
    in_progress_task = Task.objects.create(
        projectID=project, name="Frame the deck",
        statusId=statuses["In-Progress"], priority=1,
    )
    done_task = Task.objects.create(
        projectID=project, name="Survey the lot",
        statusId=statuses["Done"], priority=2,
    )

    return {
        "user": user,
        "api_token": api_token,
        "project": project,
        "statuses": statuses,
        "todo_task": todo_task,
        "in_progress_task": in_progress_task,
        "done_task": done_task,
    }


def login(page, live_server, api_token, path):
    """Authenticate the browser, then load `path`.

    The realistic route is /dev-login/, which sets the apiToken cookie for the first
    user when settings.DEBUG is True. pytest-django forces DEBUG=False during tests, so
    that DEBUG-only route is not registered and 404s. We therefore set the same apiToken
    cookie directly (the value /dev-login/ would set: the user's decrypted JWT), which is
    exactly what the browser would carry after a real login.
    """
    page.context.add_cookies([{
        "name": "apiToken",
        "value": api_token,
        "url": live_server.url,
        "httpOnly": True,
        "sameSite": "Strict",
    }])
    page.goto(f"{live_server.url}{path}")
    page.wait_for_load_state("networkidle")


def test_landing_page_loads(page, live_server):
    """1. Unauthenticated landing page (welcome.html) renders with status 200 and its heading."""
    response = page.goto(f"{live_server.url}/")
    assert response is not None
    assert response.status == 200
    assert "quayside" in page.title().lower()
    assert page.get_by_text("Ignite Collaborative Productivity").is_visible()
    assert page.get_by_text("quayside.app").first.is_visible()


def test_kanban_board_renders_statuses_and_task(page, live_server):
    """2. After login, the kanban board renders the 3 status columns and a seeded task.

    The board is built client-side by JS that fetches /api/v1/kanban/, so this exercises
    the full path: cookie -> Django API view -> ORM -> Postgres -> JSON -> DOM.
    """
    data = seed()
    project_id = data["project"].id
    login(page, live_server, data["api_token"], f"/project/{project_id}/kanban/")

    columns = page.locator("#columns")
    columns.get_by_text("Todo", exact=True).wait_for(timeout=15000)
    assert columns.get_by_text("Todo", exact=True).is_visible()
    assert columns.get_by_text("In-Progress", exact=True).is_visible()
    assert columns.get_by_text("Done", exact=True).is_visible()

    assert columns.get_by_text("Pour the foundation").is_visible()
    assert columns.get_by_text("Frame the deck").is_visible()
    assert columns.get_by_text("Survey the lot").is_visible()


def test_project_view_shows_name_and_task(page, live_server):
    """3. After login, the project (graph) view renders the project name and a seeded task.

    Project name is set client-side from /api/v1/projects; the seeded task name appears in
    the server-rendered "what's next" panel on the project page.
    """
    data = seed()
    project_id = data["project"].id
    login(page, live_server, data["api_token"], f"/project/{project_id}/graph/")

    name_el = page.locator("#projectName")
    name_el.get_by_text("Harbor Build").wait_for(timeout=15000)
    assert "Harbor Build" in name_el.inner_text()

    assert page.get_by_text("Frame the deck").first.is_visible()


def test_whats_next_panel_shows_in_flight_and_next_up(page, live_server):
    """4. The server-rendered "what's next" panel surfaces in-flight and next-up tasks.

    With Todo/In-Progress/Done statuses: the In-Progress task is "in flight", the Todo
    task is "next up", the Done task appears in neither list.
    """
    data = seed()
    project_id = data["project"].id
    login(page, live_server, data["api_token"], f"/project/{project_id}/graph/")

    panel = page.locator("#whatsNextBody")
    panel.wait_for(timeout=15000)

    assert panel.get_by_text("In flight").is_visible()
    assert panel.get_by_text("Frame the deck").is_visible()

    assert panel.get_by_text("Next up").is_visible()
    assert panel.get_by_text("Pour the foundation").is_visible()

    assert panel.get_by_text("Survey the lot").count() == 0


def test_unauthenticated_project_page_hides_task_data(page, live_server):
    """5. An unauthenticated visit to a protected project page does NOT expose task data.

    apiKeyRequired returns 401 JSON for the protected view, so the project's task names
    and the rendered board never reach the browser.
    """
    data = seed()
    project_id = data["project"].id

    page.goto(f"{live_server.url}/project/{project_id}/kanban/")
    page.wait_for_load_state("networkidle")

    body = page.locator("body").inner_text()
    assert "Pour the foundation" not in body
    assert "Frame the deck" not in body
    assert "Survey the lot" not in body
    assert "No token provided" in body
