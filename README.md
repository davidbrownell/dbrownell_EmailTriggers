# dbrownell-emailtriggers

Scripts run when email is received.

Requires Python 3.14.

## Local development

Dependencies are declared in [requirements.txt](requirements.txt):

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python main.py
```

## Deploying to Bluehost

### Why this is necessary

Bluehost shared hosting provides no root access, an old system Python, and no
compiler toolchain worth relying on, so Python 3.14 has to be installed into the
home directory as a prebuilt, self-contained interpreter.
[python-build-standalone](https://github.com/astral-sh/python-build-standalone)
publishes exactly that: a relocatable CPython with OpenSSL, SQLite, libffi and
friends bundled in, requiring only glibc 2.17+.

The complication is that the host **blocks symlink creation**. This breaks the
process in two separate places:

1. `tar` cannot extract the archive's symlink members.
2. `python -m venv` calls `os.symlink('lib', 'lib64')` without a `try`/`except`
   (see `venv/__init__.py`), so venv creation aborts outright — `--copies` does
   not help, because that flag only governs the interpreter, not this call.

The steps below work around both. Neither workaround is a hack against Python
itself; they just pre-satisfy the conditions that the symlinks would have.

### Steps

Enable SSH access in cPanel first, then confirm the platform is compatible:

```bash
uname -m       # expect x86_64
ldd --version  # expect >= 2.17
```

#### 1. Resolve the latest release asset

Release tags are dates, so the URL is looked up rather than hardcoded. Note that
GitHub percent-encodes the `+` in the filename as `%2B` — matching a literal `+`
finds nothing.

```bash
PYVER=3.14
URL=$(curl -s https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest \
  | grep -o "https://[^\"]*cpython-${PYVER}\.[0-9]*%2B[0-9]*-x86_64-unknown-linux-gnu-install_only_stripped\.tar\.gz" \
  | head -1)
echo "$URL"
```

Use the baseline `x86_64-unknown-linux-gnu` build, not the `x86_64_v2/v3/v4`
variants — the CPU on a shared host is not under your control, and a mismatch is
an immediate `SIGILL`.

#### 2. Download and extract

```bash
mkdir -p ~/opt && cd ~/opt
curl -L -o "python-${PYVER}.tar.gz" "$URL"
tar xzf "python-${PYVER}.tar.gz" --exclude='python/share/*' || true
```

`|| true` is required: `tar` exits non-zero after failing on the symlink members,
having successfully extracted everything else.

Excluding `python/share/*` drops the bundled terminfo database — 2871 of the
archive's 4568 files, and 1038 of its 1047 symlinks. The system's
`/usr/share/terminfo` covers the REPL and readline. Re-extract that subtree if
`curses` misbehaves.

#### 3. Recreate the interpreter names

Of the nine remaining symlinks, only these two matter. Hard links are a separate
permission from symlinks and generally still work; `cp` is the fallback.

```bash
cd ~/opt/python/bin
ln "python${PYVER}" python3 2>/dev/null || cp "python${PYVER}" python3
ln "python${PYVER}" python  2>/dev/null || cp "python${PYVER}" python
~/opt/python/bin/python3 -VV
```

`lib/libpython3.14.so` is only the linker name and does not need recreating —
libpython is statically linked into the interpreter, which depends on nothing
beyond glibc.

#### 4. Create the virtual environment

Pre-creating `lib64` as a real directory makes venv's `os.path.exists` guard skip
the symlink it would otherwise fail on. This is safe here because the
python-build-standalone build sets `PLATLIBDIR = "lib"`, so nothing ever resolves
into `lib64`.

```bash
cd ~/dbrownell_EmailTriggers
mkdir -p .venv/lib64
~/opt/python/bin/python3 -m venv --copies .venv
```

Optionally collapse the interpreter copies. `venv` writes `python`, `python3` and
`python3.14` into `.venv/bin`; with `--copies` those are three independent 32 MB
files:

```bash
cd .venv/bin && rm -f python3 "python${PYVER}" \
  && ln python python3 && ln python "python${PYVER}" && cd ../..
```

#### 5. Install dependencies and run

`pip` ships with the python-build-standalone build, so nothing else needs to be
installed on the host:

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python main.py
```

Invoke by absolute path from cron jobs and mail pipes rather than relying on
`activate`, since those run with a minimal environment.
