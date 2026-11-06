"""
Live Claude Code threads and what each one needs from you.

Claude Code writes ~/.claude/sessions/<pid>.json for every running thread (status busy or idle)
and a transcript at ~/.claude/projects/<dir>/<session id>.jsonl. The state comes from the two:

  needs_answer  Claude Code reports status "waiting" (a permission prompt or question dialog, at any age), or
                idle under STALE_HOURS and the reply ends by asking (a "?" or "let me know"-style line in its
                closing paragraph, outside code and quotes) or leaves a tool call unanswered
  working       busy
  current       idle under CURRENT_MINS, nothing asked
  ready_to_wrap idle CURRENT_MINS to STALE_HOURS, nothing asked
  stale         idle over STALE_HOURS
  wrapped       the last turn ran git push (wrap-up commits and pushes) and asked nothing, so the tab can close

recent_closed() lists the newest threads that aren't running, for reopening. Two optional settings:

  CLAUDE_THREADS_ROOT  only list threads started under this directory, and name projects relative to it
  CLAUDE_RESUME_CMD    command typed into the new tab; {id}, {cwd}, {rel} (cwd relative to the root, or
                       "." at the root) and {model} (opus, sonnet...) are filled in, shell-quoted.
                       Default: cd {cwd} && claude --resume {id}

Run directly to print the table: python3 claude_threads.py
"""

import json
import os
import re
import shlex
import subprocess
import time
from pathlib import Path

CURRENT_MINS = 30
STALE_HOURS = 8

SESSIONS_DIR = Path.home() / ".claude" / "sessions"
PROJECTS_DIR = Path.home() / ".claude" / "projects"
TREE_ROOT = os.path.expanduser(os.environ.get("CLAUDE_THREADS_ROOT", "")).rstrip("/")
RESUME_CMD = os.environ.get("CLAUDE_RESUME_CMD", "cd {cwd} && claude --resume {id}")
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


# Endings that ask without a question mark: "Say the word and I'll push it", "Let me know which"
ASK_PHRASES = re.compile(
    r"\b(let me know|say the word|tell me (if|whether|which|what|how)|want me to|shall i|should i|would you like)\b",
    re.IGNORECASE,
)
_FENCED = re.compile(r"^```.*?^```[^\n]*$", re.MULTILINE | re.DOTALL)
_LIST_ITEM = re.compile(r"^\s*([-*+]|\d+[.)])\s")
# "Thanks,\nIain": the reply ends with a drafted message, so its questions are for someone else
_SIGN_OFF = re.compile(r"^(thanks|thank you|many thanks|cheers|best|regards|kind regards|best regards)\b[,.!]?$", re.IGNORECASE)


def _closing_lines(text):
    """The lines a reply ends on: its last two paragraphs, plus one more when the last is a list of options.
    Code blocks, quoted text and drafts ending in a sign-off are left out, so a drafted email or snippet
    ending in '?' doesn't count."""
    text = _FENCED.sub("", text)
    paragraphs = []
    for block in re.split(r"\n\s*\n", text):
        lines = [l.strip() for l in block.splitlines() if l.strip() and not l.lstrip().startswith(">")]
        if lines:
            paragraphs.append(lines)
    if not paragraphs or _SIGN_OFF.match(paragraphs[-1][0]):
        return []
    # A question often comes just before a closing note ("Want me to change it?" then a reminder)
    take = 3 if all(_LIST_ITEM.match(l) for l in paragraphs[-1]) else 2
    return [l for p in paragraphs[-take:] for l in p]


def _asks_question(text):
    for line in _closing_lines(text):
        if line.rstrip("*_)` ").endswith("?") or ASK_PHRASES.search(line):
            return True
    return False


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


def classify(status, idle_secs, asked, pushed):
    # Claude Code's own signal: a permission prompt or question dialog is on screen. Never ages out
    if status == "waiting":
        return "needs_answer"
    if status == "busy":
        return "working"
    stale = idle_secs > STALE_HOURS * 3600
    # A question asked after a push (wrap-up asking about Todoist, say) still needs an answer
    if asked:
        return "stale" if stale else "needs_answer"
    if pushed:
        return "wrapped"
    if stale:
        return "stale"
    return "current" if idle_secs < CURRENT_MINS * 60 else "ready_to_wrap"


def _in_tree(cwd):
    return not TREE_ROOT or cwd == TREE_ROOT or cwd.startswith(TREE_ROOT + "/")


