import datetime
import re
import smtplib
import sys
import textwrap
import time
import traceback

from dataclasses import dataclass
from email.mime.text import MIMEText
from pathlib import Path
from typing import Annotated, cast
from urllib.parse import unquote

import typer

from dbrownell_Common import SubprocessEx
from typer.core import TyperGroup

from dbrownell_EmailTriggers.lib.domain_info import DomainInfo, UserInfo, ScriptInfo


# ----------------------------------------------------------------------
LOG_FILENAME = Path(__file__).parent.parent.with_suffix(".log")  # Repo root
assert (LOG_FILENAME.parent / ".git").is_dir(), LOG_FILENAME.parent


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
def EntryPoint(  # noqa: PLR0915
    domain_info_filename: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Path to a file that contains information about the domain.",
        ),
    ],
    command: Annotated[
        str,
        typer.Argument(help="The command to invoke based on the incoming email."),
    ],
) -> None:
    """Invoke functionality when an email is received."""

    try:
        message = _MessageInfo.FromContent(sys.stdin.read())

        # Get the domain
        domain_name = message.msg_from.split("@")[-1].lower()
        domain_info: DomainInfo | None = None

        for potential_domain_info in DomainInfo.FromFile(domain_info_filename):
            if potential_domain_info.name.lower() == domain_name:
                domain_info = potential_domain_info
                break

        if domain_info is None:
            msg = f"'{domain_name}' is not a supported domain."
            raise ValueError(msg)

        # Get the user within the domain
        user_name = message.msg_from.split("@")[0].lower()
        user_info: UserInfo | None = None

        for potential_user_info in domain_info.users:
            if potential_user_info.name.lower() == user_name:
                user_info = potential_user_info
                break

        if user_info is None:
            msg = f"'{user_name}' is not a supported user for domain '{domain_name}'."
            raise ValueError(msg)

        # Get the script within the user
        script_name = command.strip().lower()
        script_info: ScriptInfo | None = None

        for potential_script_info in user_info.scripts:
            if potential_script_info.name.lower() == script_name:
                script_info = potential_script_info
                break

        if script_info is None:
            msg = (
                f"'{script_name}' is not a supported script for user '{user_name}' in domain '{domain_name}'."
            )
            raise ValueError(msg)

        # Invoke the functionality
        template_values = dict(message.headers)

        template_values["email_invoker_command"] = command
        template_values["from"] = message.msg_from
        template_values["to"] = message.msg_to
        template_values["subject"] = _NormalizeSubject(message.msg_subject)
        template_values["content"] = unquote(message.content)
        template_values["domain"] = domain_name
        template_values["user"] = user_name
        template_values["script"] = script_name

        command_line = script_info.command_line_template.format(**template_values)

        start_time = time.perf_counter()

        run_result = SubprocessEx.Run(command_line)

        result = run_result.returncode
        content = run_result.output

        # Create the subject
        lines = content.splitlines()

        if len(lines) == 1:
            response_subject = lines[0]
            content = ""
        elif len(lines) > 2 and not lines[1].strip():  # noqa: PLR2004
            response_subject = lines[0]
            content = "\n".join(lines[2:])
        else:
            response_subject = command
            content = "\n".join(lines)

        # Calculate execution time
        current_time = time.perf_counter()

        assert start_time <= current_time, (start_time, current_time)
        time_delta = str(datetime.timedelta(seconds=current_time - start_time))

        # Email the response
        msg = MIMEText("")

        msg["Subject"] = (
            f"[{'Success' if result == 0 else 'Failure'}] {response_subject} [{result}, {time_delta}]"
        )
        msg["From"] = domain_info.response_email_address
        msg["To"] = message.msg_from

        s = smtplib.SMTP()

        s.connect(
            domain_info.mail_server,
            port=domain_info.port or 0,
        )

        s.sendmail(
            msg["From"],
            [msg["To"]],
            f"{msg.as_string()}\r\n{content}",
        )

        s.quit()

    except:  # noqa: E722
        with LOG_FILENAME.open("a", encoding="utf-8") as f:
            traceback.print_exc(file=f)


# ----------------------------------------------------------------------
# |
# |  Private Types
# |
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class _MessageInfo:
    """Information about an incoming email message."""

    msg_to: str
    msg_from: str
    msg_subject: str
    headers: dict[str, str | list[str]]
    content: str
    errors: list[str]

    # ----------------------------------------------------------------------
    @classmethod
    def FromContent(cls, raw_content: str) -> _MessageInfo:
        """Create an instance of this class based on the specified content."""

        errors: list[str] = []

        # Get the major sections
        raw_match = re.match(
            textwrap.dedent(
                """\
                (?P<headers>.+?)

                (?P<content>.+)""",
            ),
            raw_content,
            re.MULTILINE | re.DOTALL,
        )

        assert raw_match, raw_content

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
                    headers[tag] = [cast(str, headers[tag])]

                assert isinstance(headers[tag], list), headers[tag]
                cast(list[str], headers[tag]).append(value)
            else:
                headers[tag] = value

        # To
        assert "to" in headers, headers
        assert isinstance(headers["to"], str), headers["to"]
        match = re.match(r"<{0,1}(?P<email>.+)>{0,1}", headers["to"])
        assert match, headers["to"]

        msg_to = match.group("email")

        # From
        assert "from" in headers, headers
        assert isinstance(headers["from"], str), headers["from"]
        match = re.match(r'^(?P<quote>"{0,1})(?P<content>.+)(?P=quote) <(?P<email>.+)>$', headers["from"])
        assert match, headers["from"]

        msg_from = match.group("email")

        # Subject
        assert "subject" in headers, headers
        assert isinstance(headers["subject"], str), headers["subject"]
        msg_subject = headers["subject"]

        # Create the instance
        return cls(
            msg_to=msg_to,
            msg_from=msg_from,
            msg_subject=msg_subject,
            headers=headers,
            content=raw_match.group("content"),
            errors=errors,
        )


# ----------------------------------------------------------------------
# |
# |  Private Functions
# |
# ----------------------------------------------------------------------
def _NormalizeSubject(subject: str) -> str:
    """Normalize the subject of an email message."""

    subject = subject.strip().lower()

    while True:
        if not subject:
            break

        found = False

        for potential_prefix in [":", "-", ".", "re:", "fwd:", "fw:"]:
            if subject.startswith(potential_prefix):
                subject = subject[len(potential_prefix) :].strip()
                found = True
                break

        if not found:
            break

    return subject


# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
if __name__ == "__main__":
    app()  # pragma: no cover
