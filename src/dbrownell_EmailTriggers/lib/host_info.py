import json

from typing import TYPE_CHECKING

import yaml

from pydantic import TypeAdapter
from pydantic.dataclasses import dataclass

if TYPE_CHECKING:
    from pathlib import Path


# ----------------------------------------------------------------------
@dataclass(frozen=True)
class HostInfo:
    """Information about a host."""

    hostname: str
    username: str
    cpanel_api_token: str

    # ----------------------------------------------------------------------
    @staticmethod
    def FromFile(filename: Path) -> HostInfo:
        """Create instances of this class based on the contents of the specified file."""

        if filename.suffix.lower() in (".yaml", ".yml"):
            read_func = yaml.safe_load
        elif filename.suffix.lower() == ".json":
            read_func = json.load
        else:
            msg = f"'{filename}' is not a supported file type."
            raise ValueError(msg)

        with filename.open(encoding="utf-8") as f:
            content = read_func(f)

        return _host_info_type_adapter.validate_python(content)


# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
_host_info_type_adapter = TypeAdapter(HostInfo)