def project_of(cwd):
    if TREE_ROOT and cwd == TREE_ROOT:
        return os.path.basename(TREE_ROOT)
    if TREE_ROOT and cwd.startswith(TREE_ROOT + "/"):
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
        asked = bool(transcript["open_tool"]) or _asks_question(transcript["last_text"])
        status = info.get("status")
        state = classify(status, idle_secs, asked, transcript["pushed"])
        found[ttys[pid]] = {
            "pid": pid,
            "session_id": info["sessionId"],
            "project": project_of(info.get("cwd", "")),
            "state": state,
            "idle_secs": idle_secs,
            "asked": asked or status == "waiting",
            # What Claude Code says it's waiting for, e.g. "input needed"; empty unless status is waiting
            "waiting_for": (info.get("waitingFor") or "input needed") if status == "waiting" else "",
            "last_text": transcript["last_text"],
            "open_tool": transcript["open_tool"],
        }
    return found


RECENT_LIMIT = 10
# Transcript folders for threads started in the tree: Claude Code names them after the cwd, / and . → -
TREE_PREFIX = re.sub(r"[/.]", "-", TREE_ROOT)  # empty without a root, so every folder matches
_TITLE_RE = re.compile(rb'"(?:customTitle|aiTitle)":"((?:[^"\\]|\\.)*)"')
_MODEL_RE = re.compile(rb'"model":"claude-([a-z]+)')
# path → (mtime, details); transcripts only change while their thread runs, so closed ones parse once
_recent_cache = {}


def _running_ids():
    """Session ids of every live Claude process: its status file, plus --resume/--session-id on command lines"""
    ids = set()
    for f in SESSIONS_DIR.glob("*.json"):
        try:
            info = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if info.get("pid") and _alive(info["pid"]) and info.get("sessionId"):
            ids.add(info["sessionId"])
    out = subprocess.run(["ps", "-axo", "command="], capture_output=True, text=True).stdout
    ids.update(re.findall(r"--(?:resume|session-id)[ =]([0-9a-f-]{36})", out))
    return ids


def _first_prompt(path):
    """The first message typed in a thread, for threads Claude never titled"""
    with open(path, "rb") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            content = entry.get("message", {}).get("content") if entry.get("type") == "user" else None
            if isinstance(content, str) and not entry.get("isMeta") and not content.startswith("<"):
                return " ".join(content.split())
    return ""


def _recent_details(path, mtime):
    cached = _recent_cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    data = path.read_bytes()
    cwd = re.search(rb'"cwd":"([^"]*)"', data)
    titles = _TITLE_RE.findall(data)
    models = _MODEL_RE.findall(data)
    title = json.loads(b'"' + titles[-1] + b'"') if titles else _first_prompt(path)
    details = {
        "cwd": cwd.group(1).decode() if cwd else "",
        "title": title,
        "model": models[-1].decode() if models else "",
        "pushed": read_transcript(path)["pushed"],
    }
    _recent_cache[path] = (mtime, details)
    return details


def recent_closed(limit=RECENT_LIMIT):
    """The newest threads (under CLAUDE_THREADS_ROOT, if set) that aren't running, newest first"""
    running = _running_ids()
    now = time.time()
    files = []
    for path in PROJECTS_DIR.glob(f"{TREE_PREFIX}*/*.jsonl"):
        try:
            files.append((path.stat().st_mtime, path))
        except OSError:
            pass
    found = []
    for mtime, path in sorted(files, reverse=True):
        if len(found) >= limit:
            break
        if path.stem in running:
            continue
        try:
            d = _recent_details(path, mtime)
        except OSError:
            continue
        cwd = d["cwd"]
        if not d["title"] or not cwd or not _in_tree(cwd):
            continue
        rel = os.path.relpath(cwd, TREE_ROOT) if TREE_ROOT else cwd
        fields = {"id": path.stem, "cwd": cwd, "rel": rel, "model": d["model"]}
        found.append({
            "session_id": path.stem,
            "project": project_of(cwd),
            "command": RESUME_CMD.format(**{k: shlex.quote(v) for k, v in fields.items()}),
            "title": d["title"],
            "idle_secs": now - mtime,
            "pushed": d["pushed"],
        })
    return found


def clean_title(name):
    """Drop Claude's status glyph and iTerm's '(job)' suffix from a session name"""
    name = re.sub(r"\s*\([^)]*\)$", "", name.strip())
    return re.sub(r"^[^\w\s]\s+", "", name)


if __name__ == "__main__":
    for tty, t in sorted(threads().items(), key=lambda kv: kv[1]["idle_secs"]):
        print(f"{t['state']:14} {age(t['idle_secs']):>4}  {tty:8} {t['project']:22} {t['last_text'][-70:]!r}")
    print("\nRecently closed")
    for r in recent_closed():
        print(f"{'✅' if r['pushed'] else '  '} {age(r['idle_secs']):>4}  {r['project']:22} {r['title'][:50]:50}  {r['command']}")
