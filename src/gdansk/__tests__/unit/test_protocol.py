from __future__ import annotations

import pytest
from gdansk_bundler import Plugin
from gdansk_runtime import Script
from gdansk_vite import VitePlugin, ViteScript


def test_vite_plugin_accepts_vite_script_from_file(tmp_path):
    script_path = tmp_path / "plugins" / "append-comment.mjs"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text("export default { name: 'append-comment' };", encoding="utf-8")

    plugin = VitePlugin(script=ViteScript.from_file(script_path))

    assert isinstance(plugin.script, ViteScript)
    assert plugin.script.source_path == str(script_path.resolve())
    assert isinstance(plugin, Plugin)
    assert plugin.id == "vite"
    assert repr(plugin) == f"VitePlugin(script=ViteScript.from_file({str(script_path.resolve())!r}))"


def test_vite_plugin_accepts_inline_vite_script():
    plugin = VitePlugin(script=ViteScript(contents="export default { name: 'inline' };"))

    assert isinstance(plugin.script, ViteScript)
    assert plugin.script.source_path is None
    assert repr(plugin) == "VitePlugin(script=ViteScript(contents='<inline>'))"


def test_vite_plugin_behaves_like_a_value_object():
    left = VitePlugin(script=ViteScript(contents="export default { name: 'first' };"))
    right = VitePlugin(script=ViteScript(contents="export default { name: 'first' };"))

    assert left == right
    assert hash(left) == hash(right)


def test_vite_plugin_accepts_explicit_module_script_types():
    plugin = VitePlugin(
        script=Script(
            contents="export default { name: 'typed-script' };",
            inputs=type(None),
            outputs=object,
        ),
    )

    assert isinstance(plugin.script, ViteScript)
    assert plugin.script.source_path is None


def test_vite_plugin_rejects_non_script_values():
    with pytest.raises(TypeError, match="gdansk_runtime\\.Script"):
        VitePlugin(script="plugins/append-comment.mjs")  # ty: ignore[invalid-argument-type]
