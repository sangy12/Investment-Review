"""Seed the official writable auth store once from an injected secret file."""

import json
import os
from contextlib import suppress
from pathlib import Path


def read_private_terminal(prompt):
    """Accept a secret only at a trusted terminal, without an echoed fallback."""
    import sys

    if not sys.stdin.isatty():
        raise EOFError("Paste the callback in an interactive trusted terminal")
    if os.name == "posix":
        return _read_posix_secret(prompt, sys.stdin.fileno(), sys.stderr)
    return _read_getpass_secret(prompt, sys.stderr)


def _read_getpass_secret(prompt, output):
    import getpass
    import warnings

    # getpass normally falls back to echoed input when terminal control fails.
    # Refuse that fallback: callbacks and provider keys are credentials.
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            return getpass.getpass(prompt, stream=output)
    except getpass.GetPassWarning:
        raise EOFError("Terminal cannot hide callback input") from None


def _read_posix_secret(prompt, descriptor, output):
    """No echo, no canonical 4095-byte line truncation; restore tty on every exit."""
    import atexit
    import termios

    previous = termios.tcgetattr(descriptor)
    current = termios.tcgetattr(descriptor)
    current[3] &= ~(termios.ECHO | termios.ECHONL | termios.ICANON)
    current[6][termios.VMIN] = 1
    current[6][termios.VTIME] = 0
    value = bytearray()

    def restore():
        with suppress(OSError):
            termios.tcsetattr(descriptor, termios.TCSADRAIN, previous)

    # A successful HTTP callback can end the main process while the daemon
    # paste-reader is waiting. Restore tty state on that path as well.
    atexit.register(restore)
    try:
        termios.tcsetattr(descriptor, termios.TCSAFLUSH, current)
        output.write(prompt)
        output.flush()
        while True:
            char = os.read(descriptor, 1)
            if not char or char == b"\x04":
                raise EOFError("Secret input ended")
            if char in (b"\r", b"\n"):
                return value.decode("utf-8")
            if char in (b"\x7f", b"\x08"):
                if value:
                    value.pop()
            elif char == b"\x15":
                value.clear()
            else:
                value.extend(char)
            if len(value) > 65536:
                raise EOFError("Secret input exceeds maximum length")
    finally:
        restore()
        atexit.unregister(restore)
        output.write("\n")
        output.flush()


def read_login_callback():
    """Accept a loopback redirect only at a trusted terminal, without echoing it."""
    return read_private_terminal("完整回调地址（输入隐藏，粘贴后按回车）：")


def bootstrap_auth(source=None):
    source = source or os.environ.get("TRADINGAGENTS_CHATGPT_AUTH_SOURCE")
    raw = os.environ.get("TRADINGAGENTS_CHATGPT_AUTH_JSON")
    if not source and not raw:
        return
    from tradingagents.llm_clients import chatgpt_auth

    target = chatgpt_auth.AUTH_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    from tradingagents.dataflows.files import locked

    with locked(target):
        # A persistent refreshed token wins over the original seed on restarts.
        current = chatgpt_auth._read()
        if current.get("tokens"):
            return
        data = json.loads(Path(source).read_text(encoding="utf-8") if source else raw)
        if (not isinstance(data, dict) or not data.get("host_id")
                or not isinstance(data.get("account"), dict)
                or not data["account"].get("client_id")
                or not isinstance(data.get("tokens"), dict)
                or not data["tokens"].get("access_token")
                or not data["tokens"].get("refresh_token")):
            raise ValueError("注入文件须为官方 tradingagents login chatgpt 生成的完整登录文件")
        # Official VM import contract: retain a distinct stable ID for this VM,
        # not the ID copied from the machine which completed OAuth.
        data["host_id"] = chatgpt_auth._host_id(current)
        chatgpt_auth._write(data)  # official 0600 atomic writer


def prepare_login_host():
    """Persist this host's identity before the first OAuth attempt, even if it fails."""
    from tradingagents.dataflows.files import locked
    from tradingagents.llm_clients import chatgpt_auth

    target = chatgpt_auth.AUTH_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    with locked(target):
        data = chatgpt_auth._read()
        if not data.get("host_id"):
            data["host_id"] = chatgpt_auth._host_id(data)
            chatgpt_auth._write(data)
