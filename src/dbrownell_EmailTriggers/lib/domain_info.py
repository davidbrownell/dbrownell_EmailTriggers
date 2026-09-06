import json

from typing import TYPE_CHECKING

import yaml

from pydantic import TypeAdapter
from pydantic.dataclasses import dataclass

if TYPE_CHECKING:
    from pathlib import Path


# ----------------------------------------------------------------------
@dataclass(frozen=True)
class ScriptInfo:
    """Information about a script that can be invoked based on an incoming email."""

    name: str
    command_line_template: str


# ----------------------------------------------------------------------
@dataclass(frozen=True)
class UserInfo:
    """Information about a user that can invoke scripts based on an incoming email."""

    name: str
    scripts: list[ScriptInfo]


# ----------------------------------------------------------------------
@dataclass(frozen=True)
class DomainInfo:
    """Information about a domain that has users that can invoke scripts based on an incoming email."""

    name: str
    mail_server: str
    response_email_address: str
    users: list[UserInfo]
    port: int | None = None

    # ----------------------------------------------------------------------
    @staticmethod
    def FromFile(filename: Path) -> list[DomainInfo]:
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

        return _domain_list_type_adapter.validate_python(content)


# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
_domain_list_type_adapter = TypeAdapter(list[DomainInfo])
