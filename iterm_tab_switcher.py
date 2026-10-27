#!/usr/bin/env python3
"""
iTerm2 Tab Switcher - Menu bar app for quick tab navigation

Claude Code threads are listed first, grouped by what they need from you (see claude_threads.py);
other tabs follow, grouped by window. The menu bar title shows how many threads need an answer.

A background thread collects tabs and thread states every REFRESH_SECS, so opening the menu only
builds it from the latest snapshot. Each open also triggers a fresh collection for the next one.
"""

import rumps
import subprocess
import threading
from Foundation import NSObject
import objc

import claude_threads

ICON = "🖥️"
REFRESH_SECS = 5


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
        self.app.build_menu()
        self.app.wake.set()


class ITermTabSwitcher(rumps.App):
    def __init__(self):
        super().__init__(ICON, quit_button=None)
        # (tabs, threads), replaced whole by the collector thread and only read on the main thread
        self.snapshot = ([], {})
        self.wake = threading.Event()
        self.collect()
        self.build_menu()
        # Set up delegate to rebuild the menu when it opens
        self._menu_delegate = MenuDelegate.alloc().initWithApp_(self)
        self._nsapp_menu = self._menu._menu
        self._nsapp_menu.setDelegate_(self._menu_delegate)
        threading.Thread(target=self._collect_loop, daemon=True).start()
        # AppKit must be touched on the main thread, so a timer copies the count into the title
        self._timer = rumps.Timer(self.update_title, 1)
        self._timer.start()

    def _collect_loop(self):
        while True:
            self.wake.wait(REFRESH_SECS)
            self.wake.clear()
            self.collect()

    def collect(self):
        tabs = self.get_tabs()
        try:
            threads = claude_threads.threads()
        except Exception as e:
            print(f"Error reading Claude threads: {e}")
            threads = {}
        self.snapshot = (tabs, threads)

    def get_tabs(self):
        """Get all iTerm2 sessions via AppleScript"""
        # Bulk reads (one Apple event per property per window) keep this well under a second.
        # Checking iTerm is running first stops the background poll from relaunching it.
        script = '''
        set sep to ASCII character 9
        if application "iTerm2" is not running then return ""
        tell application "iTerm2"
            set output to ""
            set winIndex to 0
            repeat with w in windows
                set winIndex to winIndex + 1
                set ids to unique id of current session of every tab of w
                set ttys to tty of current session of every tab of w
                set names to name of current session of every tab of w
                repeat with i from 1 to count of ids
                    set output to output & winIndex & sep & i & sep & item i of ids & sep & item i of ttys & sep & item i of names & linefeed
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
                parts = line.split("\t", 4)
                if len(parts) == 5:
                    tabs.append({
                        "window": int(parts[0]),
                        "tab": int(parts[1]),
                        "id": parts[2],
                        "tty": parts[3].replace("/dev/", ""),
                        "name": parts[4]
                    })
            return tabs
        except Exception as e:
            print(f"Error getting tabs: {e}")
            return []

    def switch_to_tab(self, session_id):
        """Bring the window holding a session to the front and select its tab"""
        script = f'''
        tell application "iTerm2"
            repeat with w in windows
                repeat with t in tabs of w
                    repeat with s in sessions of t
                        if unique id of s is "{session_id}" then
                            select w
                            select t
                            select s
                            activate
                            return
                        end if
                    end repeat
                end repeat
            end repeat
        end tell
        '''
        try:
            subprocess.run(["osascript", "-e", script], timeout=5)
        except Exception as e:
            print(f"Error switching tab: {e}")

    def update_title(self, _):
        waiting = sum(t["state"] == "needs_answer" for t in self.snapshot[1].values())
        title = f"{ICON} ❓{waiting}" if waiting else ICON
        if self.title != title:
            self.title = title

    def _add(self, title, callback=None, session_id=None, tooltip=None):
        # rumps keys menu items by title, so pad duplicates with zero-width spaces
        while title in self.menu:
            title += "​"
        item = rumps.MenuItem(title)
        if callback:
            item.session_id = session_id
            item.set_callback(callback)
        if tooltip:
            item._menuitem.setToolTip_(tooltip)
        self.menu.add(item)

    def build_menu(self):
        """Rebuild the menu from the latest snapshot"""
        self.menu.clear()

        tabs, threads = self.snapshot

        if not tabs:
            self._add("No tabs found")
        else:
            claude_tabs = [(tab, threads[tab["tty"]]) for tab in tabs if tab["tty"] in threads]
            for state, label in claude_threads.STATES:
                rows = sorted(
                    [(tab, t) for tab, t in claude_tabs if t["state"] == state],
                    key=lambda row: row[1]["idle_secs"]
                )
                if not rows:
                    continue
                self._add(f"{label} ({len(rows)})")
                for tab, t in rows:
                    title = claude_threads.clean_title(tab["name"])
                    asked = " ❓" if t["asked"] and state != "needs_answer" else ""
                    when = "" if state == "working" else f"  · {claude_threads.age(t['idle_secs'])}"
                    self._add(
                        f"    {t['project']} · {title[:45]}{when}{asked}",
                        callback=self.on_tab_click,
                        session_id=tab["id"],
                        tooltip=t["last_text"].strip()[-600:] or None
                    )
                self.menu.add(None)  # separator

            other = [tab for tab in tabs if tab["tty"] not in threads]
            current_window = None
            for tab in other:
                # Add window header if new window
                if current_window != tab["window"]:
                    current_window = tab["window"]
                    self._add(f"── Window {tab['window']} ──")
                self._add(
                    f"  {tab['tab']}: {tab['name'][:40]}",
                    callback=self.on_tab_click,
                    session_id=tab["id"]
                )
            if other:
                self.menu.add(None)  # separator

        self.menu.add(rumps.MenuItem("Quit", callback=rumps.quit_application))

    def on_tab_click(self, sender):
        """Handle tab menu item click"""
        self.switch_to_tab(sender.session_id)


if __name__ == "__main__":
    ITermTabSwitcher().run()
