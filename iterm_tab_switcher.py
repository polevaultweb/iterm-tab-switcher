#!/usr/bin/env python3
"""
iTerm2 Tab Switcher - Menu bar app for quick tab navigation

Claude Code threads are listed first, grouped by what they need from you (see claude_threads.py);
other tabs follow, grouped by window. The menu bar title shows how many threads need an answer.

A background thread collects tabs and thread states every REFRESH_SECS, so opening the menu only
builds it from the latest snapshot. Each open also triggers a fresh collection for the next one.
"""

import os
import rumps
import subprocess
import threading
from Foundation import NSObject
import objc

import claude_threads

DEFAULT_ICON = "🖥️"
REFRESH_SECS = 5


def resolve_icon():
    """(image path, text) for the menu bar. TAB_SWITCHER_ICON is text such as an emoji, or a path to an image."""
    setting = os.environ.get("TAB_SWITCHER_ICON", "").strip() or DEFAULT_ICON
    path = os.path.expanduser(setting)
    if os.path.isfile(path):
        return path, ""
    if "/" in setting or setting.lower().endswith((".png", ".pdf", ".tiff", ".icns")):
        print(f"Icon {path} not found; using {DEFAULT_ICON}")
        return None, DEFAULT_ICON
    return None, setting


ICON_IMAGE, ICON = resolve_icon()
# One-colour images look right in light and dark menu bars when macOS tints them; set 0 for a colour image
ICON_TEMPLATE = os.environ.get("TAB_SWITCHER_ICON_TEMPLATE", "1") != "0"


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
        super().__init__("iTerm Tab Switcher", title=ICON or None, icon=ICON_IMAGE,
                         template=ICON_TEMPLATE if ICON_IMAGE else None, quit_button=None)
        # (tabs, threads, recent), replaced whole by the collector thread and only read on the main thread
        self.snapshot = ([], {}, [])
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
        try:
            recent = claude_threads.recent_closed()
        except Exception as e:
            print(f"Error reading recent threads: {e}")
            recent = []
        self.snapshot = (tabs, threads, recent)

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

    def reopen_thread(self, command):
        """Run a resume command in a new tab of the front iTerm window, or a new window if there is none"""
        command = command.replace("\\", "\\\\").replace('"', '\\"')
        script = f'''
        tell application "iTerm2"
            activate
            if (count of windows) is 0 then
                create window with default profile
            else
                tell current window to create tab with default profile
            end if
            tell current session of current window to write text "{command}"
        end tell
        '''
        try:
            subprocess.run(["osascript", "-e", script], timeout=5)
        except Exception as e:
            print(f"Error reopening thread: {e}")
        self.wake.set()

    def update_title(self, _):
        waiting = sum(t["state"] == "needs_answer" for t in self.snapshot[1].values())
        # An image icon leaves ICON empty, so the count sits beside the image
        title = " ".join(filter(None, [ICON, f"❓{waiting}" if waiting else ""])) or None
        if self.title != title:
            self.title = title

    def _add(self, title, callback=None, session_id=None, tooltip=None, parent=None):
        parent = self.menu if parent is None else parent
        # rumps keys menu items by title, so pad duplicates with zero-width spaces
        while title in parent:
            title += "​"
        item = rumps.MenuItem(title)
        if callback:
            item.session_id = session_id
            item.set_callback(callback)
        if tooltip:
            item._menuitem.setToolTip_(tooltip)
        parent.add(item)
        return item

    def build_menu(self):
        """Rebuild the menu from the latest snapshot"""
        self.menu.clear()

        tabs, threads, recent = self.snapshot

        if not tabs:
            self._add("No tabs found")
            self.menu.add(None)  # separator
            self._add_recent(recent)
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
                    waiting = f"  · {t['waiting_for']}" if t["waiting_for"] else ""
                    self._add(
                        f"    {t['project']} · {title[:45]}{when}{waiting}{asked}",
                        callback=self.on_tab_click,
                        session_id=tab["id"],
                        tooltip=t["last_text"].strip()[-600:] or None
                    )
                self.menu.add(None)  # separator

            self._add_recent(recent)

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

    def _add_recent(self, recent):
        """Threads closed recently, newest first, in a submenu; clicking one resumes it in a new tab"""
        if not recent:
            return
        submenu = self._add(f"🕘 Recently closed ({len(recent)})")
        for r in recent:
            done = " ✅" if r["pushed"] else ""
            self._add(
                f"{r['project']} · {r['title'][:45]}  · {claude_threads.age(r['idle_secs'])}{done}",
                callback=self.on_recent_click,
                session_id=r["command"],
                tooltip=r["command"],
                parent=submenu
            )
        self.menu.add(None)  # separator

    def on_recent_click(self, sender):
        self.reopen_thread(sender.session_id)

    def on_tab_click(self, sender):
        """Handle tab menu item click"""
        self.switch_to_tab(sender.session_id)


if __name__ == "__main__":
    ITermTabSwitcher().run()
