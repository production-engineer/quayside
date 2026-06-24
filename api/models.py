import secrets

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils import timezone


def new_id() -> str:
    return secrets.token_hex(12)


def object_id_array():
    return ArrayField(models.CharField(max_length=24), default=list, blank=True)


def string_array():
    return ArrayField(models.TextField(), default=list, blank=True)


class User(models.Model):
    id = models.CharField(primary_key=True, max_length=24, default=new_id, editable=False)
    email = models.EmailField(unique=True)
    username = models.CharField(max_length=255, blank=True, default="")
    firstName = models.CharField(max_length=255, blank=True, default="")
    lastName = models.CharField(max_length=255, blank=True, default="")
    teamIDs = object_id_array()
    apiKey = models.TextField(null=True, blank=True)


class Project(models.Model):
    id = models.CharField(primary_key=True, max_length=24, default=new_id, editable=False)
    name = models.CharField(max_length=255, blank=True, default="")
    description = models.TextField(null=True, blank=True)
    startDate = models.DateField(null=True, blank=True)
    endDate = models.DateField(null=True, blank=True)
    budget = models.CharField(max_length=255, blank=True, default="")
    completionStatus = models.CharField(max_length=255, blank=True, default="")

    types = string_array()
    objectives = string_array()
    assumptions = string_array()
    scopesIncluded = string_array()
    scopesExcluded = string_array()
    risks = string_array()
    sponsors = string_array()
    completionRequirements = string_array()
    qualityAssurance = string_array()
    KPIs = string_array()
    informationLinks = string_array()

    userIDs = object_id_array()
    projectManagerIDs = object_id_array()
    contributorIDs = object_id_array()
    otherProjectDependencies = object_id_array()
    teams = object_id_array()

    @staticmethod
    def create_default_task_statuses():
        return [
            {"name": "Todo", "color": "323232", "order": 1},
            {"name": "In-Progress", "color": "EFA610", "order": 2},
            {"name": "Done", "color": "01796E", "order": 3},
        ]


class Status(models.Model):
    id = models.CharField(primary_key=True, max_length=24, default=new_id, editable=False)
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="taskStatuses"
    )
    name = models.CharField(max_length=255)
    color = models.CharField(max_length=8)
    order = models.IntegerField()

    class Meta:
        ordering = ["order"]


class Task(models.Model):
    id = models.CharField(primary_key=True, max_length=24, default=new_id, editable=False)
    projectID = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="tasks")
    parentTaskID = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True, related_name="children"
    )
    statusId = models.ForeignKey(
        Status, on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks"
    )
    name = models.CharField(max_length=255, blank=True, default="")
    description = models.TextField(null=True, blank=True)
    startDate = models.DateField(null=True, blank=True)
    endDate = models.DateField(null=True, blank=True)
    priority = models.IntegerField(null=True, blank=True)
    durationMinutes = models.IntegerField(default=0)

    objectives = string_array()
    scopesIncluded = string_array()
    scopesExcluded = string_array()
    contributorIDs = object_id_array()
    otherProjectDependencies = object_id_array()
    otherTaskDependencies = object_id_array()


class Feedback(models.Model):
    id = models.CharField(primary_key=True, max_length=24, default=new_id, editable=False)
    userID = models.ForeignKey(User, on_delete=models.CASCADE, related_name="feedback")
    projectID = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="feedback"
    )
    taskID = models.ForeignKey(
        Task, on_delete=models.SET_NULL, null=True, blank=True, related_name="feedback"
    )
    dateCreated = models.DateTimeField(default=timezone.now)
    mood = models.IntegerField(null=True, blank=True)
    explanation = models.TextField(null=True, blank=True)
