from rest_framework import serializers

from api.models import Feedback, Project, Status, Task, User, new_id


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = "__all__"


class StatusSerializer(serializers.ModelSerializer):
    id = serializers.CharField(required=False)

    class Meta:
        model = Status
        fields = ["id", "name", "color", "order"]


class ProjectSerializer(serializers.ModelSerializer):
    taskStatuses = StatusSerializer(many=True, required=False)

    class Meta:
        model = Project
        fields = "__all__"

    def create(self, validated_data):
        statuses = validated_data.pop("taskStatuses", None)
        project = Project.objects.create(**validated_data)
        if statuses is None:
            statuses = Project.create_default_task_statuses()
        for status in statuses:
            Status.objects.create(
                id=status.get("id") or new_id(),
                project=project,
                name=status["name"],
                color=status["color"],
                order=status["order"],
            )
        return project

    def update(self, instance, validated_data):
        statuses = validated_data.pop("taskStatuses", serializers.empty)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if statuses is not serializers.empty:
            keep = {status["id"] for status in statuses if status.get("id")}
            instance.taskStatuses.exclude(id__in=keep).delete()
            for status in statuses:
                Status.objects.update_or_create(
                    id=status.get("id") or new_id(),
                    defaults={
                        "project": instance,
                        "name": status["name"],
                        "color": status["color"],
                        "order": status["order"],
                    },
                )
        return instance


class TaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = "__all__"


class FeedbackSerializer(serializers.ModelSerializer):
    class Meta:
        model = Feedback
        fields = "__all__"


class GeneratedTaskSerializer(serializers.Serializer):
    projectID = serializers.CharField(required=True)
    name = serializers.CharField(required=True)
    description = serializers.CharField(allow_blank=True, allow_null=True)
