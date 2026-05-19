"""Loads and merges all YAML files under config/ingestion/, resolving ${VAR} tokens."""

import os
import re
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

_ENV_TOKEN = re.compile(r"\$\{([^}]+)\}")


def _resolve_value(value: str, env: dict, flat: dict) -> str:
    """Replace ${VAR} and ${section.key} tokens in a string."""
    def replace(match: re.Match) -> str:
        token = match.group(1)
        if "." in token:
            # Dotted reference into merged config — flat keys look like "edgar.base_url"
            resolved = flat.get(token)
            return str(resolved) if resolved is not None else match.group(0)
        return env.get(token, match.group(0))

    return _ENV_TOKEN.sub(replace, value)


def _resolve_tree(node, env: dict, flat: dict):
    """Recursively resolve ${VAR} tokens throughout a parsed YAML tree."""
    if isinstance(node, dict):
        return {k: _resolve_tree(v, env, flat) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve_tree(item, env, flat) for item in node]
    if isinstance(node, str):
        return _resolve_value(node, env, flat)
    return node


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _flatten(node, prefix="") -> dict:
    """Produce a flat dict of dotted-key → leaf-value for cross-reference resolution."""
    out = {}
    if isinstance(node, dict):
        for k, v in node.items():
            child_key = f"{prefix}.{k}" if prefix else k
            out.update(_flatten(v, child_key))
    else:
        out[prefix] = node
    return out


def load_ingestion_config(config_dir: str | Path = "config/ingestion") -> dict:
    """
    Read every *.yaml in config_dir, deep-merge into one dict, then resolve
    ${ENV_VAR} and ${section.key} tokens against the environment and the
    merged config itself.
    """
    config_dir = Path(config_dir)
    env = dict(os.environ)

    merged: dict = {}
    for yaml_file in sorted(config_dir.glob("*.yaml")):
        with yaml_file.open() as f:
            data = yaml.safe_load(f) or {}
        merged = _deep_merge(merged, data)

    # Two-pass resolution: first pass makes base_url available for endpoints.yaml refs
    flat = _flatten(merged)
    resolved = _resolve_tree(merged, env, flat)

    # Second pass in case any resolved value introduced new tokens
    flat2 = _flatten(resolved)
    return _resolve_tree(resolved, env, flat2)
