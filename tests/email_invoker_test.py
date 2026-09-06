import email
import re
import smtplib
import sys
import textwrap

from dataclasses import dataclass, field
from pathlib import Path

import pytest
import yaml

from dbrownell_Common import SubprocessEx
from typer.testing import CliRunner

from dbrownell_EmailTriggers import email_invoker


CLI_RUNNER = CliRunner()

# Names are matched without regard to case, so the sample data intentionally mixes casing.
DOMAIN_DATA = [
    {
        "name": "example.com",
        "mail_server": "mail.example.com",
        "response_email_address": "email-triggers@example.com",
        "port": 993,
        "users": [
            {
                "name": "bob",
                "scripts": [
                    {
                        "name": "do the thing",
                        "command_line_template": "do_the_thing.py",
                    },
                    {
                        "name": "Do The Other Thing",
                        "command_line_template": "do_the_other_thing.py",
                    },
                    {
                        "name": "all values",
                        "command_line_template": "run.py {email_invoker_command}|{domain}|{user}|{script}|{from}|{to}|{subject}|{content}",
                    },
                    {
                        "name": "headers",
                        "command_line_template": "run.py {x-custom}|{received}",
                    },
                    {
                        "name": "unknown value",
                        "command_line_template": "run.py {does_not_exist}",
                    },
                ],
            },
            {
                "name": "Alice",
                "scripts": [
                    {
                        "name": "backup",
                        "command_line_template": "backup.py",
                    },
                ],
            },
        ],
    },
    {
        "name": "Other.com",
        "mail_server": "mail.other.com",
        "response_email_address": "email-triggers@other.com",
        "port": None,
        "users": [
            {
                "name": "carol",
                "scripts": [
                    {
                        "name": "status",
                        "command_line_template": "status.py",
                    },
                ],
            },
        ],
    },
]


# ----------------------------------------------------------------------
def _MakeMessage(
    msg_from: str = "bob@example.com",
    subject: str = "Do the thing",
    body: str = "This is the body.",
) -> str:
    return textwrap.dedent(
        """\
        To: <recipient@example.com>
        From: "Bob Smith" <{msg_from}>
        Subject: {subject}

        {body}
        """,
    ).format(msg_from=msg_from, subject=subject, body=body)


VALID_MESSAGE = _MakeMessage()


# ----------------------------------------------------------------------
@pytest.fixture
def log_filename(tmp_path, monkeypatch) -> Path:
    """Redirect the error log so tests never write to the installed package."""

    filename = tmp_path / "error.log"
    monkeypatch.setattr(email_invoker, "LOG_FILENAME", filename)

    return filename


# ----------------------------------------------------------------------
@dataclass(frozen=True)
class SentMail:
    """A single message handed to the mail server."""

    host: str
    port: int
    from_addr: str
    to_addrs: list[str]
    content: str


# ----------------------------------------------------------------------
@dataclass
class MailServer:
    """Activity recorded by the `mail_server` fixture."""

    sent: list[SentMail]
    quit_count: int


# ----------------------------------------------------------------------
@pytest.fixture(autouse=True)
def mail_server(monkeypatch) -> MailServer:
    """Capture response emails so tests never connect to a real mail server."""

    server = MailServer([], 0)

    # ----------------------------------------------------------------------
    class FakeSmtp:
        # ----------------------------------------------------------------------
        def __init__(self):
            self.host = ""
            self.port = -1

        # ----------------------------------------------------------------------
        def connect(self, host, port=0):
            self.host = host
            self.port = port

            return 220, b"ok"

        # ----------------------------------------------------------------------
        def sendmail(self, from_addr, to_addrs, msg):
            server.sent.append(SentMail(self.host, self.port, from_addr, to_addrs, msg))

            return {}

        # ----------------------------------------------------------------------
        def quit(self):
            server.quit_count += 1

            return 221, b"ok"

    # ----------------------------------------------------------------------

    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)

    return server


# ----------------------------------------------------------------------
@dataclass
class ScriptRunner:
    """Activity recorded by (and behavior configured for) the `script_runner` fixture."""

    command_lines: list[str] = field(default_factory=list)
    returncode: int = 0
    output: str = "Script output.\n"


# ----------------------------------------------------------------------
_REAL_RUN = SubprocessEx.Run


