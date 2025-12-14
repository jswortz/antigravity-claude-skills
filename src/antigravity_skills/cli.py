#!/usr/bin/env python3
"""
Antigravity Skill Manager
=========================

A tool to manage and ingest skills for Antigravity from external repositories.
Supports converting skills into:
1. Antigravity Workflows (.agent/workflows/)
2. Rules (.agent/rules/ or global ~/.gemini/GEMINI.md)

Usage:
    python scripts/skill_manager.py add-source <url> [name]
    python scripts/skill_manager.py list-sources
    python scripts/skill_manager.py ingest <skill_name> --as <workflow|rule> [--source <name>] [--scope <global|workspace>] [--activation <type>] [--glob <pattern>]
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional, Any

# Constants
CONFIG_DIR = Path(os.path.expanduser("~/.gemini/antigravity-skills"))
CONFIG_FILE = CONFIG_DIR / "skills_config.json"
CACHE_DIR = CONFIG_DIR / "skills_cache"
WORKFLOWS_DIR = Path(".agent/workflows")
WORKSPACE_RULES_DIR = Path(".agent/rules")
GLOBAL_RULES_FILE = Path(os.path.expanduser("~/.gemini/GEMINI.md"))

DEFAULT_SOURCES = {"anthropics": "https://github.com/anthropics/skills"}


def load_config() -> Dict[str, Any]:
    """Loads the skills configuration from JSON file."""
    if not CONFIG_FILE.exists():
        return {"sources": DEFAULT_SOURCES}
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"Warning: Could not load config file: {e}")
        return {"sources": DEFAULT_SOURCES}


def save_config(config: Dict[str, Any]):
    """Saves the skills configuration to JSON file."""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def run_command(command: list, cwd: Optional[Path] = None, check: bool = True):
    """Executes a subprocess command and handles errors."""
    try:
        subprocess.run(command, check=check, cwd=cwd, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {' '.join(command)}")
        print(f"Output: {e.stdout}")
        print(f"Error: {e.stderr}")
        raise


def ensure_repo_synced(name: str, url: str) -> Path:
    """Clones or pulls the repository to the cache directory."""
    repo_path = CACHE_DIR / name

    if repo_path.exists():
        print(f"Updating {name} ({url})...")
        run_command(["git", "fetch", "origin"], cwd=repo_path)
        run_command(
            ["git", "reset", "--hard", "origin/main"], cwd=repo_path
        )  # Assumes main/master
    else:
        print(f"Cloning {name} ({url})...")
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        run_command(["git", "clone", url, str(repo_path)])

    return repo_path


def parse_skill_md(skill_path: Path) -> dict:
    """Parses SKILL.md for frontmatter and content."""
    skill_file = skill_path / "SKILL.md"
    if not skill_file.exists():
        # Fallback for repos that might not strictly follow the structure yet
        # or if target is just a file. But for now assume structure.
        raise FileNotFoundError(f"SKILL.md not found in {skill_path}")

    content = skill_file.read_text()

    # Very basic frontmatter parser
    frontmatter = {}
    body = content

    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            fm_text = parts[1]
            body = parts[2].strip()
            for line in fm_text.splitlines():
                if ":" in line:
                    key, val = line.split(":", 1)
                    frontmatter[key.strip()] = val.strip()

    return {"frontmatter": frontmatter, "body": body}


def create_workflow(skill_name: str, data: dict):
    """Creates a workflow file."""
    WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)

    description = data["frontmatter"].get("description", f"Workflow for {skill_name}")

    content = f"""---
description: {description}
---
{data['body']}
"""
    target_file = WORKFLOWS_DIR / f"{skill_name}.md"
    target_file.write_text(content)
    print(f"Created Workflow: {target_file}")


def update_global_rule(skill_name: str, content: str):
    """Updates or appends a rule in the global GEMINI.md file."""
    GLOBAL_RULES_FILE.parent.mkdir(parents=True, exist_ok=True)

    if not GLOBAL_RULES_FILE.exists():
        GLOBAL_RULES_FILE.write_text("")

    current_content = GLOBAL_RULES_FILE.read_text()

    # Define markers
    start_marker = f"<!-- ANTHROPIC_SKILL_START: {skill_name} -->"
    end_marker = f"<!-- ANTHROPIC_SKILL_END: {skill_name} -->"

    new_block = f"{start_marker}\n{content}\n{end_marker}"

    # Regex to find existing block
    # flags=re.DOTALL to match newlines
    pattern = re.compile(
        f"{re.escape(start_marker)}.*?{re.escape(end_marker)}", re.DOTALL
    )

    if pattern.search(current_content):
        print(f"Updating existing global rule: {skill_name}")
        updated_content = pattern.sub(new_block, current_content)
    else:
        print(f"Appending new global rule: {skill_name}")
        separator = "\n\n" if current_content.strip() else ""
        updated_content = f"{current_content}{separator}{new_block}"

    GLOBAL_RULES_FILE.write_text(updated_content)
    print(f"Saved Global Rule to: {GLOBAL_RULES_FILE}")


def create_workspace_rule(skill_name: str, data: dict, activation: Optional[dict]):
    """Creates a workspace rule file with frontmatter metadata."""
    WORKSPACE_RULES_DIR.mkdir(parents=True, exist_ok=True)

    description = data["frontmatter"].get("description", f"Rule for {skill_name}")

    # Construct Frontmatter
    frontmatter = f"""---
