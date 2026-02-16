from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import patch

from minijinja import Environment

import gdansk.render as render_module
from gdansk.render import ENV


def _template_files() -> list[Path]:
    package_dir = Path(render_module.__file__).resolve().parent
    return sorted(package_dir.glob("*.html.j2"))


def test_env_is_minijinja_environment():
    assert isinstance(ENV, Environment)


def test_all_package_html_j2_templates_are_registered_at_import():
    template_files = _template_files()
    expected_stems = {template_file.stem for template_file in template_files}

    with patch("minijinja.Environment.add_template") as add_template:
        importlib.reload(render_module)

    registered_stems = {call.kwargs["name"] for call in add_template.call_args_list}
    registered_sources = {call.kwargs["source"] for call in add_template.call_args_list}

    assert add_template.call_count == len(template_files)
    assert registered_stems == expected_stems
    assert "metadata.html" in registered_stems
    assert registered_sources == {template_file.read_text(encoding="utf-8") for template_file in template_files}

    importlib.reload(render_module)


def test_metadata_and_template_html_files_are_present():
    stems = {template_file.stem for template_file in _template_files()}
    assert "template.html" in stems
    assert "metadata.html" in stems