# ----------------------------------------------------------------------
@pytest.fixture(autouse=True)
def script_runner(monkeypatch) -> ScriptRunner:
    """Capture generated command lines so tests never launch real processes."""

    runner = ScriptRunner()

    # ----------------------------------------------------------------------
    def FakeRun(command_line, *args, **kwargs) -> SubprocessEx.RunResult:  # noqa: ARG001
        runner.command_lines.append(command_line)

        return SubprocessEx.RunResult(
            runner.returncode,
            runner.output,
            command_line if runner.returncode != 0 else None,
        )

    # ----------------------------------------------------------------------

    monkeypatch.setattr(SubprocessEx, "Run", FakeRun)

    return runner


# ----------------------------------------------------------------------
@pytest.fixture
def real_script_runner(monkeypatch) -> None:
    """Undo the `script_runner` patch for tests that launch real processes."""

    monkeypatch.setattr(SubprocessEx, "Run", _REAL_RUN)


# ----------------------------------------------------------------------
@pytest.fixture
def domain_info_filename(tmp_path) -> Path:
    filename = tmp_path / "domain_info.yaml"
    filename.write_text(yaml.safe_dump(DOMAIN_DATA), encoding="utf-8")

    return filename


# ----------------------------------------------------------------------
def _Invoke(
    domain_info_filename: Path,
    content: str,
    command: str = "do the thing",
) -> int:
    result = CLI_RUNNER.invoke(
        email_invoker.app,
        [str(domain_info_filename), command],
        input=content,
    )

    return result.exit_code


# ----------------------------------------------------------------------
def _AssertNoError(log_filename: Path) -> None:
    assert not log_filename.is_file(), log_filename.read_text(encoding="utf-8")


# ----------------------------------------------------------------------
def _AssertError(log_filename: Path, expected_final_line: str) -> None:
    assert log_filename.is_file()

    log_content = log_filename.read_text(encoding="utf-8")

    assert "Traceback (most recent call last):" in log_content, log_content
    assert log_content.rstrip().splitlines()[-1] == expected_final_line, log_content


# ----------------------------------------------------------------------
def _AssertResponse(
    mail: SentMail,
    subject: str,
    content: str,
    result: int = 0,
    host: str = "mail.example.com",
    port: int = 993,
    from_addr: str = "email-triggers@example.com",
    to_addr: str = "bob@example.com",
) -> None:
    assert mail.host == host
    assert mail.port == port
    assert mail.from_addr == from_addr
    assert mail.to_addrs == [to_addr]

    msg = email.message_from_string(mail.content)

    assert msg["From"] == from_addr
    assert msg["To"] == to_addr

    # The elapsed time within the subject varies from run to run.
    match = re.fullmatch(
        r"\[(?P<disposition>\w+)\] (?P<subject>.*) \[(?P<result>-?\d+), \d+:\d{2}:\d{2}(?:\.\d+)?\]",
        msg["Subject"],
    )

    assert match, msg["Subject"]
    assert match.group("disposition") == ("Success" if result == 0 else "Failure")
    assert match.group("subject") == subject
    assert match.group("result") == str(result)

    assert msg.get_payload() == f"\r\n{content}"


# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
class TestCommandLine:
    # ----------------------------------------------------------------------
    def test_NoArgsIsHelp(self):
        result = CLI_RUNNER.invoke(email_invoker.app, [])

        assert result.exit_code == 2

    # ----------------------------------------------------------------------
    def test_MissingCommand(self, log_filename, domain_info_filename):
        result = CLI_RUNNER.invoke(
            email_invoker.app,
            [str(domain_info_filename)],
            input=VALID_MESSAGE,
        )

        assert result.exit_code == 2
        _AssertNoError(log_filename)

    # ----------------------------------------------------------------------
    def test_Standard(self, log_filename, domain_info_filename):
        assert _Invoke(domain_info_filename, VALID_MESSAGE) == 0
        _AssertNoError(log_filename)

    # ----------------------------------------------------------------------
    def test_DomainInfoFilenameEnvVarIsUnreachable(self, log_filename, domain_info_filename):
        # Both parameters are positional, so a lone value is consumed by `domain_info_filename`
        # rather than by `command`; the environment variable can never supply the filename.
        result = CLI_RUNNER.invoke(
            email_invoker.app,
            ["do the thing"],
            input=VALID_MESSAGE,
            env={"EMAIL_TRIGGERS_DOMAIN_INFO_FILENAME": str(domain_info_filename)},
        )

        assert result.exit_code == 2
        _AssertNoError(log_filename)

    # ----------------------------------------------------------------------
    def test_MissingDomainInfoFile(self, log_filename, tmp_path):
        # The argument is validated by typer, so the error is surfaced to the caller rather than
        # written to the log.
        assert _Invoke(tmp_path / "does_not_exist.yaml", VALID_MESSAGE) == 2
        _AssertNoError(log_filename)

    # ----------------------------------------------------------------------
    def test_DomainInfoDirectory(self, log_filename, tmp_path):
        assert _Invoke(tmp_path, VALID_MESSAGE) == 2
        _AssertNoError(log_filename)

    # ----------------------------------------------------------------------
    def test_UnsupportedDomainInfoFileType(self, log_filename, tmp_path):
        filename = tmp_path / "domain_info.txt"
        filename.touch()

        assert _Invoke(filename, VALID_MESSAGE) == 0
        _AssertError(log_filename, f"ValueError: '{filename}' is not a supported file type.")


