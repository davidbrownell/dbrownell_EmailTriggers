**Project:**
[![License](https://img.shields.io/github/license/davidbrownell/dbrownell_EmailTriggers?color=dark-green)](https://github.com/davidbrownell/dbrownell_EmailTriggers/blob/master/LICENSE)

**Package:**
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/dbrownell_EmailTriggers?color=dark-green)](https://pypi.org/project/dbrownell_EmailTriggers/)
[![PyPI - Version](https://img.shields.io/pypi/v/dbrownell_EmailTriggers?color=dark-green)](https://pypi.org/project/dbrownell_EmailTriggers/)
[![PyPI - Downloads](https://img.shields.io/pypi/dm/dbrownell_EmailTriggers)](https://pypistats.org/packages/dbrownell-emailtriggers)

**Development:**
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![ty](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json)](https://github.com/astral-sh/ty)
[![pytest](https://img.shields.io/badge/pytest-enabled-brightgreen)](https://docs.pytest.org/)
[![CI](https://github.com/davidbrownell/dbrownell_EmailTriggers/actions/workflows/CICD.yml/badge.svg)](https://github.com/davidbrownell/dbrownell_EmailTriggers/actions/workflows/CICD.yml)
[![Code Coverage](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/davidbrownell/f15146b1b8fdc0a5d45ac0eb786a84f7/raw/dbrownell_EmailTriggers_code_coverage.json)](https://github.com/davidbrownell/dbrownell_EmailTriggers/actions)
[![GitHub commit activity](https://img.shields.io/github/commit-activity/y/davidbrownell/dbrownell_EmailTriggers?color=dark-green)](https://github.com/davidbrownell/dbrownell_EmailTriggers/commits/main/)

<!-- Content above this delimiter will be copied to the generated README.md file. DO NOT REMOVE THIS COMMENT, as it will cause regeneration to fail. -->

## Contents
- [Overview](#overview)
- [Installation](#installation)
- [Development](#development)
- [Additional Information](#additional-information)
- [License](#license)

## Overview
`dbrownell_EmailTriggers` runs scripts on a server when email is received and replies to the sender with the results.

A mail server is configured to pipe messages sent to a specific address into `email_invoker`. The sender's email address and a command name select a script from a configuration file; that script is run and its output is emailed back to the sender.

| Command Line Tool | Description |
| --- | --- |
| `email_invoker` | Reads an email message from `stdin`, runs the script associated with the sender and the command, and emails the results to the sender. |
| `create_email_forwarder` | Creates an email forwarding address using [cPanel](https://cpanel.net/) endpoints. |

### How to use `dbrownell_EmailTriggers`

#### Describing domains, users, and scripts
`email_invoker` is driven by a YAML or JSON file (the file extension determines how it is parsed) that lists the domains that are served, the users within each domain that may invoke scripts, and the scripts available to each of those users. Complete samples are available at [domain_info.yaml](https://github.com/davidbrownell/dbrownell_EmailTriggers/blob/main/src/dbrownell_EmailTriggers/samples/domain_info.yaml) and [domain_info.json](https://github.com/davidbrownell/dbrownell_EmailTriggers/blob/main/src/dbrownell_EmailTriggers/samples/domain_info.json).

```yaml
- name: example.com
  mail_server: mail.example.com
  response_email_address: email-triggers@example.com

  # Set to null to use the mail server's default port.
  port: 993

  users:
    - name: alice
      scripts:
        - name: backup
          command_line_template: python /opt/scripts/backup.py --target "{subject}"
```

| Value | Description |
| --- | --- |
| `name` (domain) | Domain of the sender's email address (the text after `@`). |
| `mail_server` | Server used to send the response. |
| `port` | Port of the mail server; `null` uses the server's default. |
| `response_email_address` | Address that the response is sent from. |
| `name` (user) | Username of the sender's email address (the text before `@`). |
| `name` (script) | Command that selects this script. |
| `command_line_template` | Command line to run; see [Command line templates](#command-line-templates). |

Domain, user, and script names are matched without regard to case. A message whose sender or command does not match an entry is not processed, which means that access is limited to the addresses explicitly listed in this file.

#### Invoking scripts
Configure the mail server to pipe incoming messages to:

```shell
python -m dbrownell_EmailTriggers.email_invoker <domain_info_filename> <command>
```

The raw message (headers, a blank line, then the body) is read from `stdin`. `<command>` is matched against the script names available to the sender; it is not derived from the message itself, so a distinct address can be dedicated to each command.

`email_invoker` never writes to `stdout` and always exits with a return code of zero so that the mail server does not generate bounce messages. Errors are appended to the `src.log` file in the root of this repository, and no response is sent when one occurs. That path is resolved relative to the source file and is verified to be a git clone, so `email_invoker` must be run from a clone rather than from an installed package.

#### Command line templates
`command_line_template` is a Python format string. These values are available:

| Value | Description |
| --- | --- |
| `{email_invoker_command}` | `<command>` exactly as provided on the command line. |
| `{domain}` | Domain of the sender, lowercased. |
| `{user}` | Username of the sender, lowercased. |
| `{script}` | Name of the script that was matched, lowercased. |
| `{from}` | Email address of the sender. |
| `{to}` | Email address of the recipient. |
| `{subject}` | Subject, lowercased and stripped of leading `re:`, `fwd:`, `fw:`, `:`, `-`, and `.` prefixes. |
| `{content}` | Body of the message, url-decoded. |
| `{<header>}` | Any email header, lowercased (for example, `{x-custom}`). A header that appears more than once is a list of values. |

#### Interpreting the response
The subject of the response is:

```
[Success|Failure] <subject> [<return code>, <elapsed time>]
```

`Success` corresponds to a return code of zero. `<subject>` is taken from the output of the script: a single line of output becomes the subject and the body is empty; a short first line (fewer than 20 characters) followed by a blank line becomes the subject and the remaining lines become the body. Otherwise, `<command>` becomes the subject and all output becomes the body.

#### Creating a forwarding address
`create_email_forwarder` creates the forwarding address that routes email to `email_invoker` on hosts managed by cPanel.

```shell
python -m dbrownell_EmailTriggers.create_email_forwarder <host_info_filename> <new_email_address> <destination_email_address>
```

`<host_info_filename>` is a YAML or JSON file containing the credentials used to reach the cPanel endpoints; complete samples are available at [host_info.yaml](https://github.com/davidbrownell/dbrownell_EmailTriggers/blob/main/src/dbrownell_EmailTriggers/samples/host_info.yaml) and [host_info.json](https://github.com/davidbrownell/dbrownell_EmailTriggers/blob/main/src/dbrownell_EmailTriggers/samples/host_info.json).

```yaml
hostname: hosting.example.com
username: example_user

# Do not commit files that contain real API tokens.
cpanel_api_token: example_token
```

<!-- Content below this delimiter will be copied to the generated README.md file. DO NOT REMOVE THIS COMMENT, as it will cause regeneration to fail. -->

## Installation

| Installation Method | Command |
| --- | --- |
| Via [uv](https://github.com/astral-sh/uv) | `uv add dbrownell_EmailTriggers` |
| Via [pip](https://pip.pypa.io/en/stable/) | `pip install dbrownell_EmailTriggers` |

### Verifying Signed Artifacts
Artifacts are signed and verified using [py-minisign](https://github.com/x13a/py-minisign) and the public key in the file `./minisign_key.pub`.

To verify that an artifact is valid, visit [the latest release](https://github.com/davidbrownell/dbrownell_EmailTriggers/releases/latest) and download the `.minisign` signature file that corresponds to the artifact, then run the following command, replacing `<filename>` with the name of the artifact to be verified:

```shell
uv run --with py-minisign python -c "import minisign; minisign.PublicKey.from_file('minisign_key.pub').verify_file('<filename>'); print('The file has been verified.')"
```

## Development
Please visit [Contributing](https://github.com/davidbrownell/dbrownell_EmailTriggers/blob/main/CONTRIBUTING.md) and [Development](https://github.com/davidbrownell/dbrownell_EmailTriggers/blob/main/DEVELOPMENT.md) for information on contributing to this project.

## Additional Information
Additional information can be found at these locations.

| Title | Document | Description |
| --- | --- | --- |
| Code of Conduct | [CODE_OF_CONDUCT.md](https://github.com/davidbrownell/dbrownell_EmailTriggers/blob/main/CODE_OF_CONDUCT.md) | Information about the norms, rules, and responsibilities we adhere to when participating in this open source community. |
| Contributing | [CONTRIBUTING.md](https://github.com/davidbrownell/dbrownell_EmailTriggers/blob/main/CONTRIBUTING.md) | Information about contributing to this project. |
| Development | [DEVELOPMENT.md](https://github.com/davidbrownell/dbrownell_EmailTriggers/blob/main/DEVELOPMENT.md) | Information about development activities involved in making changes to this project. |
| Governance | [GOVERNANCE.md](https://github.com/davidbrownell/dbrownell_EmailTriggers/blob/main/GOVERNANCE.md) | Information about how this project is governed. |
| Maintainers | [MAINTAINERS.md](https://github.com/davidbrownell/dbrownell_EmailTriggers/blob/main/MAINTAINERS.md) | Information about individuals who maintain this project. |
| Security | [SECURITY.md](https://github.com/davidbrownell/dbrownell_EmailTriggers/blob/main/SECURITY.md) | Information about how to privately report security issues associated with this project. |

## License
`dbrownell_EmailTriggers` is licensed under the <a href="https://choosealicense.com/licenses/MIT/" target="_blank">MIT</a> license.
