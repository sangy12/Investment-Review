"""Long remote OAuth redirects must not hit the tty canonical line limit."""
import hashlib
import json
import os
import select
import subprocess
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX tty regression")


@pytest.mark.parametrize("eof", [False, True])
def test_long_private_input_and_terminal_restoration(eof):
    import pty
    import termios

    master, slave = pty.openpty()
    before = termios.tcgetattr(slave)
    payload = b"fixture-private-callback-" * 300
    code = '''import hashlib,json
from tradingagents.watchlist.auth import read_private_terminal
try:
 value=read_private_terminal('READY: ')
 print(json.dumps({'length':len(value),'digest':hashlib.sha256(value.encode()).hexdigest()}))
except EOFError:
 print(json.dumps({'error':'EOFError'}))
'''
    process = subprocess.Popen([sys.executable, "-c", code], stdin=slave, stdout=slave,
                               stderr=slave, start_new_session=True)
    output = bytearray()
    try:
        deadline = time.monotonic() + 10
        while b"READY:" not in output and time.monotonic() < deadline:
            if select.select([master], [], [], 0.1)[0]:
                output.extend(os.read(master, 65536))
        assert b"READY:" in output
        pending = b"\x04" if eof else payload + b"\n"
        while pending:
            sent = os.write(master, pending)
            pending = pending[sent:]
        while process.poll() is None and time.monotonic() < deadline:
            if select.select([master], [], [], 0.1)[0]:
                output.extend(os.read(master, 65536))
        process.wait(timeout=2)
        while select.select([master], [], [], 0)[0]:
            output.extend(os.read(master, 65536))
        assert payload[:30] not in output
        line = next(line for line in output.decode().splitlines() if line.startswith('{'))
        result = json.loads(line)
        if eof:
            assert result == {"error": "EOFError"}
        else:
            assert result == {"length": len(payload), "digest": hashlib.sha256(payload).hexdigest()}
        assert termios.tcgetattr(slave) == before
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)
        os.close(slave)


def test_browser_callback_process_exit_restores_waiting_daemon_terminal():
    import pty
    import termios

    master, slave = pty.openpty()
    before = termios.tcgetattr(slave)
    code = '''import threading,time
from tradingagents.watchlist.auth import read_private_terminal
threading.Thread(target=lambda:read_private_terminal('READY: '),daemon=True).start()
time.sleep(0.5)
'''
    process = subprocess.Popen([sys.executable, '-c', code], stdin=slave, stdout=slave,
                               stderr=slave, start_new_session=True)
    try:
        process.wait(timeout=5)
        assert process.returncode == 0
        assert termios.tcgetattr(slave) == before
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)
        os.close(slave)