# ----------------------------------------------------------------------
class TestValidContent:
    # ----------------------------------------------------------------------
    @pytest.mark.parametrize(
        "from_value",
        [
            '"Bob Smith" <bob@example.com>',
            "Bob Smith <bob@example.com>",
            "bob <bob@example.com>",
        ],
    )
    def test_FromVariations(self, log_filename, domain_info_filename, from_value):
        content = textwrap.dedent(
            """\
            To: <recipient@example.com>
            From: {}
            Subject: Do the thing

            This is the body.
            """,
        ).format(from_value)

        assert _Invoke(domain_info_filename, content) == 0
        _AssertNoError(log_filename)

    # ----------------------------------------------------------------------
    @pytest.mark.parametrize(
        ("to_value", "expected"),
        [
            # The trailing '>' is retained because the closing bracket is optional within the
            # expression used to extract the address.
            ("<recipient@example.com>", "recipient@example.com>"),
            ("recipient@example.com", "recipient@example.com"),
        ],
    )
    def test_ToVariations(self, log_filename, domain_info_filename, script_runner, to_value, expected):
        content = textwrap.dedent(
            """\
            To: {}
            From: "Bob Smith" <bob@example.com>
            Subject: Do the thing

            This is the body.
            """,
        ).format(to_value)

        assert _Invoke(domain_info_filename, content, "all values") == 0
        _AssertNoError(log_filename)

        assert script_runner.command_lines == [
            f"run.py all values|example.com|bob|all values|bob@example.com|{expected}|do the thing|This is the body.\n"
        ]

    # ----------------------------------------------------------------------
    def test_MultilineContent(self, log_filename, domain_info_filename, script_runner):
        content = textwrap.dedent(
            """\
            To: <recipient@example.com>
            From: "Bob Smith" <bob@example.com>
            Subject: Do the thing

            Line 1

            Line 2
            """,
        )

        assert _Invoke(domain_info_filename, content, "all values") == 0
        _AssertNoError(log_filename)

        assert script_runner.command_lines == [
            "run.py all values|example.com|bob|all values|bob@example.com|recipient@example.com>|do the thing|Line 1\n\nLine 2\n"
        ]

    # ----------------------------------------------------------------------
    def test_DuplicateHeadersBecomeLists(self, log_filename, domain_info_filename, script_runner):
        # A header seen twice is converted to a list; a header seen a third time is appended to
        # that list.
        content = textwrap.dedent(
            """\
            To: <recipient@example.com>
            From: "Bob Smith" <bob@example.com>
            Subject: Do the thing
            X-Custom: custom value
            Received: one
            Received: two
            Received: three

            This is the body.
            """,
        )

        assert _Invoke(domain_info_filename, content, "headers") == 0
        _AssertNoError(log_filename)

        assert script_runner.command_lines == ["run.py custom value|['one', 'two', 'three']"]

    # ----------------------------------------------------------------------
    def test_MalformedHeaderLineIsNotFatal(self, log_filename, domain_info_filename):
        content = textwrap.dedent(
            """\
            To: <recipient@example.com>
            this line is not a header
            From: "Bob Smith" <bob@example.com>
            Subject: Do the thing

            This is the body.
            """,
        )

        assert _Invoke(domain_info_filename, content) == 0
        _AssertNoError(log_filename)


