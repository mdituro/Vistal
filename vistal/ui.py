"""Minimal user interaction that works from a terminal, a desktop session, or
Steam's Game Mode (gamescope shows zenity/kdialog windows of the launched
process tree), and degrades to safe defaults when nobody can answer.

Select a backend with VISTAL_UI=auto|tty|zenity|kdialog|none.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Sequence

from .log import LOG


class Progress:
    def update(self, fraction: float, text: str = "") -> bool:
        """Report progress; returns False if the user cancelled."""
        return True

    def close(self) -> None:
        pass

    def __enter__(self) -> "Progress":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class UI:
    name = "none"

    def info(self, title: str, text: str) -> None:
        LOG.info("%s: %s", title, text)

    def error(self, title: str, text: str) -> None:
        LOG.error("%s: %s", title, text)

    def confirm(self, title: str, text: str, default: bool = True) -> bool:
        LOG.info("%s: %s -> %s (non-interactive default)", title, text, "yes" if default else "no")
        return default

    def choose(self, title: str, text: str, options: Sequence[str], default: int = 0) -> int | None:
        if not options:
            return None
        LOG.info("%s: %s -> %s (non-interactive default)", title, text, options[default])
        return default

    def progress(self, title: str, text: str) -> Progress:
        return _LogProgress(title)


class _LogProgress(Progress):
    def __init__(self, title: str):
        self.title = title
        self._last = -1

    def update(self, fraction: float, text: str = "") -> bool:
        pct = int(fraction * 100)
        if pct // 10 != self._last // 10:
            LOG.info("%s: %d%%", self.title, pct)
        self._last = pct
        return True


class TtyUI(UI):
    name = "tty"

    def info(self, title: str, text: str) -> None:
        print(f"\n== {title} ==\n{text}", file=sys.stderr)

    def error(self, title: str, text: str) -> None:
        print(f"\n!! {title} !!\n{text}", file=sys.stderr)

    def confirm(self, title: str, text: str, default: bool = True) -> bool:
        hint = "[Y/n]" if default else "[y/N]"
        try:
            ans = input(f"\n{title}: {text} {hint} ").strip().lower()
        except EOFError:
            return default
        if not ans:
            return default
        return ans.startswith("y")

    def choose(self, title: str, text: str, options: Sequence[str], default: int = 0) -> int | None:
        if not options:
            return None
        print(f"\n{title}: {text}", file=sys.stderr)
        for i, opt in enumerate(options, 1):
            mark = "*" if i - 1 == default else " "
            print(f" {mark}{i}) {opt}", file=sys.stderr)
        while True:
            try:
                ans = input(f"Choice [1-{len(options)}, Enter={default + 1}, q=cancel]: ").strip().lower()
            except EOFError:
                return default
            if not ans:
                return default
            if ans == "q":
                return None
            if ans.isdigit() and 1 <= int(ans) <= len(options):
                return int(ans) - 1

    def progress(self, title: str, text: str) -> Progress:
        return _TtyProgress(title)


class _TtyProgress(Progress):
    def __init__(self, title: str):
        self.title = title

    def update(self, fraction: float, text: str = "") -> bool:
        bar = int(fraction * 30)
        short = (text[-40:]) if text else ""
        sys.stderr.write(f"\r{self.title} [{'#' * bar}{'.' * (30 - bar)}] {int(fraction * 100):3d}% {short:<40}")
        sys.stderr.flush()
        return True

    def close(self) -> None:
        sys.stderr.write("\n")


class ZenityUI(UI):
    name = "zenity"

    def __init__(self, exe: str):
        self.exe = exe

    def _run(self, args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run([self.exe, *args], capture_output=True, text=True)

    def info(self, title: str, text: str) -> None:
        self._run(["--info", "--title", title, "--text", text, "--width", "480"])

    def error(self, title: str, text: str) -> None:
        self._run(["--error", "--title", title, "--text", text, "--width", "480"])

    def confirm(self, title: str, text: str, default: bool = True) -> bool:
        return self._run(["--question", "--title", title, "--text", text, "--width", "480"]).returncode == 0

    def choose(self, title: str, text: str, options: Sequence[str], default: int = 0) -> int | None:
        if not options:
            return None
        args = ["--list", "--title", title, "--text", text, "--column", "#", "--column", "Option",
                "--hide-column", "1", "--print-column", "1", "--width", "640", "--height", "420"]
        for i, opt in enumerate(options):
            args += [str(i), opt]
        res = self._run(args)
        out = res.stdout.strip().split("|")[0]
        if res.returncode != 0 or not out.isdigit():
            return None
        return int(out)

    def progress(self, title: str, text: str) -> Progress:
        return _PipeProgress([self.exe, "--progress", "--title", title, "--text", text,
                              "--auto-close", "--width", "480"], zenity=True)


class KdialogUI(UI):
    name = "kdialog"

    def __init__(self, exe: str):
        self.exe = exe

    def _run(self, args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run([self.exe, *args], capture_output=True, text=True)

    def info(self, title: str, text: str) -> None:
        self._run(["--title", title, "--msgbox", text])

    def error(self, title: str, text: str) -> None:
        self._run(["--title", title, "--error", text])

    def confirm(self, title: str, text: str, default: bool = True) -> bool:
        return self._run(["--title", title, "--yesno", text]).returncode == 0

    def choose(self, title: str, text: str, options: Sequence[str], default: int = 0) -> int | None:
        if not options:
            return None
        args = ["--title", title, "--menu", text]
        for i, opt in enumerate(options):
            args += [str(i), opt]
        res = self._run(args)
        out = res.stdout.strip()
        return int(out) if res.returncode == 0 and out.isdigit() else None

    def progress(self, title: str, text: str) -> Progress:
        # kdialog progress needs D-Bus plumbing; a log-only bar is good enough.
        return _LogProgress(title)


class _PipeProgress(Progress):
    def __init__(self, cmd: list[str], zenity: bool):
        self.proc: subprocess.Popen | None
        try:
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, text=True,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            self.proc = None
        self._last = -1

    def update(self, fraction: float, text: str = "") -> bool:
        if not self.proc or not self.proc.stdin:
            return True
        if self.proc.poll() is not None:
            return self.proc.returncode == 0  # closed by user => cancelled
        pct = min(99, int(fraction * 100))  # 100 auto-closes the window
        if pct == self._last and not text:
            return True
        self._last = pct
        try:
            if text:
                self.proc.stdin.write(f"# {text}\n")
            self.proc.stdin.write(f"{pct}\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            return False
        return True

    def close(self) -> None:
        if not self.proc:
            return
        try:
            if self.proc.stdin:
                self.proc.stdin.write("100\n")
                self.proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def _has_display() -> bool:
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


_current: UI | None = None


def get() -> UI:
    global _current
    if _current is not None:
        return _current
    want = os.environ.get("VISTAL_UI", "auto").lower()
    zen = shutil.which("zenity")
    kd = shutil.which("kdialog")
    if want == "none":
        _current = UI()
    elif want == "tty" or (want == "auto" and sys.stdin.isatty() and sys.stderr.isatty()):
        _current = TtyUI()
    elif want in ("auto", "zenity") and zen and _has_display():
        _current = ZenityUI(zen)
    elif want in ("auto", "kdialog") and kd and _has_display():
        _current = KdialogUI(kd)
    else:
        _current = UI()
    return _current


def set_ui(ui: UI | None) -> None:
    global _current
    _current = ui
