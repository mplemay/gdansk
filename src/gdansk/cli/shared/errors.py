from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import TYPE_CHECKING

from belgie.errors import BelgieRuntimeError

if TYPE_CHECKING:
    from collections.abc import Generator


def eprint(message: str) -> None:
    print(message, file=sys.stderr)


@contextmanager
def runtime_errors() -> Generator[None, None, None]:
    try:
        yield
    except BelgieRuntimeError as exc:
        eprint(str(exc))
        raise SystemExit(1) from exc