# ----------------------------------------------------------------------
class TestInvalidContent:
    """Parse failures are written to `LOG_FILENAME` rather than surfaced to the caller."""

    # ----------------------------------------------------------------------
    @pytest.mark.parametrize(
        ("description", "content"),
        [
            ("empty", ""),
            (
                "no separator between the headers and the content",
                "To: <recipient@example.com>\nFrom: <bob@example.com>\nSubject: Do the thing\n",
            ),
            ("no content", "To: <recipient@example.com>\n\n"),
            (
                "missing 'to'",
                'From: "Bob Smith" <bob@example.com>\nSubject: Do the thing\n\nThis is the body.\n',
            ),
            (
                "missing 'from'",
                "To: <recipient@example.com>\nSubject: Do the thing\n\nThis is the body.\n",
            ),
            (
                "missing 'subject'",
                'To: <recipient@example.com>\nFrom: "Bob Smith" <bob@example.com>\n\nThis is the body.\n',
            ),
            (
                "'from' without an email address",
                "To: <recipient@example.com>\nFrom: Bob Smith\nSubject: Do the thing\n\nThis is the body.\n",
            ),
            (
                "duplicate 'to'",
                'To: <a@example.com>\nTo: <b@example.com>\nFrom: "Bob" <bob@example.com>\nSubject: Do the thing\n\nThis is the body.\n',
            ),
            (
                "duplicate 'from'",
                'To: <a@example.com>\nFrom: "Bob" <bob@example.com>\nFrom: "Sue" <sue@example.com>\nSubject: Do the thing\n\nThis is the body.\n',
            ),
            (
                "duplicate 'subject'",
                'To: <a@example.com>\nFrom: "Bob" <bob@example.com>\nSubject: One\nSubject: Two\n\nThis is the body.\n',
            ),
        ],
    )
    def test_ErrorIsLogged(self, log_filename, domain_info_filename, description, content):
        assert _Invoke(domain_info_filename, content) == 0, description

        assert log_filename.is_file(), description

        log_content = log_filename.read_text(encoding="utf-8")

        assert "Traceback (most recent call last):" in log_content, description
        assert "AssertionError" in log_content, description

    # ----------------------------------------------------------------------
    def test_ErrorsAreAppended(self, log_filename, domain_info_filename):
        assert _Invoke(domain_info_filename, "") == 0
        assert _Invoke(domain_info_filename, "") == 0

        log_content = log_filename.read_text(encoding="utf-8")

        assert log_content.count("Traceback (most recent call last):") == 2


# ----------------------------------------------------------------------
class TestDomainLookup:
    # ----------------------------------------------------------------------
    @pytest.mark.parametrize(
        ("msg_from", "command"),
        [
            ("bob@EXAMPLE.COM", "do the thing"),
            ("carol@other.com", "status"),
            ("carol@OTHER.COM", "status"),
        ],
    )
    def test_CaseInsensitive(self, log_filename, domain_info_filename, msg_from, command):
        assert _Invoke(domain_info_filename, _MakeMessage(msg_from), command) == 0
        _AssertNoError(log_filename)

    # ----------------------------------------------------------------------
    def test_UnsupportedDomain(self, log_filename, domain_info_filename):
        assert _Invoke(domain_info_filename, _MakeMessage("bob@unknown.com")) == 0
        _AssertError(log_filename, "ValueError: 'unknown.com' is not a supported domain.")

    # ----------------------------------------------------------------------
    def test_NoDomains(self, log_filename, tmp_path):
        filename = tmp_path / "domain_info.yaml"
        filename.write_text("[]", encoding="utf-8")

        assert _Invoke(filename, VALID_MESSAGE) == 0
        _AssertError(log_filename, "ValueError: 'example.com' is not a supported domain.")


# ----------------------------------------------------------------------
class TestUserLookup:
    # ----------------------------------------------------------------------
    def test_CaseInsensitive(self, log_filename, domain_info_filename):
        assert _Invoke(domain_info_filename, _MakeMessage("ALICE@example.com"), "backup") == 0
        _AssertNoError(log_filename)

    # ----------------------------------------------------------------------
    def test_UnsupportedUser(self, log_filename, domain_info_filename):
        assert _Invoke(domain_info_filename, _MakeMessage("dave@example.com")) == 0
        _AssertError(
            log_filename,
            "ValueError: 'dave' is not a supported user for domain 'example.com'.",
        )

    # ----------------------------------------------------------------------
    def test_UserFromAnotherDomain(self, log_filename, domain_info_filename):
        # 'carol' is a user of 'other.com' only.
        assert _Invoke(domain_info_filename, _MakeMessage("carol@example.com"), "status") == 0
        _AssertError(
            log_filename,
            "ValueError: 'carol' is not a supported user for domain 'example.com'.",
        )


