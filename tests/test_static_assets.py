import tempfile

from django.core.management import call_command
from django.test import SimpleTestCase, override_settings


class CollectStatic(SimpleTestCase):
    """
    Manifest static storage rewrites every url() reference it finds and raises when one
    does not resolve. entrypoint.sh runs collectstatic under set -e before gunicorn, so a
    dead reference stops the container from starting.
    """

    def test_every_static_reference_resolves(self):
        with tempfile.TemporaryDirectory() as staticRoot:
            with override_settings(STATIC_ROOT=staticRoot):
                call_command("collectstatic", interactive=False, verbosity=0)
