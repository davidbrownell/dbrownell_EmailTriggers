from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
import requests
import yaml

from typer.testing import CliRunner

from dbrownell_EmailTriggers import create_email_forwarder


CLI_RUNNER = CliRunner()

HOST_DATA = {
    "hostname": "hosting.example.com",
    "username": "example_user",
    "cpanel_api_token": "example_token",
}

SUCCESS_PAYLOAD = {"cpanelresult": {"data": [{"reason": "OK", "result": 1}]}}


# ----------------------------------------------------------------------
@dataclass(frozen=True)
class SentRequest:
    """A single request handed to the cpanel endpoint."""

    url: str
    headers: dict[str, str]
    timeout: int | None


# ----------------------------------------------------------------------
@dataclass
class Endpoint:
    """Activity recorded by (and behavior configured for) the `endpoint` fixture."""

    sent: list[SentRequest] = field(default_factory=list)
    payload: dict = field(default_factory=lambda: SUCCESS_PAYLOAD)
    error: Exception | None = None

    # ----------------------------------------------------------------------
    @property
    def query(self) -> dict[str, list[str]]:
        assert len(self.sent) == 1, self.sent

        return parse_qs(urlparse(self.sent[0].url).query)


# ----------------------------------------------------------------------
@pytest.fixture(autouse=True)
def endpoint(monkeypatch) -> Endpoint:
    """Capture requests so tests never contact a real cpanel host."""

    result = Endpoint()

    # ----------------------------------------------------------------------
    class FakeResponse:
        # ----------------------------------------------------------------------
        def raise_for_status(self) -> None:
            if result.error is not None:
                raise result.error

        # ----------------------------------------------------------------------
        def json(self) -> dict:
            return result.payload

    # ----------------------------------------------------------------------
    def FakeGet(url, *args, headers=None, timeout=None, **kwargs) -> FakeResponse:  # noqa: ARG001
        result.sent.append(SentRequest(url, headers or {}, timeout))

        return FakeResponse()

    # ----------------------------------------------------------------------

    monkeypatch.setattr(requests, "get", FakeGet)

    return result


# ----------------------------------------------------------------------
@pytest.fixture
def host_info_filename(tmp_path) -> Path:
    filename = tmp_path / "host_info.yaml"
    filename.write_text(yaml.safe_dump(HOST_DATA), encoding="utf-8")

    return filename


# ----------------------------------------------------------------------
def _Invoke(
    host_info_filename: Path,
    new_email_address: str = "new@example.com",
    destination_email_address: str = "destination@other.com",
):
    return CLI_RUNNER.invoke(
        create_email_forwarder.app,
        [str(host_info_filename), new_email_address, destination_email_address],
    )


# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
class TestCommandLine:
    # ----------------------------------------------------------------------
    def test_NoArgsIsHelp(self, endpoint):
        result = CLI_RUNNER.invoke(create_email_forwarder.app, [])

        assert result.exit_code == 2
        assert endpoint.sent == []

    # ----------------------------------------------------------------------
    @pytest.mark.parametrize("num_args", [1, 2])
    def test_MissingArgs(self, host_info_filename, endpoint, num_args):
        args = [str(host_info_filename), "new@example.com"][:num_args]

        result = CLI_RUNNER.invoke(create_email_forwarder.app, args)

        assert result.exit_code == 2
        assert endpoint.sent == []

    # ----------------------------------------------------------------------
    def test_MissingHostInfoFile(self, tmp_path, endpoint):
        assert _Invoke(tmp_path / "does_not_exist.yaml").exit_code == 2
        assert endpoint.sent == []

    # ----------------------------------------------------------------------
    def test_HostInfoDirectory(self, tmp_path, endpoint):
        assert _Invoke(tmp_path).exit_code == 2
        assert endpoint.sent == []

    # ----------------------------------------------------------------------
    def test_UnsupportedHostInfoFileType(self, tmp_path, endpoint):
        filename = tmp_path / "host_info.txt"
        filename.touch()

        result = _Invoke(filename)

        assert result.exit_code != 0
        assert isinstance(result.exception, ValueError)
        assert str(result.exception) == f"'{filename}' is not a supported file type."
        assert endpoint.sent == []

    # ----------------------------------------------------------------------
    @pytest.mark.parametrize("flag", ["--verbose", "--debug"])
    def test_Flags(self, host_info_filename, endpoint, flag):
        result = CLI_RUNNER.invoke(
            create_email_forwarder.app,
            [str(host_info_filename), "new@example.com", "destination@other.com", flag],
        )

        assert result.exit_code == 0
        assert len(endpoint.sent) == 1