# ----------------------------------------------------------------------
class TestScriptLookup:
    """The script is selected by the `command` argument rather than by the subject of the email."""

    # ----------------------------------------------------------------------
    @pytest.mark.parametrize(
        "command",
        [
            "Do the other thing",
            "do the other thing",
            "DO THE OTHER THING",
            "   Do The Other Thing   ",
        ],
    )
    def test_CaseAndWhitespaceInsensitive(self, log_filename, domain_info_filename, command):
        assert _Invoke(domain_info_filename, VALID_MESSAGE, command) == 0
        _AssertNoError(log_filename)

    # ----------------------------------------------------------------------
    def test_SubjectDoesNotSelectTheScript(self, log_filename, domain_info_filename, script_runner):
        assert _Invoke(domain_info_filename, _MakeMessage(subject="backup"), "do the thing") == 0
        _AssertNoError(log_filename)

        assert script_runner.command_lines == ["do_the_thing.py"]

    # ----------------------------------------------------------------------
    @pytest.mark.parametrize(
        ("command", "expected_name"),
        [
            ("not a script", "not a script"),
            # The prefix normalization applied to the subject is not applied to the command.
            ("Re: do the thing", "re: do the thing"),
            ("", ""),
        ],
    )
    def test_UnsupportedScript(self, log_filename, domain_info_filename, command, expected_name):
        assert _Invoke(domain_info_filename, VALID_MESSAGE, command) == 0
        _AssertError(
            log_filename,
            f"ValueError: '{expected_name}' is not a supported script for user 'bob' in domain 'example.com'.",
        )

    # ----------------------------------------------------------------------
    def test_ScriptFromAnotherUser(self, log_filename, domain_info_filename):
        # 'backup' belongs to 'alice'.
        assert _Invoke(domain_info_filename, VALID_MESSAGE, "backup") == 0
        _AssertError(
            log_filename,
            "ValueError: 'backup' is not a supported script for user 'bob' in domain 'example.com'.",
        )


# ----------------------------------------------------------------------
class TestCommandLineTemplate:
    # ----------------------------------------------------------------------
    def test_AllValues(self, log_filename, domain_info_filename, script_runner):
        assert _Invoke(domain_info_filename, VALID_MESSAGE, "  All Values  ") == 0
        _AssertNoError(log_filename)

        assert script_runner.command_lines == [
            "run.py   All Values  |example.com|bob|all values|bob@example.com|recipient@example.com>|do the thing|This is the body.\n"
        ]

    # ----------------------------------------------------------------------
    @pytest.mark.parametrize(
        "subject",
        [
            "Do the thing",
            "do the thing",
            "DO THE THING",
            "   Do the thing   ",
            "Re: Do the thing",
            "RE:Do the thing",
            "Fwd: Do the thing",
            "Fw: Do the thing",
            "- Do the thing",
            ": Do the thing",
            ". Do the thing",
            "Fwd: Re: Do the thing",
            "Re: - Fwd: Do the thing",
        ],
    )
    def test_SubjectNormalization(self, log_filename, domain_info_filename, script_runner, subject):
        assert _Invoke(domain_info_filename, _MakeMessage(subject=subject), "all values") == 0
        _AssertNoError(log_filename)

        assert script_runner.command_lines == [
            "run.py all values|example.com|bob|all values|bob@example.com|recipient@example.com>|do the thing|This is the body.\n"
        ]

    # ----------------------------------------------------------------------
    def test_SubjectIsNothingButPrefixes(self, log_filename, domain_info_filename, script_runner):
        assert _Invoke(domain_info_filename, _MakeMessage(subject="Re: Fwd:"), "all values") == 0
        _AssertNoError(log_filename)

        assert script_runner.command_lines == [
            "run.py all values|example.com|bob|all values|bob@example.com|recipient@example.com>||This is the body.\n"
        ]

    # ----------------------------------------------------------------------
    def test_ContentIsUnquoted(self, log_filename, domain_info_filename, script_runner):
        assert _Invoke(domain_info_filename, _MakeMessage(body="Hello%20World%21"), "all values") == 0
        _AssertNoError(log_filename)

        assert script_runner.command_lines == [
            "run.py all values|example.com|bob|all values|bob@example.com|recipient@example.com>|do the thing|Hello World!\n"
        ]

    # ----------------------------------------------------------------------
    def test_UnknownValue(self, log_filename, domain_info_filename, script_runner, mail_server):
        assert _Invoke(domain_info_filename, VALID_MESSAGE, "unknown value") == 0
        _AssertError(log_filename, "KeyError: 'does_not_exist'")

        assert script_runner.command_lines == []
        assert mail_server.sent == []


