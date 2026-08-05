from django.test import SimpleTestCase
from django.urls import resolve, reverse

from api import views as api_views
from app import views as app_views
from quayside import views as quayside_views


class TestAPIUrls(SimpleTestCase):
    def test_get_user_url(self):
        url = reverse("v1-get-user")
        self.assertEqual(url, "/api/v1/users/")
        self.assertEqual(resolve(url).func.view_class, api_views.users.UsersAPIView)

    def test_projects_list_url(self):
        url = reverse("v1-projects-list")
        self.assertEqual(url, "/api/v1/projects/")
        self.assertEqual(resolve(url).func.view_class, api_views.projects.ProjectsAPIView)

    def test_tasks_list_url(self):
        url = reverse("v1-tasks-list")
        self.assertEqual(url, "/api/v1/tasks/")
        self.assertEqual(resolve(url).func.view_class, api_views.tasks.TasksAPIView)

    def test_generated_tasks_url(self):
        url = reverse("v1-generated-tasks")
        self.assertEqual(url, "/api/v1/generatedTasks/")
        self.assertEqual(
            resolve(url).func.view_class, api_views.generatedTasks.GeneratedTasksAPIView
        )

    def test_kanban_url(self):
        url = reverse("v1-kanban-board")
        self.assertEqual(url, "/api/v1/kanban/")
        self.assertEqual(resolve(url).func.view_class, api_views.kanban.KanbanAPIView)

    def test_statuses_url(self):
        url = reverse("v1-status-list")
        self.assertEqual(url, "/api/v1/statuses/")
        self.assertEqual(resolve(url).func.view_class, api_views.statuses.StatusesAPIView)

    def test_feedback_url(self):
        url = reverse("v1-feedback")
        self.assertEqual(url, "/api/v1/feedback/")
        self.assertEqual(resolve(url).func.view_class, api_views.feedback.FeedbackAPIView)


class TestAppUrls(SimpleTestCase):
    routes = [
        ("create-project-view", {}, "/create-project/", app_views.createProjectView),
        ("project-graph-view", {"projectID": "p1"}, "/project/p1/graph/", app_views.projectGraphView),
        ("project-kanban-view", {"projectID": "p1"}, "/project/p1/kanban/", app_views.projectKanbanView),
        ("project-detail-view", {"projectID": "p1"}, "/project/p1/", app_views.editProjectView),
        ("task-detail-view", {"projectID": "p1", "viewType": "graph", "taskID": "t1"}, "/project/p1/graph/task/t1/", app_views.taskView),
        ("create-task-with-parent-view", {"projectID": "p1", "viewType": "graph", "parentTaskID": "t1"}, "/project/p1/graph/create-task/t1/", app_views.taskView),
        ("create-task-tree-view", {"projectID": "p1", "viewType": "graph"}, "/project/p1/graph/create-task/", app_views.taskView),
        ("logout-view", {}, "/welcome/", app_views.logout),
        ("settings-view", {}, "/settings/", app_views.settingsView),
        ("invite-view", {}, "/invite/", app_views.inviteView),
        ("tutorial-view", {}, "/tutorial/", app_views.tutorialView),
        ("marketplace-view", {}, "/marketplace/", app_views.marketplaceView),
        ("feedback-view", {}, "/feedback/", app_views.feedbackView),
        ("authorize", {"provider": "google"}, "/auth/google/", app_views.requestAuth),
        ("offsite-redirect", {}, "/redirect/", app_views.redirectOffSite),
    ]

    def test_routes(self):
        for name, kwargs, expected_path, view_func in self.routes:
            with self.subTest(name=name):
                self.assertEqual(reverse(name, kwargs=kwargs), expected_path)
                self.assertEqual(resolve(expected_path).func, view_func)


class TestRootUrls(SimpleTestCase):
    def test_index_url(self):
        url = reverse("index")
        self.assertEqual(url, "/")
        self.assertEqual(resolve(url).func, quayside_views.index)
