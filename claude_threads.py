"""
Live Claude Code threads and what each one needs from you.

Claude Code writes ~/.claude/sessions/<pid>.json for every running thread (status busy or idle)
and a transcript at ~/.claude/projects/<dir>/<session id>.jsonl. The state comes from the two:

  needs_answer  idle, and the last reply asks a question, opens AskUserQuestion or waits on a permission
  working       busy
  current       idle under CURRENT_MINS, nothing asked
  ready_to_wrap idle CURRENT_MINS to STALE_HOURS, nothing asked
  stale         idle over STALE_HOURS
  wrapped       the last turn ran git push (wrap-up commits and pushes), so the tab can close

Run directly to print the table: python3 claude_threads.py
"""

import json
import os
import re
import subprocess
import time
from pathlib import Path

CURRENT_MINS = 30
STALE_HOURS = 8

SESSIONS_DIR = Path.home() / ".claude" / "sessions"
PROJECTS_DIR = Path.home() / ".claude" / "projects"
TREE_ROOT = str(Path.home() / "claude-sessions")
TAIL_BYTES = 256 * 1024

STATES = [
    ("needs_answer", "❓ Needs answer"),
    ("working", "⏳ Working"),
    ("current", "💬 Current"),
    ("ready_to_wrap", "🎁 Ready to wrap"),
    ("wrapped", "✅ Wrapped, close tab"),
    ("stale", "💤 Stale"),
]


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _ttys():
    """pid → tty name (e.g. ttys012) for every process that has one"""
    out = subprocess.run(["ps", "-axo", "pid=,tty="], capture_output=True, text=True).stdout
    ttys = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] != "??":
            ttys[int(parts[0])] = parts[1]
    return ttys


def _tail_entries(path):
    """Transcript entries from the end of the file, newest first"""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - TAIL_BYTES))
        lines = f.read().decode("utf-8", "replace").splitlines()
    if size > TAIL_BYTES:
        lines = lines[1:]  # first line is cut mid-way
    entries = []
    for line in reversed(lines):
        try:
            entries.append(json.loads(line))
        except ValueError:
            pass
    return entries


def _is_prompt(entry):
    """A message typed by the user, as opposed to a tool result or injected context"""
    if entry.get("type") != "user" or entry.get("isMeta"):
        return False
    content = entry.get("message", {}).get("content")
    if isinstance(content, str):
        return True
    return isinstance(content, list) and not any(c.get("type") == "tool_result" for c in content)


def _asks_question(text):
    lines = [l.strip().rstrip("*_)` ") for l in text.strip().splitlines() if l.strip()]
    return any(l.endswith("?") for l in lines[-3:])


def read_transcript(path):
    """What the last turn left behind: final reply text, an unanswered tool call, and whether it pushed"""
    result = {"last_text": "", "open_tool": None, "pushed": False}
    newest = True
    for entry in _tail_entries(path):
        kind = entry.get("type")
        if kind not in ("user", "assistant") or entry.get("isMeta"):
            continue
        if _is_prompt(entry):
            break
        if kind == "assistant":
            for block in reversed(entry.get("message", {}).get("content") or []):
                if block.get("type") == "text" and not result["last_text"]:
                    result["last_text"] = block.get("text", "")
                elif block.get("type") == "tool_use":
                    # A tool call with nothing after it: waiting on a permission prompt or AskUserQuestion
                    if newest and not result["open_tool"]:
                        result["open_tool"] = block.get("name")
                    if "git push" in str((block.get("input") or {}).get("command", "")):
                        result["pushed"] = True
        newest = False
    return result


def classify(status, idle_secs, transcript):
    if status == "busy":
        return "working"
    if transcript["pushed"]:
        return "wrapped"
    if idle_secs > STALE_HOURS * 3600:
        return "stale"
    if transcript["open_tool"] or _asks_question(transcript["last_text"]):
        return "needs_answer"
    return "current" if idle_secs < CURRENT_MINS * 60 else "ready_to_wrap"


def project_of(cwd):
    if cwd == TREE_ROOT:
        return "claude-sessions"
    if cwd.startswith(TREE_ROOT + "/"):
        return cwd[len(TREE_ROOT) + 1:]
    return os.path.basename(cwd) or cwd


def age(secs):
    if secs < 3600:
        return f"{max(1, int(secs // 60))}m"
    if secs < 86400:
        return f"{int(secs // 3600)}h"
    return f"{int(secs // 86400)}d"


def threads():
    """Every live interactive Claude thread, keyed by tty"""
    ttys = _ttys()
    now = time.time()
    found = {}
    for f in SESSIONS_DIR.glob("*.json"):
        if not f.stem.isdigit():
            continue
        try:
            info = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        pid = info.get("pid")
        if info.get("kind") != "interactive" or not pid or not _alive(pid) or pid not in ttys:
            continue
        transcripts = list(PROJECTS_DIR.glob(f"*/{info['sessionId']}.jsonl"))
        transcript = read_transcript(transcripts[0]) if transcripts else {"last_text": "", "open_tool": None, "pushed": False}
        idle_secs = now - info.get("statusUpdatedAt", info.get("updatedAt", now * 1000)) / 1000
        state = classify(info.get("status"), idle_secs, transcript)
        found[ttys[pid]] = {
            "pid": pid,
            "session_id": info["sessionId"],
            "project": project_of(info.get("cwd", "")),
            "state": state,
            "idle_secs": idle_secs,
            "asked": bool(transcript["open_tool"]) or _asks_question(transcript["last_text"]),
            "last_text": transcript["last_text"],
            "open_tool": transcript["open_tool"],
        }
    return found


def clean_title(name):
    """Drop Claude's status glyph and iTerm's '(job)' suffix from a session name"""
    name = re.sub(r"\s*\([^)]*\)$", "", name.strip())
    return re.sub(r"^[^\w\s]\s+", "", name)


if __name__ == "__main__":
    for tty, t in sorted(threads().items(), key=lambda kv: kv[1]["idle_secs"]):
        print(f"{t['state']:14} {age(t['idle_secs']):>4}  {tty:8} {t['project']:22} {t['last_text'][-70:]!r}")