# ----------------------------------------------------------------------
class TestResponseSubjectAndContent:
    """The first line of the output becomes the subject when it is followed by a blank line."""

    # ----------------------------------------------------------------------
    @pytest.mark.parametrize(
        ("description", "output", "expected_subject", "expected_content"),
        [
            ("no output", "", "Do the thing", ""),
            ("a single line", "Only line\n", "Only line", ""),
            ("a single line without a newline", "Only line", "Only line", ""),
            ("two lines", "One\nTwo\n", "Do the thing", "One\nTwo"),
            ("three lines separated by a blank line", "Subject\n\nBody\n", "Subject", "Body"),
            (
                "many lines separated by a blank line",
                "Subject\n\nBody 1\nBody 2\n",
                "Subject",
                "Body 1\nBody 2",
            ),
            (
                "many lines separated by a whitespace-only line",
                "Subject\n   \nBody 1\nBody 2\n",
                "Subject",
                "Body 1\nBody 2",
            ),
            (
                "many lines without a blank line",
                "Line 1\nLine 2\nLine 3\n",
                "Do the thing",
                "Line 1\nLine 2\nLine 3",
            ),
            (
                "a blank line that is not the second line",
                "Line 1\nLine 2\n\nLine 4\n",
                "Do the thing",
                "Line 1\nLine 2\n\nLine 4",
            ),
        ],
    )
    def test_Output(
        self,
        log_filename,
        domain_info_filename,
        script_runner,
        mail_server,
        description,
        output,
        expected_subject,
        expected_content,
    ):
        script_runner.output = output

        # The command is used as the subject verbatim, so its casing is preserved.
        assert _Invoke(domain_info_filename, VALID_MESSAGE, "Do the thing") == 0, description
        _AssertNoError(log_filename)

        assert len(mail_server.sent) == 1, description
        _AssertResponse(mail_server.sent[0], expected_subject, expected_content)

    # ----------------------------------------------------------------------
    @pytest.mark.parametrize("returncode", [1, 3, -1])
    def test_Failure(self, log_filename, domain_info_filename, script_runner, mail_server, returncode):
        script_runner.returncode = returncode
        script_runner.output = "It went badly\n"

        assert _Invoke(domain_info_filename, VALID_MESSAGE) == 0
        _AssertNoError(log_filename)

        assert len(mail_server.sent) == 1
        _AssertResponse(mail_server.sent[0], "It went badly", "", result=returncode)


