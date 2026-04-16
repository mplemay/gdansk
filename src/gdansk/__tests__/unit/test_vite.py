from __future__ import annotations

import pytest

from gdansk.vite import Vite


def test_vite_rejects_invalid_runtime_port():
    with pytest.raises(ValueError, match="runtime port"):
        Vite(port=0)
