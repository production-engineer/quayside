from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.utils.decorators import method_decorator

from api.decorators import apiKeyRequired
from api.models import Project, Status
from api.utils import getAuthorizationToken, decodeApiKey


def _member_project(projectID, authorizationToken):
    """Returns (project, error_response, http_status). On success error_response is None."""
    userID = decodeApiKey(authorizationToken).get("userID")
    try:
        project = Project.objects.get(id=projectID)
    except Project.DoesNotExist:
        return None, {"message": "Project not found."}, status.HTTP_404_NOT_FOUND
    if userID not in project.userIDs:
        return None, {
            "message": "User not authorized for this project."
        }, status.HTTP_403_FORBIDDEN
    return project, None, status.HTTP_200_OK


def _serialize(stat):
    return {"id": stat.id, "name": stat.name, "color": stat.color, "order": stat.order}


@method_decorator(
    apiKeyRequired, name="dispatch"
)  # dispatch protects all HTTP requests coming in
class StatusesAPIView(APIView):
    """
    Create, get, update, and delete a project status.
    """

    def get(self, request):
        """
        Retrieves a list of Status objects for a Project, filtered based on query parameters
        provided in the request. Requires 'apiToken' passed in auth header or cookies. Only gets
        statuses for projects where UserID matches.

        @param {HttpRequest} request - The request object.
            The query parameters can be:
                - projectID (objectID str)

        @return A Response object containing a JSON array of serialized Status objects.

        @example Javascript:
            fetch('quayside.app/api/v1/statuses?projectID=1234');
        """
        responseData, httpStatus = self.getStatuses(
            request.query_params.dict(), getAuthorizationToken(request)
        )
        return Response(responseData, status=httpStatus)

    def post(self, request):
        """
        Creates a status. Requires 'apiToken' passed in auth header or cookies.

        @param {HttpRequest} request - The request object.
            The request body can contain:
                - projectID (objectID str)
                - name (str)
                - color (str)
                - order (int)
        @param {str} authorizationToken - JWT authorization token.

        @return A response telling you if the status was created.

        @example javascript:

            fetch('quayside.app/api/v1/statuses', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ "projectID": "5AC9942376", "name":  "backlog", "color": "A4279", "order":  2 }),
            });

        """
        responseData, httpStatus = self.createStatus(
            request.data, getAuthorizationToken(request)
        )
        return Response(responseData, status=httpStatus)

    def put(self, request):
        """
        Updates a single status.
        Requires 'apiToken' passed in auth header or cookies.

        @param {HttpRequest} request - The request object.
            The request body can contain:
                - projectID (objectID str)
                - id (objectID str)
                - name (str)
                - color (str)
                - order (int)
        @return: A Response object with the updated status data or an error message.

        @example javascript
            await fetch(`/api/v1/statuses`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json'},
                body: JSON.stringify({ "projectID": "5AC9942376", "id": "1234", "name":  "backlog", "color": "A4279", "order":  2 }),
            });

        """
        responseData, httpStatus = self.updateStatus(
            request.data, getAuthorizationToken(request)
        )
        return Response(responseData, status=httpStatus)

    def delete(self, request):
        """
        Deletes a status from a project. Requires 'apiToken' passed in auth header or cookies.

        @param {HttpRequest} request - The request object.
            The query parameters MUST be:
                - projectID (objectID str) [REQUIRED]
                - id (objectID str) [REQUIRED]

        @return: A Response object with a success or an error message.

        @example javascript:

            fetch(`/api/v1/statuses?projectID=5678&id=1234`, {
                method: 'DELETE',
            });
        """
        responseData, httpStatus = self.deleteStatus(
            request.query_params, getAuthorizationToken(request)
        )
        return Response(responseData, status=httpStatus)

    @staticmethod
    def getStatuses(statusData, authorizationToken):
        """
        Service API function that returns the statuses for a member's project.

        @param statusData      Dict containing 'projectID'.
        @param authorizationToken      JWT authorization token.
        @return      A tuple of (response_data, http_status).
        """
        if "projectID" not in statusData:
            return {
                "message": "Parameter 'projectID' required."
            }, status.HTTP_400_BAD_REQUEST

        project, error, httpStatus = _member_project(
            statusData["projectID"], authorizationToken
        )
        if error is not None:
            return error, httpStatus

        statuses = [_serialize(stat) for stat in project.taskStatuses.all()]
        return statuses, status.HTTP_200_OK

    @staticmethod
    def createStatus(statusData, authorizationToken):
        """
        Service API function that creates a status row for a member's project.

        @param statusData      Dict containing 'projectID', 'name', 'color', 'order'.
        @param authorizationToken      JWT authorization token.
        @return      A tuple of (response_data, http_status).
        """
        if "projectID" not in statusData:
            return {
                "message": "Parameter 'projectID' required."
            }, status.HTTP_400_BAD_REQUEST

        project, error, httpStatus = _member_project(
            statusData["projectID"], authorizationToken
        )
        if error is not None:
            return error, httpStatus

        stat = Status.objects.create(
            project=project,
            name=statusData["name"],
            color=statusData["color"],
            order=statusData["order"],
        )
        return _serialize(stat), status.HTTP_201_CREATED

    @staticmethod
    def updateStatus(statusData, authorizationToken):
        """
        Service API function that updates a status row for a member's project.

        @param statusData      Dict containing 'projectID', 'id', and fields to update.
        @param authorizationToken      JWT authorization token.
        @return      A tuple of (response_data, http_status).
        """
        if "projectID" not in statusData or "id" not in statusData:
            return {
                "message": "Parameters 'projectID' and 'id' required."
            }, status.HTTP_400_BAD_REQUEST

        project, error, httpStatus = _member_project(
            statusData["projectID"], authorizationToken
        )
        if error is not None:
            return error, httpStatus

        try:
            stat = project.taskStatuses.get(id=statusData["id"])
        except Status.DoesNotExist:
            return {"message": "Status not found."}, status.HTTP_404_NOT_FOUND

        for field in ("name", "color", "order"):
            if field in statusData:
                setattr(stat, field, statusData[field])
        stat.save()
        return _serialize(stat), status.HTTP_200_OK

    @staticmethod
    def deleteStatus(statusData, authorizationToken):
        """
        Service API function that deletes a status row from a member's project.

        @param statusData      Dict containing 'projectID' and 'id'.
        @param authorizationToken      JWT authorization token.
        @return      A tuple of (response_data, http_status).
        """
        if "projectID" not in statusData or "id" not in statusData:
            return {
                "message": "Parameters 'projectID' and 'id' required."
            }, status.HTTP_400_BAD_REQUEST

        project, error, httpStatus = _member_project(
            statusData["projectID"], authorizationToken
        )
        if error is not None:
            return error, httpStatus

        deleted, _ = project.taskStatuses.filter(id=statusData["id"]).delete()
        if deleted == 0:
            return {"message": "Status not found."}, status.HTTP_404_NOT_FOUND

        return {"message": "Successfully deleted status"}, status.HTTP_200_OK
