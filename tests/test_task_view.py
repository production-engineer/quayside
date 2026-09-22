from contextlib import ExitStack
from unittest import mock

import jwt
from django.test import RequestFactory, SimpleTestCase, override_settings
from rest_framework import status

from app import views


def statusesFor(projectID):
    return [
        {"id": f"{projectID}-todo", "name": "To Do"},
        {"id": f"{projectID}-done", "name": "Done"},
    ]


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
)
class TaskViewStatusChoices(SimpleTestCase):
    """
    The status choices a POST validates against must come from the project named in that
    request. Holding them on the view function leaks one request's project into the next.
    """

    def setUp(self):
        self.requests = RequestFactory()
        patches = ExitStack()
        self.addCleanup(patches.close)

        patches.enter_context(
            mock.patch("api.decorators.decodeApiKey", return_value={"userID": "u1"})
        )
        patches.enter_context(
            mock.patch("api.decorators.decryptApiKey", return_value="token")
        )
        patches.enter_context(
            mock.patch.object(jwt, "decode", return_value={"userID": "u1"})
        )
        patches.enter_context(mock.patch("api.decorators.User", mock.MagicMock()))

        patches.enter_context(
            mock.patch.object(
                views.ProjectsAPIView,
                "getProjects",
                return_value=([{"id": "p1", "userIDs": ["u1"]}], status.HTTP_200_OK),
            )
        )
        patches.enter_context(
            mock.patch.object(
                views.UsersAPIView,
                "getUsers",
                return_value=([{"id": "u1", "username": "ada"}], status.HTTP_200_OK),
            )
        )
        self.getStatuses = patches.enter_context(
            mock.patch.object(
                views.StatusesAPIView,
                "getStatuses",
                side_effect=lambda query, token: (
                    statusesFor(query["projectID"]),
                    status.HTTP_200_OK,
                ),
            )
        )
        self.createTasks = patches.enter_context(
            mock.patch.object(
                views.TasksAPIView,
                "createTasks",
                return_value=({}, status.HTTP_201_CREATED),
            )
        )

    def postTask(self, projectID, statusID):
        request = self.requests.post(
            f"/project/{projectID}/kanban/create-task/",
            {"name": "Survey the ice road", "status": statusID, "duration": "2h"},
        )
        request.COOKIES["apiToken"] = "token"
        return views.taskView(request, projectID, "kanban")

    def test_post_validates_against_its_own_project_statuses(self):
        response = self.postTask("p2", "p2-todo")

        self.assertEqual(response.status_code, 302)
        self.getStatuses.assert_called_once_with({"projectID": "p2"}, "token")
        self.createTasks.assert_called_once()
        self.assertEqual(self.createTasks.call_args.args[0]["statusId"], "p2-todo")

    def test_status_choices_are_not_kept_on_the_view(self):
        self.postTask("p2", "p2-todo")

        self.assertFalse(hasattr(views.taskView, "statusData"))

    def getTaskForm(self, projectID):
        request = self.requests.get(f"/project/{projectID}/kanban/create-task/")
        request.COOKIES["apiToken"] = "token"
        return views.taskView(request, projectID, "kanban")

    def test_a_get_for_one_project_does_not_bind_a_later_post_for_another(self):
        self.getTaskForm("p1")

        response = self.postTask("p2", "p2-todo")

        self.assertEqual(response.status_code, 302)
        self.createTasks.assert_called_once()
        self.assertEqual(self.createTasks.call_args.args[0]["statusId"], "p2-todo")

    def test_post_rejects_a_status_from_another_project(self):
        response = self.postTask("p2", "p9-todo")

        self.assertEqual(response.status_code, 200)
        self.createTasks.assert_not_called()