description: {description}
"""
    if activation:
        frontmatter += "activation:\n"
        frontmatter += f"  type: {activation['type']}\n"
        if activation.get("glob"):
            frontmatter += f"  glob: {activation['glob']}\n"

    frontmatter += "---\n\n"

    content = f"{frontmatter}{data['body']}"

    target_file = WORKSPACE_RULES_DIR / f"{skill_name}.md"
    target_file.write_text(content)
    print(f"Created Workspace Rule: {target_file}")


def command_add_source(args, config):
    """Handler for the 'add-source' command."""
    name = args.name or args.url.split("/")[-1].replace(".git", "")
    config["sources"][name] = args.url
    save_config(config)
    print(f"Added source '{name}': {args.url}")


def command_list_sources(args, config):
    """Handler for the 'list-sources' command."""
    print("Registered Sources:")
    for name, url in config.get("sources", {}).items():
        print(f"  {name.ljust(15)} {url}")


def command_ingest(args, config):
    """Handler for the 'ingest' command."""
    skill_name = args.skill_name
    sources = config.get("sources", {})

    # Determines source to use
    if args.source:
        if args.source in sources:
            source_url = sources[args.source]
            source_name = args.source
        else:
            print(f"Error: Source '{args.source}' not found in config.")
            return
    else:
        # Default to 'anthropics' if available, or first one
        if "anthropics" in sources:
            source_name = "anthropics"
        else:
            source_name = list(sources.keys())[0]
        source_url = sources[source_name]

    repo_path = ensure_repo_synced(source_name, source_url)

    # Locate the skill in the repo
    skill_dir = repo_path / "skills" / skill_name
    if not skill_dir.exists():
        skill_dir = repo_path / skill_name
        if not skill_dir.exists():
            print(f"Error: Skill '{skill_name}' not found in {source_name}.")
            return

    try:
        data = parse_skill_md(skill_dir)
    except Exception as e:
        print(f"Error parsing skill: {e}")
        return

    if args.as_type == "workflow":
        create_workflow(skill_name, data)
    elif args.as_type == "rule":
        if args.scope == "global":
            # Global rules don't use new activation metadata yet as they are just appended to markdown
            # Unless we want to inject metadata into the text? For now, keep it simple as requested.
            create_rule_global(skill_name, data)
        else:
            # Workspace rules
            activation = None
            if args.activation:
                activation = {"type": args.activation}
                if args.activation == "glob":
                    if not args.glob_pattern:
                        print(
                            "Error: --glob is required when activation type is 'glob'"
                        )
                        return
                    activation["glob"] = args.glob_pattern

            create_workspace_rule(skill_name, data, activation)
    else:
        print(f"Unknown type: {args.as_type}")


def create_rule_global(skill_name: str, data: dict):
    """Wrapper to call update_global_rule."""
    # We might want to prepend the description as a comment
    content = data["body"]
    if "description" in data["frontmatter"]:
        content = f"<!-- {data['frontmatter']['description']} -->\n\n{content}"
    update_global_rule(skill_name, content)


def list_artifacts():
    """
    Lists all installed workflows and rules.

    Checks:
    - .agent/workflows/
    - .agent/rules/
    - ~/.gemini/GEMINI.md (for global rules)
    """
    print("\nINSTALLED WORKFLOWS:")
    if WORKFLOWS_DIR.exists():
        for f in sorted(WORKFLOWS_DIR.glob("*.md")):
            print(f"  - {f.stem}")
    else:
        print("  (None)")

    print("\nINSTALLED WORKSPACE RULES:")
    if WORKSPACE_RULES_DIR.exists():
        for f in sorted(WORKSPACE_RULES_DIR.glob("*.md")):
            print(f"  - {f.stem}")
    else:
        print("  (None)")

    print("\nINSTALLED GLOBAL RULES:")
    if GLOBAL_RULES_FILE.exists():
        content = GLOBAL_RULES_FILE.read_text()
        # Find all start markers
        # Marker format: <!-- ANTHROPIC_SKILL_START: {skill_name} -->
        pattern = re.compile(r"<!-- ANTHROPIC_SKILL_START: (.+?) -->")
        matches = pattern.findall(content)
        if matches:
            for m in sorted(matches):
                print(f"  - {m}")
        else:
            print("  (None)")
    else:
        print("  (None)")


def remove_artifact(name: str, type_: str, scope: str = "workspace"):
    """
    Removes a specified artifact.

    Args:
        name: Name of the skill/artifact.
        type_: Type of artifact ('workflow' or 'rule').
        scope: Scope for rules ('workspace' or 'global').
    """
    if type_ == "workflow":
        target = WORKFLOWS_DIR / f"{name}.md"
        if target.exists():
            target.unlink()
            print(f"Removed workflow: {name}")
        else:
            print(f"Workflow '{name}' not found.")

    elif type_ == "rule":
        if scope == "workspace":
            target = WORKSPACE_RULES_DIR / f"{name}.md"
            if target.exists():
                target.unlink()
                print(f"Removed workspace rule: {name}")
            else:
                print(f"Workspace rule '{name}' not found.")
        elif scope == "global":
            if not GLOBAL_RULES_FILE.exists():
                print("Global rules file does not exist.")
                return

            content = GLOBAL_RULES_FILE.read_text()
            start_marker = f"<!-- ANTHROPIC_SKILL_START: {name} -->"
            end_marker = f"<!-- ANTHROPIC_SKILL_END: {name} -->"

            # Simple check first
            if start_marker not in content:
                print(f"Global rule '{name}' not found.")
                return

            # Regex remove
            # Include potential trailing newlines to keep file clean
            pattern = re.compile(
                f"{re.escape(start_marker)}.*?{re.escape(end_marker)}\\s*", re.DOTALL
            )

            new_content = pattern.sub("", content)

            # Clean up excessive newlines if any
            new_content = re.sub(r"\n{3,}", "\n\n", new_content.strip() + "\n")

            GLOBAL_RULES_FILE.write_text(new_content)
            print(f"Removed global rule: {name}")
    else:
        print(f"Unknown type: {type_}")


def command_list(args, config):
    """Handler for 'list' command."""
    list_artifacts()


def command_remove(args, config):
    """Handler for 'remove' command."""
    remove_artifact(args.name, args.type, args.scope)


def main():
    parser = argparse.ArgumentParser(description="Antigravity Skill Manager")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ADD SOURCE
    p_add = subparsers.add_parser("add-source", help="Add a git repository source")
    p_add.add_argument("url", help="Git repository URL")
    p_add.add_argument("name", nargs="?", help="Short name for the source")

    # LIST SOURCES
    p_list_sources = subparsers.add_parser(
        "list-sources", help="List registered sources"
    )

    # INGEST
    p_ingest = subparsers.add_parser("ingest", help="Ingest a skill")
    p_ingest.add_argument("skill_name", help="Name of the skill directory in the repo")
    p_ingest.add_argument(
        "--as",
        dest="as_type",
        choices=["workflow", "rule"],
        required=True,
        help="Convert to Workflow or Rule",
    )
    p_ingest.add_argument("--source", help="Specific source to pull from")
    p_ingest.add_argument(
        "--scope",
        choices=["global", "workspace"],
        default="workspace",
        help="Scope for rules (default: workspace)",
    )

    # Activation Metadata
    p_ingest.add_argument(
        "--activation",
        choices=["manual", "always-on", "model-decision", "glob"],
        help="Activation type for workspace rules",
    )
    p_ingest.add_argument(
        "--glob",
        dest="glob_pattern",
        help="Glob pattern (required if activation is 'glob')",
    )

    # LIST ARTIFACTS
    p_list = subparsers.add_parser("list", help="List installed workflows and rules")

    # REMOVE
    p_remove = subparsers.add_parser("remove", help="Remove an installed artifact")
    p_remove.add_argument("name", help="Name of the artifact to remove")
    p_remove.add_argument(
        "--type", choices=["workflow", "rule"], required=True, help="Type of artifact"
    )
    p_remove.add_argument(
        "--scope",
        choices=["global", "workspace"],
        default="workspace",
        help="Scope for rules (default: workspace)",
    )

    args = parser.parse_args()
    config = load_config()

    if args.command == "add-source":
        command_add_source(args, config)
    elif args.command == "list-sources":
        command_list_sources(args, config)
    elif args.command == "ingest":
        command_ingest(args, config)
    elif args.command == "list":
        command_list(args, config)
    elif args.command == "remove":
        command_remove(args, config)


if __name__ == "__main__":
    main()
