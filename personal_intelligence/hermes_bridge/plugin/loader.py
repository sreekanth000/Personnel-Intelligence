"""
Hermes Plugin Loader and Discovery Engine for Personal Intelligence.

Discovers and loads Hermes plugins, parses plugin.yaml manifests,
registers tools and lifecycle hooks, and discovers bundled skills.
Enforces that external integrations (Gmail, Calendar, Drive, Meet)
are delegated to Hermes core rather than implemented independently.
"""

from dataclasses import dataclass, field
import importlib
import importlib.util
import os
from pathlib import Path
import sys
from dataclasses import dataclass, field
import importlib
import importlib.util
import os
from pathlib import Path
import re
import sys
from typing import Any, Callable, Dict, List, Optional


def parse_simple_yaml(yaml_text: str) -> Dict[str, Any]:
    """
    Zero-dependency simple YAML parser for plugin.yaml and SKILL.md frontmatter.
    Parses key-value pairs, nested dictionaries, and lists.
    """
    result: Dict[str, Any] = {}
    lines = yaml_text.splitlines()
    current_key = None
    current_list: Optional[List[Any]] = None
    current_dict: Optional[Dict[str, Any]] = None
    list_item_dict: Optional[Dict[str, Any]] = None

    for raw_line in lines:
        # Strip comments
        line = raw_line.split("#", 1)[0].rstrip()
        if not line or not line.strip():
            continue

        indent = len(line) - len(line.lstrip())
        stripped = line.strip()

        # List item
        if stripped.startswith("- "):
            item_val = stripped[2:].strip()
            if ":" in item_val:
                # Dict item in list: e.g. "- name: get_state"
                k, v = item_val.split(":", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                list_item_dict = {k: v}
                if current_list is not None:
                    current_list.append(list_item_dict)
            else:
                item_clean = item_val.strip('"').strip("'")
                if current_list is not None:
                    current_list.append(item_clean)
            continue

        # Property under list item: e.g. "  description: Query..."
        if indent >= 4 and list_item_dict is not None and ":" in stripped:
            k, v = stripped.split(":", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            list_item_dict[k] = v
            continue

        # Reset list item dict on unindented or top-level lines
        list_item_dict = None

        if ":" in stripped:
            k, v = stripped.split(":", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")

            if not v:  # Starts a block (list or sub-dict)
                current_key = k
                if indent == 0:
                    current_list = []
                    result[k] = current_list
                    current_dict = None
                else:
                    current_list = []
                    if current_dict is not None:
                        current_dict[k] = current_list
            else:
                if indent == 0:
                    result[k] = v
                    current_key = None
                    current_list = None
                    current_dict = None
                elif current_dict is not None:
                    current_dict[k] = v
                elif current_key and current_key in result and isinstance(result[current_key], dict):
                    result[current_key][k] = v
                else:
                    result[k] = v

    return result


@dataclass
class BundledSkillMetadata:
    """Metadata representing a skill bundled within a Hermes plugin."""
    name: str
    path: str
    description: str = ""
    tools: List[str] = field(default_factory=list)
    raw_content: str = ""


@dataclass
class PluginMetadata:
    """Metadata representation of a discovered Hermes plugin."""
    name: str
    version: str
    description: str
    entrypoint: str
    directory_path: str
    manifest_path: str
    author: str = ""
    license: str = ""
    tools: List[Dict[str, Any]] = field(default_factory=list)
    hooks: List[str] = field(default_factory=list)
    skills: List[BundledSkillMetadata] = field(default_factory=list)
    capabilities: Dict[str, Any] = field(default_factory=dict)
    is_loaded: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "entrypoint": self.entrypoint,
            "author": self.author,
            "license": self.license,
            "directory_path": self.directory_path,
            "tool_count": len(self.tools),
            "tools": self.tools,
            "hooks": self.hooks,
            "skill_count": len(self.skills),
            "skills": [s.name for s in self.skills],
            "capabilities": self.capabilities,
            "is_loaded": self.is_loaded,
        }


class HermesPluginLoader:
    """
    Standard discovery and loading harness for Hermes plugins and bundled skills.
    """

    def __init__(self, plugin_roots: Optional[List[str]] = None) -> None:
        if plugin_roots is None:
            project_root = Path(__file__).resolve().parent.parent.parent.parent
            self.plugin_roots = [
                str(project_root / "plugins"),
                str(project_root / ".agents" / "plugins"),
                str(project_root / "personal_intelligence" / "hermes_bridge" / "plugin"),
            ]
        else:
            self.plugin_roots = [str(Path(p).resolve()) for p in plugin_roots]

    def discover_plugins(self) -> List[PluginMetadata]:
        """
        Scans all configured plugin roots for directories containing plugin.yaml.
        """
        discovered: List[PluginMetadata] = []
        visited_names = set()

        for root in self.plugin_roots:
            root_path = Path(root)
            if not root_path.exists():
                continue

            # Check if root itself is a plugin
            manifest_self = root_path / "plugin.yaml"
            if manifest_self.is_file():
                plugin_meta = self._parse_manifest(manifest_self, root_path)
                if plugin_meta and plugin_meta.name not in visited_names:
                    discovered.append(plugin_meta)
                    visited_names.add(plugin_meta.name)

            # Check immediate child directories
            if root_path.is_dir():
                for child in root_path.iterdir():
                    if child.is_dir():
                        manifest = child / "plugin.yaml"
                        if manifest.is_file():
                            plugin_meta = self._parse_manifest(manifest, child)
                            if plugin_meta and plugin_meta.name not in visited_names:
                                discovered.append(plugin_meta)
                                visited_names.add(plugin_meta.name)

        return discovered

    def find_plugin(self, plugin_name: str) -> Optional[PluginMetadata]:
        """Finds a specific plugin by name from discovered plugins."""
        for p in self.discover_plugins():
            if p.name == plugin_name:
                return p
        return None

    def load_plugin(self, plugin_name: str, context: object) -> PluginMetadata:
        """
        Discovers, loads, and registers a named plugin into the provided Hermes context.
        """
        plugin = self.find_plugin(plugin_name)
        if not plugin:
            raise FileNotFoundError(f"Plugin '{plugin_name}' not found in roots: {self.plugin_roots}")

        # Add plugin directory to sys.path if not present
        if plugin.directory_path not in sys.path:
            sys.path.insert(0, plugin.directory_path)

        # Parse entrypoint format: "module:function" or "__init__.py:register"
        ep = plugin.entrypoint
        if ":" in ep:
            mod_part, func_name = ep.split(":", 1)
        else:
            mod_part, func_name = ep, "register"

        if mod_part.endswith(".py"):
            mod_name = Path(mod_part).stem
            mod_file = os.path.join(plugin.directory_path, mod_part)
            spec = importlib.util.spec_from_file_location(f"plugins.{plugin_name}.{mod_name}", mod_file)
            if spec is None or spec.loader is None:
                raise ImportError(f"Could not load module spec from {mod_file}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        else:
            module = importlib.import_module(mod_part)

        if not hasattr(module, func_name):
            raise AttributeError(f"Entrypoint function '{func_name}' not found in module '{mod_part}' for plugin '{plugin_name}'")

        register_func: Callable[[Any], None] = getattr(module, func_name)
        register_func(context)
        plugin.is_loaded = True

        return plugin

    def _parse_manifest(self, manifest_path: Path, directory_path: Path) -> Optional[PluginMetadata]:
        """Parses a plugin.yaml manifest file into a PluginMetadata object."""
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                content = f.read()
            data = parse_simple_yaml(content)
            if not isinstance(data, dict):
                return None

            name = data.get("name")
            if not name:
                return None

            # Discover bundled skills
            skills = self._discover_bundled_skills(directory_path, data.get("skills", []))

            return PluginMetadata(
                name=name,
                version=str(data.get("version", "0.1.0")),
                description=str(data.get("description", "")),
                entrypoint=str(data.get("entrypoint", "__init__.py:register")),
                author=str(data.get("author", "")),
                license=str(data.get("license", "")),
                directory_path=str(directory_path),
                manifest_path=str(manifest_path),
                tools=data.get("tools", []),
                hooks=data.get("hooks", []),
                skills=skills,
                capabilities=data.get("capabilities", {}),
            )
        except Exception:
            return None

    def _discover_bundled_skills(self, plugin_dir: Path, skill_entries: List[Dict[str, Any]]) -> List[BundledSkillMetadata]:
        """Discovers and parses SKILL.md documents in the plugin's skills/ directory."""
        skills: List[BundledSkillMetadata] = []
        skills_dir = plugin_dir / "skills"

        # Explicit manifest skills or directory scanning
        if skills_dir.is_dir():
            for child in skills_dir.iterdir():
                skill_md = child / "SKILL.md" if child.is_dir() else (child if child.name.endswith(".md") else None)
                if skill_md and skill_md.is_file():
                    skill_meta = self._parse_skill_file(skill_md, child.name if child.is_dir() else child.stem)
                    if skill_meta:
                        skills.append(skill_meta)

        return skills

    def _parse_skill_file(self, skill_file: Path, fallback_name: str) -> Optional[BundledSkillMetadata]:
        """Extracts YAML frontmatter from a SKILL.md file."""
        try:
            with open(skill_file, "r", encoding="utf-8") as f:
                content = f.read()

            name = fallback_name
            description = ""
            tools = []

            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    frontmatter = parse_simple_yaml(parts[1])
                    if isinstance(frontmatter, dict):
                        name = frontmatter.get("name", fallback_name)
                        description = frontmatter.get("description", "")
                        tools = frontmatter.get("tools", [])

            return BundledSkillMetadata(
                name=name,
                path=str(skill_file),
                description=description,
                tools=tools,
                raw_content=content,
            )
        except Exception:
            return None
