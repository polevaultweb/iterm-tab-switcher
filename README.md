# iTerm Tab Switcher

A macOS menu bar app for quick navigation between iTerm2 tabs.

## Features

- Shows all open iTerm2 tabs in a menu bar dropdown
- Tabs grouped by window
- Click to switch to any tab instantly
- Opens instantly: a background thread refreshes the tab list every 5 seconds (`REFRESH_SECS`), and each open triggers another refresh
- Claude Code threads listed first, grouped by what they need from you; the menu bar shows `❓N` when N threads need an answer

## Claude Code thread states

`claude_threads.py` combines Claude Code's live status file (`~/.claude/sessions/<pid>.json`, busy or idle) with the tail of each thread's transcript, and matches threads to tabs by tty. No hooks needed.

| State | Rule |
|-------|------|
| ❓ Needs answer | Idle, and the last reply ends with a question, or a tool call (AskUserQuestion, a permission prompt) has no result yet |
| ⏳ Working | Busy |
| 💬 Current | Idle under 30 minutes, nothing asked |
| 🎁 Ready to wrap | Idle 30 minutes to 8 hours, nothing asked |
| ✅ Wrapped, close tab | The last turn ran `git push`, which wrap-up does |
| 💤 Stale | Idle over 8 hours (a `❓` marks an old unanswered question) |

Hover over a thread to see the end of Claude's last reply. Thresholds are `CURRENT_MINS` and `STALE_HOURS` in `claude_threads.py`. `python3 claude_threads.py` prints the same table in the terminal.

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

1. Look for the **🖥️** icon in your macOS menu bar
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
