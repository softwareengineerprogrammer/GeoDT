from pathlib import Path
import os
import time
import inspect
from typing import Optional


def generate_pin() -> int:
    return int(time.time())


def build_path(pin: int, file_name: str, run_name: Optional[str] = None) -> str:
    if run_name is None:
        run_name = Path(inspect.stack()[1].filename).name.replace('.py', '')
    output_dir = Path(
        'build',
        run_name,
        str(pin)
    )

    if not output_dir.exists():
        os.makedirs(output_dir)

    return str(Path(output_dir, file_name))
