import mongomock
import pytest
from bson import ObjectId

from api.management.commands.migrate_mongo import run_migration
from api.models import Feedback, Project, Status, Task, User

pytestmark = pytest.mark.django_db


def fresh_db():
    return mongomock.MongoClient().quayside


def seed_basic(db):
    uid = ObjectId()
    pid = ObjectId()
    sid = ObjectId()
    tid = ObjectId()
    fid = ObjectId()
    db["User"].insert_one(
        {
            "_id": uid,
            "email": "a@example.com",
            "username": "alice",
            "firstName": "A",
            "lastName": "Lice",
            "teamIDs": [str(ObjectId())],
        }
    )
    db["Project"].insert_one(
        {
            "_id": pid,
            "name": "P1",
            "userIDs": [str(uid)],
            "taskStatuses": [
                {"id": str(sid), "name": "Todo", "color": "323232", "order": 1}
            ],
        }
    )
    db["Task"].insert_one(
        {
            "_id": tid,
            "name": "Root",
            "projectID": str(pid),
            "statusId": str(sid),
            "parentTaskID": None,
            "durationMinutes": 30,
        }
    )
    db["Feedback"].insert_one(
        {
            "_id": fid,
            "userID": str(uid),
            "projectID": str(pid),
            "taskID": str(tid),
            "mood": 5,
        }
    )
    return {
        "uid": str(uid),
        "pid": str(pid),
        "sid": str(sid),
        "tid": str(tid),
        "fid": str(fid),
    }


def test_round_trip_preserves_ids_and_fks():
    db = fresh_db()
    parent = ObjectId()
    ids = seed_basic(db)
    db["Task"].insert_one(
        {
            "_id": parent,
            "name": "Child",
            "projectID": ids["pid"],
            "statusId": ids["sid"],
            "parentTaskID": ids["tid"],
        }
    )

    run_migration(db)

    user = User.objects.get(id=ids["uid"])
    assert user.email == "a@example.com"

    project = Project.objects.get(id=ids["pid"])
    assert project.userIDs == [ids["uid"]]

    status = Status.objects.get(id=ids["sid"])
    assert status.project_id == ids["pid"]
    assert status.name == "Todo"

    root = Task.objects.get(id=ids["tid"])
    assert root.projectID_id == ids["pid"]
    assert root.statusId_id == ids["sid"]
    assert root.parentTaskID_id is None
    assert root.durationMinutes == 30

    child = Task.objects.get(id=str(parent))
    assert child.parentTaskID_id == ids["tid"]

    fb = Feedback.objects.get(id=ids["fid"])
    assert fb.userID_id == ids["uid"]
    assert fb.projectID_id == ids["pid"]
    assert fb.taskID_id == ids["tid"]


def test_idempotency():
    db = fresh_db()
    seed_basic(db)

    r1 = run_migration(db)
    counts1 = (User.objects.count(), Project.objects.count(), Status.objects.count(),
               Task.objects.count(), Feedback.objects.count())

    r2 = run_migration(db)
    counts2 = (User.objects.count(), Project.objects.count(), Status.objects.count(),
               Task.objects.count(), Feedback.objects.count())

    assert counts1 == counts2 == (1, 1, 1, 1, 1)
    assert r1.tasks.written == r2.tasks.written
    assert r1.feedback.written == r2.feedback.written


def test_orphan_task_missing_project_skipped():
    db = fresh_db()
    orphan = ObjectId()
    db["Task"].insert_one(
        {"_id": orphan, "name": "Orphan", "projectID": str(ObjectId())}
    )

    report = run_migration(db)

    assert Task.objects.filter(id=str(orphan)).count() == 0
    assert report.orphan_tasks == 1
    assert report.tasks.skipped == 1


def test_dangling_status_nulled_and_counted():
    db = fresh_db()
    pid = ObjectId()
    tid = ObjectId()
    db["Project"].insert_one({"_id": pid, "name": "P", "taskStatuses": []})
    db["Task"].insert_one(
        {"_id": tid, "name": "T", "projectID": str(pid), "statusId": str(ObjectId())}
    )

    report = run_migration(db)

    task = Task.objects.get(id=str(tid))
    assert task.statusId_id is None
    assert report.dropped_statuses == 1
    assert report.tasks.reconciled == 1


