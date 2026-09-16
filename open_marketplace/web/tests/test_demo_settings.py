import os
import subprocess
import sys

from django.test import SimpleTestCase


class DemoSettingsTests(SimpleTestCase):
    def test_only_exact_true_enables_demo_orders(self):
        for value in (None, "", "false", "TRUE", "True", "1", "true"):
            with self.subTest(value=value):
                environment = os.environ.copy()
                environment.pop("DEMO_ORDERS_ENABLED", None)
                if value is not None:
                    environment["DEMO_ORDERS_ENABLED"] = value
                result = subprocess.run(
                    [sys.executable, "-c", "from open_marketplace.config.settings import DEMO_ORDERS_ENABLED; print(DEMO_ORDERS_ENABLED)"],
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                self.assertEqual(result.stdout.strip(), str(value == "true"))
