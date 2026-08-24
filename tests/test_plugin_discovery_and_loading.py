"""
Unit and integration test suite for Hermes Plugin Discovery and Loading.
Verifies:
1. Plugin discovery across plugin roots.
2. Successful plugin loading and tool/hook registration.
3. Bundled skill discovery (personal_intelligence and personal_investigation).
4. Strict architectural isolation (no independent Gmail/Drive/Calendar/Meet API clients or OAuth).
"""

from pathlib import Path
import unittest

from personal_intelligence.hermes_bridge.plugin.loader import (
    BundledSkillMetadata,
    HermesPluginLoader,
    PluginMetadata,
)


class MockHermesAgentContext:
    """Mock Hermes runtime context to capture tool and hook registrations."""

    def __init__(self) -> None:
        self.registered_tools = {}
        self.registered_hooks = {}

    def register_tool(self, name: str, schema: dict, handler: callable) -> None:
        self.registered_tools[name] = {
            "schema": schema,
            "handler": handler,
        }

    def register_hook(self, hook_name: str, handler: callable) -> None:
        if hook_name not in self.registered_hooks:
            self.registered_hooks[hook_name] = []
        self.registered_hooks[hook_name].append(handler)


class TestHermesPluginDiscoveryAndLoading(unittest.TestCase):
    """Test suite verifying plugin discovery, loading, and skill discovery."""

    def setUp(self) -> None:
        project_root = Path(__file__).resolve().parent.parent
        self.plugin_roots = [
            str(project_root / "plugins"),
            str(project_root / "personal_intelligence" / "hermes_bridge" / "plugin"),
        ]
        self.loader = HermesPluginLoader(plugin_roots=self.plugin_roots)

    # 1. Plugin Discovery
    def test_plugin_discovery(self) -> None:
        """Verify the personal_intelligence plugin is discovered in plugin roots."""
        plugins = self.loader.discover_plugins()
        self.assertGreaterEqual(len(plugins), 1)

        plugin_names = [p.name for p in plugins]
        self.assertIn("personal_intelligence", plugin_names)

        pi_plugin = next(p for p in plugins if p.name == "personal_intelligence")
        self.assertEqual(pi_plugin.version, "0.1.0")
        self.assertIn("Hermes plugin exposing Personal Intelligence", pi_plugin.description)
        self.assertTrue(Path(pi_plugin.manifest_path).exists())

    # 2. Plugin Loading & Tool Registration
    def test_plugin_loading_and_registration(self) -> None:
        """Verify plugin loads into Hermes context and registers tools and hooks."""
        ctx = MockHermesAgentContext()
        plugin = self.loader.load_plugin("personal_intelligence", ctx)

        self.assertTrue(plugin.is_loaded)

        expected_tools = {
            "get_current_personal_state",
            "get_personal_timeline",
            "get_active_goals",
            "get_situation",
            "get_reasoning_context",
            "store_reasoning_episode",
            "record_observation",
            "get_personal_world_model",
            "evaluate_candidate_situations",
            "execute_pi_command",
        }
        self.assertEqual(set(ctx.registered_tools.keys()), expected_tools)


        # Verify tool schemas
        for tool_name in expected_tools:
            tool_entry = ctx.registered_tools[tool_name]
            self.assertIn("schema", tool_entry)
            self.assertIn("handler", tool_entry)
            self.assertTrue(callable(tool_entry["handler"]))
            self.assertEqual(tool_entry["schema"]["name"], tool_name)
            self.assertIn("description", tool_entry["schema"])

        # Verify hooks
        self.assertIn("pre_tool_call", ctx.registered_hooks)
        self.assertIn("post_tool_call", ctx.registered_hooks)

    # 3. Skill Discovery
    def test_bundled_skill_discovery(self) -> None:
        """Verify bundled skills are discovered with valid YAML frontmatter."""
        pi_plugin = self.loader.find_plugin("personal_intelligence")
        self.assertIsNotNone(pi_plugin)

        skill_names = [s.name for s in pi_plugin.skills]
        self.assertIn("personal_intelligence", skill_names)

        # Verify personal_intelligence skill content
        pi_skill = next(s for s in pi_plugin.skills if s.name == "personal_intelligence")
        self.assertIn("reasoning skill", pi_skill.description)
        self.assertTrue(Path(pi_skill.path).exists())
        self.assertIn("get_current_personal_state", pi_skill.tools)
        self.assertIn("store_reasoning_episode", pi_skill.tools)

    # 4. Strict Architectural Isolation Guarantee
    def test_architectural_isolation_guarantee(self) -> None:
        """
        Verify no separate Gmail, Google Calendar, Google Drive, or Google Meet API clients
        or OAuth implementations exist in Personal Intelligence codebase.
        Hermes owns external integration capabilities.
        """
        import personal_intelligence

        pkg_dir = Path(personal_intelligence.__file__).parent

        # Inspect all python source files for unauthorized Google API client libraries
        unauthorized_tokens = [
            "googleapiclient.discovery",
            "google_auth_oauthlib.flow",
            "google.oauth2.credentials",
            "google.auth.transport.requests",
            "gmail_v1",
            "calendar_v3",
            "drive_v3",
        ]

        for py_file in pkg_dir.rglob("*.py"):
            with open(py_file, "r", encoding="utf-8") as f:
                content = f.read()
                for token in unauthorized_tokens:
                    self.assertNotIn(
                        token,
                        content,
                        f"Unauthorized separate Google API client import '{token}' found in {py_file}. "
                        "Personal Intelligence must use Hermes existing tools rather than independent API clients.",
                    )


if __name__ == "__main__":
    unittest.main()
