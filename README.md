# iTerm Tab Switcher

A macOS menu bar app for quick navigation between iTerm2 tabs.

## Features

- Shows all open iTerm2 tabs in a menu bar dropdown
- Tabs grouped by window
- Click to switch to any tab instantly
- Auto-refreshes when menu opens

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
2. Click to see all open iTerm2 tabs (list refreshes automatically)
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
