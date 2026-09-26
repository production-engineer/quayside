import json
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from pm import tenants
from pm.model import WorkItem

OWNERS = {"remote-hands-llc": "rh", "beadedcloud": "bc", "production-engineer": "personal"}


def remote_of(owners_by_path):
    def lookup(path):
        return owners_by_path.get(str(path))
    return lookup


def item(source, **fields):
    fields.setdefault("title", "Invented")
    return WorkItem(source=source, id=f"{source}:invented", **fields)


class OwnerMap(unittest.TestCase):
    def test_config_table_is_loaded_from_json(self):
        path = Path(tempfile.mkdtemp()) / "owners.json"
        path.write_text(json.dumps({"Invented-Org": "rh"}), encoding="utf-8")
        self.assertEqual(tenants.load_owner_map(path), {"invented-org": "rh"})

    def test_shipped_table_covers_the_three_orgs(self):
        table = tenants.load_owner_map()
        self.assertEqual((table["remote-hands-llc"], table["beadedcloud"], table["production-engineer"]), ("rh", "bc", "personal"))

    def test_tenants_in_the_table_are_known(self):
        path = Path(tempfile.mkdtemp()) / "owners.json"
        path.write_text(json.dumps({"invented-org": "somewhere-else"}), encoding="utf-8")
        with self.assertRaises(ValueError):
            tenants.load_owner_map(path)


class TenantOfOwner(unittest.TestCase):
    def test_known_owners_case_insensitive(self):
        self.assertEqual(tenants.tenant_of_owner("Remote-Hands-LLC", OWNERS), "rh")
        self.assertEqual(tenants.tenant_of_owner("BEADEDCLOUD", OWNERS), "bc")
        self.assertEqual(tenants.tenant_of_owner("production-engineer", OWNERS), "personal")

    def test_any_other_owner_is_personal(self):
        self.assertEqual(tenants.tenant_of_owner("invented-customer-co", OWNERS), "personal")

    def test_no_owner_is_unassigned(self):
        self.assertIsNone(tenants.tenant_of_owner(None, OWNERS))
        self.assertIsNone(tenants.tenant_of_owner("", OWNERS))


class RemoteOwner(unittest.TestCase):
    def test_parses_ssh_and_https_remotes(self):
        self.assertEqual(tenants.owner_from_remote_url("git@github.com:Remote-Hands-LLC/invented.git"), "Remote-Hands-LLC")
        self.assertEqual(tenants.owner_from_remote_url("https://github.com/beadedcloud/invented"), "beadedcloud")
        self.assertEqual(tenants.owner_from_remote_url("ssh://git@github.com/production-engineer/invented.git"), "production-engineer")

    def test_non_github_or_garbage_remote_is_none(self):
        self.assertIsNone(tenants.owner_from_remote_url("https://gitlab.com/invented/x.git"))
        self.assertIsNone(tenants.owner_from_remote_url(""))

    def test_folder_without_git_has_no_owner(self):
        self.assertIsNone(tenants.git_remote_owner(Path(tempfile.mkdtemp())))

    def test_path_from_another_machine_maps_to_this_home(self):
        home = Path(tempfile.mkdtemp())
        (home / "repos" / "invented-app").mkdir(parents=True)
        self.assertEqual(tenants.local_path("/Users/someone-else/repos/invented-app", home), home / "repos" / "invented-app")
        self.assertEqual(tenants.local_path("~/repos/invented-app", home), home / "repos" / "invented-app")
        self.assertIsNone(tenants.local_path("/Users/someone-else/repos/missing", home))


class Attribute(unittest.TestCase):
    def attribute(self, work, remotes=None, tasks_path=None):
        return tenants.attribute(work, OWNERS, remote_of(remotes or {}), tasks_path=tasks_path, home=Path("/invented-home"))

    def test_github_items_go_by_repo_owner(self):
        self.assertEqual(self.attribute(item("github", project="Remote-Hands-LLC/invented")), "rh")
        self.assertEqual(self.attribute(item("github", project="beadedcloud/invented")), "bc")
        self.assertEqual(self.attribute(item("github", project="invented-customer-co/x")), "personal")

    def test_github_item_without_owner_is_unassigned(self):
        self.assertIsNone(self.attribute(item("github", project="")))

    def test_tracker_rows_are_remote_hands(self):
        self.assertEqual(self.attribute(item("tracker", project="remote-hands")), "rh")

    def test_tasks_go_by_the_task_file_repo_remote(self):
        remotes = {"/invented/quayside_personal": "production-engineer"}
        self.assertEqual(self.attribute(item("tasks"), remotes, Path("/invented/quayside_personal/TASKS.md")), "personal")

    def test_tasks_file_outside_a_repo_is_unassigned(self):
        self.assertIsNone(self.attribute(item("tasks"), {}, Path("/invented/loose/TASKS.md")))

    def test_portal_goes_by_its_declared_project_path(self):
        remotes = {"/invented-home/repos/invented-portal-app": "Remote-Hands-LLC"}
        work = item("portal", project="/Users/someone-else/repos/invented-portal-app")
        with unittest.mock.patch.object(tenants, "local_path", lambda declared, home: Path("/invented-home/repos/invented-portal-app")):
            self.assertEqual(self.attribute(work, remotes), "rh")

    def test_portal_without_a_declared_path_is_unassigned(self):
        self.assertIsNone(self.attribute(item("portal", project="Keep")))

    def test_portal_whose_declared_path_is_missing_is_unassigned(self):
        with unittest.mock.patch.object(tenants, "local_path", lambda declared, home: None):
            self.assertIsNone(self.attribute(item("portal", project="/Users/someone-else/repos/missing")))

    def test_unknown_source_is_unassigned(self):
        self.assertIsNone(self.attribute(item("invented-source")))


if __name__ == "__main__":
    unittest.main()
