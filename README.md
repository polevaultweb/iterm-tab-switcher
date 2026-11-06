# iTerm Tab Switcher

A macOS menu bar app for quick navigation between iTerm2 tabs.

## Features

- Shows all open iTerm2 tabs in a menu bar dropdown
- Tabs grouped by window
- Click to switch to any tab instantly
- Opens instantly: a background thread refreshes the tab list every 5 seconds (`REFRESH_SECS`), and each open triggers another refresh
- Claude Code threads listed first, grouped by what they need from you; the menu bar shows `❓N` when N threads need an answer
- Recently closed Claude Code threads (the newest 10 that aren't running) in a submenu, with a click to resume one in a new tab

## Claude Code thread states

`claude_threads.py` combines Claude Code's live status file (`~/.claude/sessions/<pid>.json`, busy or idle) with the tail of each thread's transcript, and matches threads to tabs by tty. No hooks needed.

| State | Rule |
|-------|------|
| ❓ Needs answer | Claude Code reports `status: "waiting"` (a permission prompt or question dialog; never ages out, and the row shows what it's waiting for). Or idle under 8 hours, and the reply ends by asking: a `?` or a "let me know", "say the word", "want me to" style line in its last two paragraphs, ignoring code blocks, quotes and drafts that end in a sign-off. Or a tool call has no result yet |
| ⏳ Working | Busy |
| 💬 Current | Idle under 30 minutes, nothing asked |
| 🎁 Ready to wrap | Idle 30 minutes to 8 hours, nothing asked |
| ✅ Wrapped, close tab | The last turn ran `git push`, which wrap-up does, and asked nothing |
| 💤 Stale | Idle over 8 hours (a `❓` marks an old unanswered question) |

Hover over a thread to see the end of Claude's last reply. Thresholds are `CURRENT_MINS` and `STALE_HOURS` in `claude_threads.py`. `python3 claude_threads.py` prints the same table in the terminal.

## Recently closed threads

The 🕘 Recently closed submenu lists the newest Claude Code transcripts in `~/.claude/projects` whose thread isn't running (no live `~/.claude/sessions/<pid>.json`, and no `--resume` or `--session-id` for it on a running command line). ✅ marks a thread whose last turn ran `git push`. Clicking a row opens a new iTerm tab and resumes the thread. The limit is `RECENT_LIMIT` in `claude_threads.py`.

Two optional environment variables change what's listed and what runs:

| Variable | Effect | Default |
|----------|--------|---------|
| `CLAUDE_THREADS_ROOT` | Only list threads started under this directory; project names are shown relative to it | all threads |
| `CLAUDE_RESUME_CMD` | Command typed into the new tab. `{id}`, `{cwd}`, `{rel}` (cwd relative to the root) and `{model}` are filled in, shell-quoted | `cd {cwd} && claude --resume {id}` |

For a launch agent, set them under `EnvironmentVariables` in the plist.

## Menu bar icon

The icon is 🖥️ unless `TAB_SWITCHER_ICON` says otherwise. Set it to other text, such as an emoji, or to the path of an image (PNG, PDF or TIFF; drawn at 20 points, so a 40 or 48 pixel image stays sharp on Retina). Images are treated as one-colour templates that macOS tints to match the menu bar; set `TAB_SWITCHER_ICON_TEMPLATE=0` for a colour image. The `❓N` count appears beside whichever icon you use.

## Requirements

- macOS
- iTerm2
- Python 3.8+

## Installation

1. Install the required dependency:

```bash
pip3 install rumps
```

2. Run the app:

```bash
python3 iterm_tab_switcher.py
```

## Usage

1. Look for the **🖥️** icon (or your own, see Menu bar icon) in your macOS menu bar
2. Click to see all open iTerm2 tabs
3. Click any tab name to switch to it
4. Use "Quit" to close the app

## Run on Startup

To run automatically on login, create a launch agent:

```bash
mkdir -p ~/Library/LaunchAgents
cat > ~/Library/LaunchAgents/com.iterm-tab-switcher.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.iterm-tab-switcher</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/path/to/iterm_tab_switcher.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
EOF
```

Update the path to `iterm_tab_switcher.py` and load it:

```bash
launchctl load ~/Library/LaunchAgents/com.iterm-tab-switcher.plist
```

## License

MIT
