import shutil
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def setup_paths() -> Generator[tuple[Path, Path], None, None]:
    cwd = Path("tests").resolve(strict=True)
    output_path = Path(tempfile.mkdtemp(prefix="mkslides_")).resolve(strict=False)

    yield cwd, output_path

    if output_path.exists():
        shutil.rmtree(output_path)
