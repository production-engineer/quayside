from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.utils.decorators import method_decorator

from api.models import Task
from api.serializers import TaskSerializer
from api.decorators import apiKeyRequired
from api.views.v1.statuses import StatusesAPIView
from api.utils import getAuthorizationToken


@method_decorator(apiKeyRequired, name="dispatch")
class KanbanAPIView(APIView):
    """"
    Get and update a kanban board.
    Includes an endpoint to get a kanban and an endpoint to update a kanban.
    """

    def get(self, request):
        """
        Retrieves an array of task lists for the statuses associated with the project,
        ordered by status.order, and an array of status objects also ordered by `order`.

        Requires 'apiToken' passed in auth header or cookies

        @param {HttpRequest} request - The request object.
            Query Parameters:
                - projectID (objectId str)


        @return: A Response object containing projects tasks grouped by status.

        @response example:
            {
                "statuses": [
                    {"id": 123, "name": "Backlog", "order": 1, "color": "A13D23"},
                    {"id": 423, "name": "Todo", "order": 2, "color": "A13D42"},
                    {"id": 444, "name": "Done", "order": 3, "color": "A13D99"}
                ],
                "taskLists": [
                    # tasks with statusId 123, no statusId, or a statusId not in `statuses`
                    [taskObject, taskObject],
                    # tasks with statusId 423
                    [taskObject],
                    # tasks with statusId 444
                    [taskObject]
                ]
            }

        @example Javascript:

            fetch('quayside.app/api/v1/kanban?projectID=1234');
        """
        responseData, httpStatus = self.getKanban(request.query_params, getAuthorizationToken(request))
        return Response(responseData, status=httpStatus)

    def put(self, request):
        """
        Updates a kanban board.
        Requires 'apiToken' passed in auth header or cookies.

        @param {HttpRequest} request - The request object.
            The request body can contain:
                - id (objectId str) [REQUIRED]
                - statusId (objectId str) [REQUIRED]
                - priority (int) [REQUIRED]

        @return: A response object with the changes made or an error message

        @example Javascript:

            fetch('quayside.app/api/v1/kanban', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({id: '1234', statusId: '5678', priority: 4})
            })

        """
        responseData, httpStatus = self.updateKanban(request.data)
        return Response(responseData, status=httpStatus)

    @staticmethod
    def getKanban(taskData, authorizationToken):
        """
        Service API function that gets the kanban for a project's tasks grouped by status.

        @param taskData     Dict of parameters. Only projectID considered.
        @param authorizationToken      JWT authorization token.
        @return      A tuple of (response_data, http_status).
        """
        if "projectID" not in taskData:
            return "Error: paramter 'projectID' required.", status.HTTP_400_BAD_REQUEST

        projectID = taskData.get("projectID")

        statuses, httpsCode = StatusesAPIView.getStatuses(
            {"projectID": projectID}, authorizationToken
        )
        if httpsCode != status.HTTP_200_OK:
            return statuses, httpsCode

        sorted_statuses = sorted(statuses, key=lambda stat: stat["order"])

        column_index = {stat["id"]: index for index, stat in enumerate(sorted_statuses)}

        task_lists = [[] for _ in sorted_statuses]

        tasks = Task.objects.filter(projectID=projectID)
        for task in tasks:
            index = column_index.get(task.statusId_id, 0)
            task_lists[index].append(task)

        serialized_lists = [
            TaskSerializer(column, many=True).data for column in task_lists
        ]

        return {
            "statuses": sorted_statuses,
            "taskLists": serialized_lists,
        }, status.HTTP_200_OK

    @staticmethod
    def updateKanban(taskData):
        """
        Service API function that moves a task to a new status and priority, shifting the
        priorities of the tasks it displaces.

        @param taskData (dict): Dict containing id, statusId, and priority.
            id (string): Id of the task to update.
            statusId (string): Reference to a status.
            priority (int): The priority to update task to.

        @return:
            A tuple of (response_data, http_status).
        """
        if "id" not in taskData:
            return "Error: paramter 'id' required.", status.HTTP_400_BAD_REQUEST

        if "priority" not in taskData:
            return "Error: parameter 'priority' required.", status.HTTP_400_BAD_REQUEST

        if "statusId" not in taskData:
            return "Error: parameter 'statusId' required.", status.HTTP_400_BAD_REQUEST

        try:
            updating_task = Task.objects.get(id=taskData.get("id"))
        except Task.DoesNotExist:
            return "Task not found with the provided ID.", status.HTTP_404_NOT_FOUND

        project_id = updating_task.projectID_id
        old_status_id = updating_task.statusId_id
        old_priority = updating_task.priority
        new_status_id = taskData.get("statusId") or None

        # The board does not always send a priority (a plain column move). Treat a
        # missing/blank priority as "append to the end of the target column" so the
        # status change still persists instead of failing on a None comparison.
        try:
            new_priority = int(taskData.get("priority"))
        except (TypeError, ValueError):
            new_priority = (
                Task.objects.filter(projectID=project_id, statusId=new_status_id)
                .exclude(id=updating_task.id)
                .count()
            )

        old_status_tasks = []
        if old_priority is not None:
            old_status_tasks = list(
                Task.objects.filter(
                    projectID=project_id,
                    statusId=old_status_id,
                    priority__gt=old_priority,
                )
            )
        new_status_tasks = list(
            Task.objects.filter(
                projectID=project_id,
                statusId=new_status_id,
                priority__gte=new_priority,
            )
        )

        for task in old_status_tasks:
            task.priority -= 1
        for task in new_status_tasks:
            task.priority += 1

        if old_status_tasks:
            Task.objects.bulk_update(old_status_tasks, ["priority"])
        if new_status_tasks:
            Task.objects.bulk_update(new_status_tasks, ["priority"])

        updating_task.statusId_id = new_status_id
        updating_task.priority = new_priority
        updating_task.save()

        return "Kanban successfully updated.", status.HTTP_200_OK