# ----------------------------------------------------------------------
class TestRequest:
    # ----------------------------------------------------------------------
    def test_Url(self, host_info_filename, endpoint):
        assert _Invoke(host_info_filename).exit_code == 0

        url = urlparse(endpoint.sent[0].url)

        assert url.scheme == "https"
        assert url.hostname == "hosting.example.com"
        assert url.port == 2083
        assert url.path == "/json-api/cpanel"

    # ----------------------------------------------------------------------
    def test_Query(self, host_info_filename, endpoint):
        assert _Invoke(host_info_filename).exit_code == 0

        assert endpoint.query == {
            "cpanel_jsonapi_version": ["2"],
            "cpanel_jsonapi_module": ["Email"],
            "cpanel_jsonapi_func": ["addforward"],
            "domain": ["example.com"],
            "email": ["new"],
            "fwdopt": ["fwd"],
            "fwdemail": ["destination@other.com"],
        }

    # ----------------------------------------------------------------------
    def test_Authorization(self, host_info_filename, endpoint):
        assert _Invoke(host_info_filename).exit_code == 0

        assert endpoint.sent[0].headers == {"Authorization": "cpanel example_user:example_token"}

    # ----------------------------------------------------------------------
    def test_Timeout(self, host_info_filename, endpoint):
        # An unresponsive host must not hang the process indefinitely.
        assert _Invoke(host_info_filename).exit_code == 0

        assert endpoint.sent[0].timeout == 30

    # ----------------------------------------------------------------------
    def test_DomainIsLowercasedAndNameIsNot(self, host_info_filename, endpoint):
        # cpanel matches the domain without regard to case, but the mailbox name is preserved as
        # provided.
        assert _Invoke(host_info_filename, "New@EXAMPLE.COM").exit_code == 0

        query = endpoint.query

        assert query["domain"] == ["example.com"]
        assert query["email"] == ["New"]

    # ----------------------------------------------------------------------
    def test_Subdomain(self, host_info_filename, endpoint):
        assert _Invoke(host_info_filename, "new@mail.example.com").exit_code == 0

        assert endpoint.query["domain"] == ["mail.example.com"]

    # ----------------------------------------------------------------------
    @pytest.mark.parametrize(
        "new_email_address",
        ["no-at-sign", "too@many@at-signs.com", ""],
    )
    def test_InvalidNewEmailAddress(self, host_info_filename, endpoint, new_email_address):
        result = _Invoke(host_info_filename, new_email_address)

        assert result.exit_code != 0
        assert isinstance(result.exception, AssertionError)
        assert endpoint.sent == []


# ----------------------------------------------------------------------
class TestResponse:
    # ----------------------------------------------------------------------
    # `DoneManager` binds the real `sys.stdout` rather than the stream redirected by `CliRunner`,
    # so success is observed through the exit code and the request that was sent.
    def test_Standard(self, host_info_filename, endpoint):
        result = _Invoke(host_info_filename)

        assert result.exit_code == 0
        assert result.exception is None
        assert len(endpoint.sent) == 1

    # ----------------------------------------------------------------------
    def test_HttpError(self, host_info_filename, endpoint):
        endpoint.error = requests.HTTPError("401 Client Error: Unauthorized")

        result = _Invoke(host_info_filename)

        assert result.exit_code != 0
        assert result.exception is endpoint.error

    # ----------------------------------------------------------------------
    def test_CpanelError(self, host_info_filename, endpoint):
        endpoint.payload = {"cpanelresult": {"error": "the domain does not exist"}}

        result = _Invoke(host_info_filename)

        assert result.exit_code != 0
        assert str(result.exception) == "the domain does not exist"

    # ----------------------------------------------------------------------
    def test_MissingCpanelResult(self, host_info_filename, endpoint):
        endpoint.payload = {}

        result = _Invoke(host_info_filename)

        assert result.exit_code != 0
        assert isinstance(result.exception, KeyError)
