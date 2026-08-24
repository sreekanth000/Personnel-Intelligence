"""
Test suite for Local Hermes Runtime Host Launcher.
"""

import unittest
from personal_intelligence.hermes_bridge.client import get_active_hermes_context, set_active_hermes_context
from scripts.launch_local_hermes import LocalHermesRuntimeHost
from personal_intelligence.hermes_bridge.plugin import register as register_pi_plugin


class TestLocalHermesLauncher(unittest.TestCase):

    def setUp(self) -> None:
        set_active_hermes_context(None)

    def tearDown(self) -> None:
        set_active_hermes_context(None)

    def test_local_hermes_runtime_host_creation_and_registration(self) -> None:
        host = LocalHermesRuntimeHost(
            enable_gmail=True,
            gmail_auth_status="authenticated",
        )
        self.assertIn("gmail_search", host.available_tools)
        self.assertIn("fs_read", host.available_tools)
        self.assertEqual(host.is_capability_authenticated("gmail"), "authenticated")

        # Execute built-in tool
        res = host.execute_tool("gmail_search", {"query": "project status"})
        self.assertEqual(res["status"], "success")
        self.assertEqual(len(res["result"]["messages"]), 1)

        # Register Personal Intelligence Plugin
        register_pi_plugin(host)
        set_active_hermes_context(host)

        # Verify active context
        ctx = get_active_hermes_context()
        self.assertIsNotNone(ctx)
        self.assertIn("get_current_personal_state", host.tools)
        self.assertIn("get_personal_world_model", host.tools)

        # Verify tool execution via plugin
        pi_res = host.execute_tool("get_current_personal_state", {})
        self.assertEqual(pi_res["status"], "success")


if __name__ == "__main__":
    unittest.main()