def test_dangling_parent_detached_and_counted():
    db = fresh_db()
    pid = ObjectId()
    tid = ObjectId()
    db["Project"].insert_one({"_id": pid, "name": "P", "taskStatuses": []})
    db["Task"].insert_one(
        {
            "_id": tid,
            "name": "T",
            "projectID": str(pid),
            "parentTaskID": str(ObjectId()),
        }
    )

    report = run_migration(db)

    task = Task.objects.get(id=str(tid))
    assert task.parentTaskID_id is None
    assert report.detached_parents == 1


def test_orphan_feedback_skipped():
    db = fresh_db()
    pid = ObjectId()
    db["Project"].insert_one({"_id": pid, "name": "P", "taskStatuses": []})
    db["Feedback"].insert_one(
        {"_id": ObjectId(), "userID": str(ObjectId()), "projectID": str(pid)}
    )

    report = run_migration(db)

    assert Feedback.objects.count() == 0
    assert report.orphan_feedback == 1
    assert report.feedback.skipped == 1


def test_feedback_dangling_task_detached():
    db = fresh_db()
    ids = seed_basic(db)
    fid = ObjectId()
    db["Feedback"].insert_one(
        {
            "_id": fid,
            "userID": ids["uid"],
            "projectID": ids["pid"],
            "taskID": str(ObjectId()),
        }
    )

    report = run_migration(db)

    fb = Feedback.objects.get(id=str(fid))
    assert fb.taskID_id is None
    assert report.detached_feedback_task == 1


def test_email_coercion_missing_and_duplicate():
    db = fresh_db()
    u_missing = ObjectId()
    u_first = ObjectId()
    u_dup = ObjectId()
    db["User"].insert_one({"_id": u_missing, "username": "nomail"})
    db["User"].insert_one({"_id": u_first, "email": "dup@example.com"})
    db["User"].insert_one({"_id": u_dup, "email": "dup@example.com"})

    report = run_migration(db)

    assert User.objects.get(id=str(u_missing)).email == f"placeholder+{u_missing}@quayside.invalid"
    assert User.objects.get(id=str(u_first)).email == "dup@example.com"
    assert User.objects.get(id=str(u_dup)).email == f"placeholder+{u_dup}@quayside.invalid"
    assert report.synthesized_emails == 1
    assert report.deduped_emails == 1
    assert User.objects.count() == 3


def test_synthesized_status_id_when_missing():
    db = fresh_db()
    pid = ObjectId()
    db["Project"].insert_one(
        {
            "_id": pid,
            "name": "P",
            "taskStatuses": [{"name": "Todo", "color": "323232", "order": 1}],
        }
    )

    run_migration(db)

    statuses = Status.objects.filter(project_id=str(pid))
    assert statuses.count() == 1
    assert len(statuses.first().id) == 24


def test_dry_run_writes_nothing():
    db = fresh_db()
    seed_basic(db)

    report = run_migration(db, dry_run=True)

    assert User.objects.count() == 0
    assert Project.objects.count() == 0
    assert Status.objects.count() == 0
    assert Task.objects.count() == 0
    assert Feedback.objects.count() == 0
    assert report.users.source == 1
    assert report.tasks.written == 1


def test_only_filter_runs_subset():
    db = fresh_db()
    seed_basic(db)

    run_migration(db, only=["users"])

    assert User.objects.count() == 1
    assert Project.objects.count() == 0
    assert Task.objects.count() == 0


def test_durationminutes_defaults_to_zero():
    db = fresh_db()
    pid = ObjectId()
    tid = ObjectId()
    db["Project"].insert_one({"_id": pid, "name": "P", "taskStatuses": []})
    db["Task"].insert_one({"_id": tid, "name": "T", "projectID": str(pid)})

    run_migration(db)

    assert Task.objects.get(id=str(tid)).durationMinutes == 0
