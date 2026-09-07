from pathlib import Path  # noqa: TC003 - typer evaluates annotations at runtime
from typing import Annotated

import requests
import typer

from dbrownell_Common.Streams.DoneManager import DoneManager, Flags as DoneManagerFlags
from typer.core import TyperGroup

from dbrownell_EmailTriggers.lib.host_info import HostInfo


# ----------------------------------------------------------------------
class NaturalOrderGrouper(TyperGroup):  # noqa: D101
    # ----------------------------------------------------------------------
    def list_commands(self, *args, **kwargs) -> list[str]:  # noqa: ARG002, D102
        return list(self.commands.keys())  # pragma: no cover


# ----------------------------------------------------------------------
app = typer.Typer(
    cls=NaturalOrderGrouper,
    help=__doc__,
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
    pretty_exceptions_enable=False,
)


# ----------------------------------------------------------------------
@app.command("EntryPoint", no_args_is_help=True)
def EntryPoint(
    host_info_filename: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Path to a file that contains information about the host.",
        ),
    ],
    new_email_address: Annotated[
        str,
        typer.Argument(help="New email address that will forward to a destination."),
    ],
    destination_email_address: Annotated[
        str,
        typer.Argument(help="Destination email address that will receive forwarded emails."),
    ],
    verbose: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--verbose", help="Write verbose information to the terminal."),
    ] = False,
    debug: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--debug", help="Write debug information to the terminal."),
    ] = False,
) -> None:
    """Create a forwarding address using cpanel endpoints."""

    with DoneManager.CreateCommandLine(
        flags=DoneManagerFlags.Create(verbose=verbose, debug=debug),
    ) as dm:
        host_info = HostInfo.FromFile(host_info_filename)

        new_email_address_parts = new_email_address.split("@")
        assert len(new_email_address_parts) == 2, new_email_address  # noqa: PLR2004

        args = {
            "cpanel_jsonapi_version": "2",
            "cpanel_jsonapi_module": "Email",
            "cpanel_jsonapi_func": "addforward",
            "domain": new_email_address_parts[1].lower(),
            "email": new_email_address_parts[0],
            "fwdopt": "fwd",
            "fwdemail": destination_email_address,
        }

        url = "https://{hostname}:2083/json-api/cpanel?{args}".format(
            hostname=host_info.hostname,
            args="&".join("{}={}".format(tag, value) for tag, value in args.items()),
        )

        response = requests.get(
            url,
            headers={
                "Authorization": f"cpanel {host_info.username}:{host_info.cpanel_api_token}",
            },
            timeout=30,
        )

        response.raise_for_status()
        response = response.json()

        data = response["cpanelresult"]

        if "error" in data:
            raise Exception(data["error"])

        dm.WriteLine(f"'{new_email_address}' will now forward to '{destination_email_address}'.")


# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
if __name__ == "__main__":
    app()  # pragma: no cover