# ----------------------------------------------------------------------
class TestResponseEmail:
    # ----------------------------------------------------------------------
    def test_Standard(self, log_filename, domain_info_filename, mail_server):
        assert _Invoke(domain_info_filename, VALID_MESSAGE) == 0
        _AssertNoError(log_filename)

        assert len(mail_server.sent) == 1
        _AssertResponse(mail_server.sent[0], "Script output.", "")

    # ----------------------------------------------------------------------
    def test_NoPortConnectsToZero(self, log_filename, domain_info_filename, mail_server):
        assert _Invoke(domain_info_filename, _MakeMessage("carol@other.com"), "status") == 0
        _AssertNoError(log_filename)

        assert len(mail_server.sent) == 1
        _AssertResponse(
            mail_server.sent[0],
            "Script output.",
            "",
            host="mail.other.com",
            port=0,
            from_addr="email-triggers@other.com",
            to_addr="carol@other.com",
        )

    # ----------------------------------------------------------------------
    def test_RecipientPreservesCase(self, log_filename, domain_info_filename, mail_server):
        # The response is addressed to the sender as written rather than to the lowercased name
        # used for the lookup.
        assert _Invoke(domain_info_filename, _MakeMessage("ALICE@example.com"), "backup") == 0
        _AssertNoError(log_filename)

        assert len(mail_server.sent) == 1
        _AssertResponse(mail_server.sent[0], "Script output.", "", to_addr="ALICE@example.com")

    # ----------------------------------------------------------------------
    def test_ConnectionIsClosed(self, log_filename, domain_info_filename, mail_server):
        assert _Invoke(domain_info_filename, VALID_MESSAGE) == 0
        _AssertNoError(log_filename)

        assert mail_server.quit_count == 1

    # ----------------------------------------------------------------------
    @pytest.mark.parametrize(
        ("description", "content", "command"),
        [
            ("unparsable message", "", "do the thing"),
            ("unsupported domain", _MakeMessage("bob@unknown.com"), "do the thing"),
            ("unsupported user", _MakeMessage("dave@example.com"), "do the thing"),
            ("unsupported script", VALID_MESSAGE, "not a script"),
        ],
    )
    def test_NoResponseOnError(
        self,
        log_filename,
        domain_info_filename,
        mail_server,
        description,
        content,
        command,
    ):
        assert _Invoke(domain_info_filename, content, command) == 0, description

        assert log_filename.is_file(), description
        assert mail_server.sent == [], description

    # ----------------------------------------------------------------------
    def test_SmtpFailureIsLogged(self, log_filename, domain_info_filename, monkeypatch, mail_server):
        # ----------------------------------------------------------------------
        def RaisingConnect(self, host, port=0):
            msg = "unable to connect"
            raise smtplib.SMTPConnectError(421, msg)

        # ----------------------------------------------------------------------

        monkeypatch.setattr(smtplib.SMTP, "connect", RaisingConnect)

        assert _Invoke(domain_info_filename, VALID_MESSAGE) == 0

        assert mail_server.sent == []
        assert mail_server.quit_count == 0

        log_content = log_filename.read_text(encoding="utf-8")

        assert "smtplib.SMTPConnectError" in log_content, log_content


# ----------------------------------------------------------------------
class TestScriptExecution:
    """End-to-end coverage of the processes actually launched for a script."""

    # ----------------------------------------------------------------------
    @pytest.fixture
    def domain_info_filename(self, tmp_path) -> Path:
        python = f'"{sys.executable}"'

        data = [
            {
                "name": "example.com",
                "mail_server": "mail.example.com",
                "response_email_address": "email-triggers@example.com",
                "port": 993,
                "users": [
                    {
                        "name": "bob",
                        "scripts": [
                            {
                                "name": "success",
                                "command_line_template": f"{python} -c \"print('It worked')\"",
                            },
                            {
                                "name": "failure",
                                "command_line_template": f"{python} -c \"import sys; sys.stderr.write('It failed\\n'); sys.exit(3)\"",
                            },
                            {
                                "name": "substitution",
                                "command_line_template": f"{python} -c \"print('{{user}} of {{domain}}')\"",
                            },
                        ],
                    },
                ],
            },
        ]

        filename = tmp_path / "domain_info.yaml"
        filename.write_text(yaml.safe_dump(data), encoding="utf-8")

        return filename

    # ----------------------------------------------------------------------
    def test_Success(self, log_filename, domain_info_filename, real_script_runner, mail_server):
        assert _Invoke(domain_info_filename, VALID_MESSAGE, "success") == 0
        _AssertNoError(log_filename)

        assert len(mail_server.sent) == 1
        _AssertResponse(mail_server.sent[0], "It worked", "")

    # ----------------------------------------------------------------------
    def test_Failure(self, log_filename, domain_info_filename, real_script_runner, mail_server):
        # Standard error is folded into the output of the process.
        assert _Invoke(domain_info_filename, VALID_MESSAGE, "failure") == 0
        _AssertNoError(log_filename)

        assert len(mail_server.sent) == 1
        _AssertResponse(mail_server.sent[0], "It failed", "", result=3)

    # ----------------------------------------------------------------------
    def test_Substitution(self, log_filename, domain_info_filename, real_script_runner, mail_server):
        assert _Invoke(domain_info_filename, VALID_MESSAGE, "substitution") == 0
        _AssertNoError(log_filename)

        assert len(mail_server.sent) == 1
        _AssertResponse(mail_server.sent[0], "bob of example.com", "")
