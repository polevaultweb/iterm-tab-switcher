#!/usr/bin/env python3
"""
iTerm2 Tab Switcher - Menu bar app for quick tab navigation
"""

import rumps
import subprocess
from Foundation import NSObject
from AppKit import NSMenu
import objc


class MenuDelegate(NSObject):
    """Delegate to refresh tabs when menu opens"""

    def initWithApp_(self, app):
        self = objc.super(MenuDelegate, self).init()
        if self is None:
            return None
        self.app = app
        return self

    def menuWillOpen_(self, menu):
        """Called when menu is about to open"""
        self.app.refresh_tabs(None)


class ITermTabSwitcher(rumps.App):
    def __init__(self):
        super().__init__("🖥️", quit_button=None)
        self.refresh_tabs(None)
        # Set up delegate to refresh on menu open
        self._menu_delegate = MenuDelegate.alloc().initWithApp_(self)
        self._nsapp_menu = self._menu._menu
        self._nsapp_menu.setDelegate_(self._menu_delegate)

    def get_tabs(self):
        """Get all iTerm2 tabs via AppleScript"""
        script = '''
        tell application "iTerm2"
            set output to ""
            set winIndex to 0
            repeat with w in windows
                set winIndex to winIndex + 1
                set tabIndex to 0
                repeat with t in tabs of w
                    set tabIndex to tabIndex + 1
                    tell current session of t
                        set tabTitle to variable named "tab.title"
                        set sessionName to name
                    end tell
                    if tabTitle is not equal to sessionName and tabTitle is not equal to "" then
                        set displayName to tabTitle & " - " & sessionName
                    else
                        set displayName to sessionName
                    end if
                    set output to output & winIndex & "," & tabIndex & "," & displayName & linefeed
                end repeat
            end repeat
            return output
        end tell
        '''
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=5
            )
            tabs = []
            for line in result.stdout.strip().split("\n"):
                if line:
                    parts = line.split(",", 2)
                    if len(parts) >= 3:
                        tabs.append({
                            "window": int(parts[0]),
                            "tab": int(parts[1]),
                            "name": parts[2]
                        })
            return tabs
        except Exception as e:
            print(f"Error getting tabs: {e}")
            return []

    def switch_to_tab(self, window_index, tab_index):
        """Switch to a specific tab via AppleScript"""
        script = f'''
        tell application "iTerm2"
            activate
            set w to window {window_index}
            set t to tab {tab_index} of w
            select t
        end tell
        '''
        try:
            subprocess.run(["osascript", "-e", script], timeout=5)
        except Exception as e:
            print(f"Error switching tab: {e}")

    def refresh_tabs(self, _):
        """Refresh the tab list"""
        self.menu.clear()

        tabs = self.get_tabs()

        if not tabs:
            self.menu.add(rumps.MenuItem("No tabs found", callback=None))
        else:
            current_window = None
            for tab in tabs:
                # Add window separator if new window
                if current_window != tab["window"]:
                    if current_window is not None:
                        self.menu.add(None)  # separator
                    current_window = tab["window"]
                    header = rumps.MenuItem(f"── Window {tab['window']} ──")
                    header.set_callback(None)
                    self.menu.add(header)

                # Create menu item for tab
                item = rumps.MenuItem(
                    f"  {tab['tab']}: {tab['name'][:40]}"
                )
                # Store tab info for callback
                item.window_index = tab["window"]
                item.tab_index = tab["tab"]
                item.set_callback(self.on_tab_click)
                self.menu.add(item)

        self.menu.add(None)  # separator
        self.menu.add(rumps.MenuItem("Quit", callback=rumps.quit_application))

    def on_tab_click(self, sender):
        """Handle tab menu item click"""
        self.switch_to_tab(sender.window_index, sender.tab_index)


if __name__ == "__main__":
    ITermTabSwitcher().run()
