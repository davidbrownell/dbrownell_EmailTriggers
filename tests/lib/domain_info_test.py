import dataclasses
import json
import re

from pathlib import Path

import pytest
import yaml

from pydantic import TypeAdapter, ValidationError

import dbrownell_EmailTriggers

from dbrownell_EmailTriggers.lib.domain_info import DomainInfo, ScriptInfo, UserInfo


SAMPLES_DIR = Path(dbrownell_EmailTriggers.__file__).parent / "samples"

SCRIPT_INFO_ADAPTER = TypeAdapter(ScriptInfo)
USER_INFO_ADAPTER = TypeAdapter(UserInfo)
DOMAIN_INFO_ADAPTER = TypeAdapter(DomainInfo)


# ----------------------------------------------------------------------
@pytest.fixture
def domain_data() -> dict:
    return {
        "name": "example.com",
        "mail_server": "mail.example.com",
        "response_email_address": "email-triggers@example.com",
        "port": 993,
        "users": [
            {
                "name": "alice@example.com",
                "scripts": [
                    {
                        "name": "backup",
                        "command_line_template": 'python /opt/scripts/backup.py --target "{subject}"',
                    },
                    {
                        "name": "deploy",
                        "command_line_template": "/opt/scripts/deploy.sh {body}",
                    },
                ],
            },
            {
                "name": "bob@example.com",
                "scripts": [
                    {
                        "name": "status",
                        "command_line_template": "python /opt/scripts/status.py",
                    },
                ],
            },
        ],
    }


# ----------------------------------------------------------------------
def _AssertMatchesSampleContent(domain_info: DomainInfo) -> None:
    assert domain_info.name == "example.com"
    assert domain_info.mail_server == "mail.example.com"
    assert domain_info.response_email_address == "email-triggers@example.com"
    assert domain_info.port == 993

    assert len(domain_info.users) == 2

    alice, bob = domain_info.users

    assert alice.name == "alice@example.com"
    assert [script.name for script in alice.scripts] == ["backup", "deploy"]
    assert alice.scripts[0].command_line_template == 'python /opt/scripts/backup.py --target "{subject}"'
    assert alice.scripts[1].command_line_template == "/opt/scripts/deploy.sh {body}"

    assert bob.name == "bob@example.com"
    assert [script.name for script in bob.scripts] == ["status"]
    assert bob.scripts[0].command_line_template == "python /opt/scripts/status.py"


# ----------------------------------------------------------------------
def _AssertMatchesSampleFile(domain_infos: list[DomainInfo]) -> None:
    assert len(domain_infos) == 2

    _AssertMatchesSampleContent(domain_infos[0])

    other = domain_infos[1]

    assert other.name == "other.com"
    assert other.mail_server == "mail.other.com"
    assert other.response_email_address == "email-triggers@other.com"
    assert other.port is None

    assert len(other.users) == 1
    assert other.users[0].name == "carol@other.com"
    assert other.users[0].scripts == [ScriptInfo("status", "python /opt/scripts/status.py")]


# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
class TestScriptInfo:
    # ----------------------------------------------------------------------
    def test_Construct(self):
        script_info = ScriptInfo("backup", "python backup.py {subject}")

        assert script_info.name == "backup"
        assert script_info.command_line_template == "python backup.py {subject}"

    # ----------------------------------------------------------------------
    def test_Frozen(self):
        script_info = ScriptInfo("backup", "python backup.py")

        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(script_info, "name", "other")

    # ----------------------------------------------------------------------
    def test_InvalidType(self):
        invalid_data: object = {"name": 123, "command_line_template": "python backup.py"}

        with pytest.raises(ValidationError):
            SCRIPT_INFO_ADAPTER.validate_python(invalid_data)


# ----------------------------------------------------------------------
class TestUserInfo:
    # ----------------------------------------------------------------------
    def test_Construct(self):
        script_info = ScriptInfo("backup", "python backup.py")
        user_info = UserInfo("alice@example.com", [script_info])

        assert user_info.name == "alice@example.com"
        assert user_info.scripts == [script_info]

    # ----------------------------------------------------------------------
    def test_NoScripts(self):
        assert UserInfo("alice@example.com", []).scripts == []

    # ----------------------------------------------------------------------
    def test_ScriptsCoercedFromDicts(self):
        data: object = {
            "name": "alice@example.com",
            "scripts": [{"name": "backup", "command_line_template": "python backup.py"}],
        }

        user_info = USER_INFO_ADAPTER.validate_python(data)

        assert user_info.scripts == [ScriptInfo("backup", "python backup.py")]

    # ----------------------------------------------------------------------
    def test_Frozen(self):
        user_info = UserInfo("alice@example.com", [])

        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(user_info, "scripts", [])


# ----------------------------------------------------------------------
class TestDomainInfo:
    # ----------------------------------------------------------------------
    def test_Construct(self, domain_data):
        domain_info = DomainInfo(
            domain_data["name"],
            domain_data["mail_server"],
            domain_data["response_email_address"],
            [
                UserInfo(user["name"], [ScriptInfo(**script) for script in user["scripts"]])
                for user in domain_data["users"]
            ],
            domain_data["port"],
        )

        _AssertMatchesSampleContent(domain_info)

    # ----------------------------------------------------------------------
    def test_NoPort(self):
        assert DomainInfo("example.com", "mail.example.com", "a@example.com", [], None).port is None
        assert DomainInfo("example.com", "mail.example.com", "a@example.com", []).port is None

    # ----------------------------------------------------------------------
    def test_Frozen(self):
        domain_info = DomainInfo("example.com", "mail.example.com", "a@example.com", [], None)

        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(domain_info, "name", "other.com")

    # ----------------------------------------------------------------------
    def test_PortIsOptional(self):
        data_without_port: object = {
            "name": "example.com",
            "mail_server": "mail.example.com",
            "response_email_address": "a@example.com",
            "users": [],
        }

        assert DOMAIN_INFO_ADAPTER.validate_python(data_without_port).port is None


