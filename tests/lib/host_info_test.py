import dataclasses
import json
import re

from pathlib import Path

import pytest
import yaml

from pydantic import TypeAdapter, ValidationError

import dbrownell_EmailTriggers

from dbrownell_EmailTriggers.lib.host_info import HostInfo


SAMPLES_DIR = Path(dbrownell_EmailTriggers.__file__).parent / "samples"

HOST_INFO_ADAPTER = TypeAdapter(HostInfo)


# ----------------------------------------------------------------------
@pytest.fixture
def host_data() -> dict:
    return {
        "hostname": "hosting.example.com",
        "username": "example_user",
        "cpanel_api_token": "example_token",
    }


# ----------------------------------------------------------------------
def _AssertMatchesSampleContent(host_info: HostInfo) -> None:
    assert host_info.hostname == "hosting.example.com"
    assert host_info.username == "example_user"
    assert host_info.cpanel_api_token == "example_token"


# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
class TestHostInfo:
    # ----------------------------------------------------------------------
    def test_Construct(self, host_data):
        _AssertMatchesSampleContent(
            HostInfo(host_data["hostname"], host_data["username"], host_data["cpanel_api_token"]),
        )

    # ----------------------------------------------------------------------
    def test_Frozen(self):
        host_info = HostInfo("hosting.example.com", "example_user", "example_token")

        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(host_info, "hostname", "other.example.com")

    # ----------------------------------------------------------------------
    def test_Compare(self):
        assert HostInfo("host", "user", "token") == HostInfo("host", "user", "token")
        assert HostInfo("host", "user", "token") != HostInfo("host", "user", "other")

    # ----------------------------------------------------------------------
    def test_Coerced(self, host_data):
        _AssertMatchesSampleContent(HOST_INFO_ADAPTER.validate_python(host_data))

    # ----------------------------------------------------------------------
    @pytest.mark.parametrize("key", ["hostname", "username", "cpanel_api_token"])
    def test_MissingRequiredValue(self, host_data, key):
        del host_data[key]

        with pytest.raises(ValidationError, match=key):
            HOST_INFO_ADAPTER.validate_python(host_data)

    # ----------------------------------------------------------------------
    def test_InvalidType(self, host_data):
        host_data["hostname"] = 123

        with pytest.raises(ValidationError, match="hostname"):
            HOST_INFO_ADAPTER.validate_python(host_data)


# ----------------------------------------------------------------------
class TestFromFile:
    # ----------------------------------------------------------------------
    def test_YamlSample(self):
        _AssertMatchesSampleContent(HostInfo.FromFile(SAMPLES_DIR / "host_info.yaml"))

    # ----------------------------------------------------------------------
    def test_JsonSample(self):
        _AssertMatchesSampleContent(HostInfo.FromFile(SAMPLES_DIR / "host_info.json"))

    # ----------------------------------------------------------------------
    def test_SamplesAreEquivalent(self):
        assert HostInfo.FromFile(SAMPLES_DIR / "host_info.yaml") == HostInfo.FromFile(
            SAMPLES_DIR / "host_info.json"
        )

    # ----------------------------------------------------------------------
    @pytest.mark.parametrize("suffix", [".yaml", ".yml", ".YAML", ".YML", ".Yml"])
    def test_YamlSuffixes(self, tmp_path, host_data, suffix):
        filename = tmp_path / f"host_info{suffix}"
        filename.write_text(yaml.safe_dump(host_data), encoding="utf-8")

        _AssertMatchesSampleContent(HostInfo.FromFile(filename))

    # ----------------------------------------------------------------------
    @pytest.mark.parametrize("suffix", [".json", ".JSON", ".Json"])
    def test_JsonSuffixes(self, tmp_path, host_data, suffix):
        filename = tmp_path / f"host_info{suffix}"
        filename.write_text(json.dumps(host_data), encoding="utf-8")

        _AssertMatchesSampleContent(HostInfo.FromFile(filename))

    # ----------------------------------------------------------------------
    @pytest.mark.parametrize("suffix", ["", ".txt", ".xml", ".toml", ".yamlx"])
    def test_UnsupportedSuffix(self, tmp_path, suffix):
        filename = tmp_path / f"host_info{suffix}"
        filename.touch()

        with pytest.raises(
            ValueError,
            match=re.escape(f"'{filename}' is not a supported file type."),
        ):
            HostInfo.FromFile(filename)

    # ----------------------------------------------------------------------
    def test_UnsupportedSuffixDoesNotRequireExistingFile(self, tmp_path):
        filename = tmp_path / "does_not_exist.txt"

        with pytest.raises(ValueError, match="is not a supported file type"):
            HostInfo.FromFile(filename)

    # ----------------------------------------------------------------------
    def test_MissingFile(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            HostInfo.FromFile(tmp_path / "does_not_exist.yaml")

    # ----------------------------------------------------------------------
    def test_MissingRequiredValue(self, tmp_path, host_data):
        del host_data["cpanel_api_token"]

        filename = tmp_path / "host_info.yaml"
        filename.write_text(yaml.safe_dump(host_data), encoding="utf-8")

        with pytest.raises(ValidationError, match="cpanel_api_token"):
            HostInfo.FromFile(filename)

    # ----------------------------------------------------------------------
    def test_InvalidValueType(self, tmp_path, host_data):
        host_data["username"] = 123

        filename = tmp_path / "host_info.json"
        filename.write_text(json.dumps(host_data), encoding="utf-8")

        with pytest.raises(ValidationError, match="username"):
            HostInfo.FromFile(filename)

    # ----------------------------------------------------------------------
    def test_InvalidContent(self, tmp_path):
        filename = tmp_path / "host_info.yaml"
        filename.write_text("this is a string, not a mapping", encoding="utf-8")

        with pytest.raises(ValidationError):
            HostInfo.FromFile(filename)

    # ----------------------------------------------------------------------
    def test_ListOfHostsIsNotSupported(self, tmp_path, host_data):
        filename = tmp_path / "host_info.yaml"
        filename.write_text(yaml.safe_dump([host_data]), encoding="utf-8")

        with pytest.raises(ValidationError):
            HostInfo.FromFile(filename)
