import re
import sys
import textwrap
import traceback

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer

from dbrownell_Common.Streams.DoneManager import DoneManager, Flags as DoneManagerFlags
from typer.core import TyperGroup


# ----------------------------------------------------------------------
class NaturalOrderGrouper(TyperGroup):
    # ----------------------------------------------------------------------
    def list_commands(self, *args, **kwargs) -> list[str]:
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
LOG_FILENAME = Path(__file__).parent / "email_invoker.log"


# ----------------------------------------------------------------------
@dataclass(frozen=True)
class MessageInfo:
    msg_to: str
    msg_from: str
    msg_subject: str
    headers: dict[str, str | list[str]]
    content: str
    errors: list[str]


# ----------------------------------------------------------------------
@app.command("EntryPoint", no_args_is_help=True)
def EntryPoint(
    command: Annotated[str, typer.Argument(help="The command to invoke.")],
    verbose: Annotated[
        bool,
        typer.Option("--verbose", help="Write verbose information to the terminal."),
    ] = False,
    debug: Annotated[
        bool,
        typer.Option("--debug", help="Write debug information to the terminal."),
    ] = False,
) -> None:
    """Invoke functionality based on an incoming email."""

    with DoneManager.CreateCommandLine(
        flags=DoneManagerFlags.Create(verbose=verbose, debug=debug),
    ) as dm:
        try:
            message = _ParseMessage(sys.stdin.read())

            with LOG_FILENAME.open("a", encoding="utf-8") as f:
                f.write(f"\n\n{message}\n\n")

        except Exception as ex:
            with LOG_FILENAME.open("a", encoding="utf-8") as f:
                traceback.print_exception(ex, file=f)


# ----------------------------------------------------------------------
def _ParseMessage(raw_message: str) -> MessageInfo:
    errors: list[str] = []

    # Get the major sections
    raw_match = re.match(
        textwrap.dedent(
            """\
            (?P<headers>.+?)

            (?P<content>.+)""",
        ),
        raw_message,
        re.MULTILINE | re.DOTALL,
    )

    assert raw_match, raw_message

    # Parse the headers
    headers: dict[str, str | list[str]] = {}
    header_re = re.compile(r"^(?P<prefix>\S+?):\s*(?P<suffix>.+)$")

    for line in raw_match.group("headers").splitlines():
        match = header_re.match(line)
        if not match:
            errors.append(f"Invalid header encountered: '{line}'")
            continue

        tag = match.group("prefix").lower()
        value = match.group("suffix").strip()

        if tag in headers:
            if not isinstance(headers[tag], list):
                assert isinstance(headers[tag], str), headers[tag]
                headers[tag] = [headers[tag]]

            assert isintance(headers[tag], list), headers[tag]
            headers[tag].append(value)
        else:
            headers[tag] = value

    # To
    assert "to" in headers, headers
    match = re.match(r"<{0,1}(?P<email>.+)>{0,1}", headers["to"])
    assert match, headers["to"]

    msg_to = match.group("email")

    # From
    assert "from" in headers, headers
    match = re.match(
        r'^(?P<quote>"{0,1})(?P<content>.+)(?P=quote) <(?P<email>.+)>$', headers["from"]
    )
    assert match, headers["from"]

    msg_from = match.group("email")

    # Subject
    assert "subject" in headers, headers
    msg_subject = headers["subject"]

    return MessageInfo(
        msg_to,
        msg_from,
        msg_subject,
        headers,
        raw_match.group("content"),
        errors,
    )


# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
if __name__ == "__main__":
    app()  # pragma: no cover
