"""Template environment setup for rendering gdansk app resources."""

from pathlib import Path
from typing import Final

from minijinja import Environment

from gdansk.metadata import resolve_metadata_url

ENV: Final[Environment] = Environment()
ENV.add_global("resolve_metadata_url", resolve_metadata_url)

for file in Path(__file__).parent.glob("*.html.j2"):
    ENV.add_template(name=file.stem, source=file.read_text(encoding="utf-8"))