# ----------------------------------------------------------------------
class TestFromFile:
    # ----------------------------------------------------------------------
    def test_YamlSample(self):
        _AssertMatchesSampleFile(DomainInfo.FromFile(SAMPLES_DIR / "domain_info.yaml"))

    # ----------------------------------------------------------------------
    def test_JsonSample(self):
        _AssertMatchesSampleFile(DomainInfo.FromFile(SAMPLES_DIR / "domain_info.json"))

    # ----------------------------------------------------------------------
    def test_SamplesAreEquivalent(self):
        assert DomainInfo.FromFile(SAMPLES_DIR / "domain_info.yaml") == DomainInfo.FromFile(
            SAMPLES_DIR / "domain_info.json"
        )

    # ----------------------------------------------------------------------
    @pytest.mark.parametrize("suffix", [".yaml", ".yml", ".YAML", ".YML", ".Yml"])
    def test_YamlSuffixes(self, tmp_path, domain_data, suffix):
        filename = tmp_path / f"domain_info{suffix}"
        filename.write_text(yaml.safe_dump([domain_data]), encoding="utf-8")

        domain_infos = DomainInfo.FromFile(filename)

        assert len(domain_infos) == 1
        _AssertMatchesSampleContent(domain_infos[0])

    # ----------------------------------------------------------------------
    @pytest.mark.parametrize("suffix", [".json", ".JSON", ".Json"])
    def test_JsonSuffixes(self, tmp_path, domain_data, suffix):
        filename = tmp_path / f"domain_info{suffix}"
        filename.write_text(json.dumps([domain_data]), encoding="utf-8")

        domain_infos = DomainInfo.FromFile(filename)

        assert len(domain_infos) == 1
        _AssertMatchesSampleContent(domain_infos[0])

    # ----------------------------------------------------------------------
    def test_MultipleDomains(self, tmp_path, domain_data):
        other_data = dict(domain_data, name="other.com", mail_server="mail.other.com")

        filename = tmp_path / "domain_info.yaml"
        filename.write_text(yaml.safe_dump([domain_data, other_data]), encoding="utf-8")

        assert [domain_info.name for domain_info in DomainInfo.FromFile(filename)] == [
            "example.com",
            "other.com",
        ]

    # ----------------------------------------------------------------------
    def test_NoDomains(self, tmp_path):
        filename = tmp_path / "domain_info.json"
        filename.write_text("[]", encoding="utf-8")

        assert DomainInfo.FromFile(filename) == []

    # ----------------------------------------------------------------------
    def test_NoPort(self, tmp_path, domain_data):
        domain_data["port"] = None

        filename = tmp_path / "domain_info.yaml"
        filename.write_text(yaml.safe_dump([domain_data]), encoding="utf-8")

        assert DomainInfo.FromFile(filename)[0].port is None

    # ----------------------------------------------------------------------
    @pytest.mark.parametrize("suffix", ["", ".txt", ".xml", ".toml", ".yamlx"])
    def test_UnsupportedSuffix(self, tmp_path, suffix):
        filename = tmp_path / f"domain_info{suffix}"
        filename.touch()

        with pytest.raises(
            ValueError,
            match=re.escape(f"'{filename}' is not a supported file type."),
        ):
            DomainInfo.FromFile(filename)

    # ----------------------------------------------------------------------
    def test_UnsupportedSuffixDoesNotRequireExistingFile(self, tmp_path):
        filename = tmp_path / "does_not_exist.txt"

        with pytest.raises(ValueError, match="is not a supported file type"):
            DomainInfo.FromFile(filename)

    # ----------------------------------------------------------------------
    def test_MissingFile(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            DomainInfo.FromFile(tmp_path / "does_not_exist.yaml")

    # ----------------------------------------------------------------------
    def test_MissingRequiredValue(self, tmp_path, domain_data):
        del domain_data["mail_server"]

        filename = tmp_path / "domain_info.yaml"
        filename.write_text(yaml.safe_dump([domain_data]), encoding="utf-8")

        with pytest.raises(ValidationError, match="mail_server"):
            DomainInfo.FromFile(filename)

    # ----------------------------------------------------------------------
    def test_InvalidValueType(self, tmp_path, domain_data):
        domain_data["port"] = "not a port"

        filename = tmp_path / "domain_info.json"
        filename.write_text(json.dumps([domain_data]), encoding="utf-8")

        with pytest.raises(ValidationError, match="port"):
            DomainInfo.FromFile(filename)

    # ----------------------------------------------------------------------
    def test_InvalidNestedValue(self, tmp_path, domain_data):
        del domain_data["users"][0]["scripts"][0]["command_line_template"]

        filename = tmp_path / "domain_info.yaml"
        filename.write_text(yaml.safe_dump([domain_data]), encoding="utf-8")

        with pytest.raises(ValidationError, match="command_line_template"):
            DomainInfo.FromFile(filename)

    # ----------------------------------------------------------------------
    def test_InvalidContent(self, tmp_path):
        filename = tmp_path / "domain_info.yaml"
        filename.write_text("this is a string, not a list", encoding="utf-8")

        with pytest.raises(ValidationError):
            DomainInfo.FromFile(filename)

    # ----------------------------------------------------------------------
    def test_SingleDomainIsNotAList(self, tmp_path, domain_data):
        filename = tmp_path / "domain_info.yaml"
        filename.write_text(yaml.safe_dump(domain_data), encoding="utf-8")

        with pytest.raises(ValidationError):
            DomainInfo.FromFile(filename)
