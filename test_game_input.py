"""
Find out exactly where the translator loses to a game.

"It does not work in my game" has at least four separate causes, and they need
different fixes:

  1. The keystrokes never arrive at all (scan code, or Windows refusing them).
  2. They arrive, but the text box does not implement Ctrl+A or Ctrl+C, so
     there is nothing to translate.
  3. They arrive, but the box does not implement Ctrl+V, so the translation
     cannot be put back.
  4. An anti-cheat is discarding injected input.

This walks through each one against whatever window you point it at and says
which of them is happening.

    python test_game_input.py

Run it, then click into the game's chat box before the countdown ends. It types
into that box on purpose - use a chat box, a search field, anything you do not
mind having text typed into. It sends nothing to the network and reads nothing
but the clipboard.
"""
import functools
import sys
import time

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

print = functools.partial(print, flush=True)  # noqa: A001

import win_input
from hotkey_manager import (VK_A, VK_C, VK_CONTROL, VK_V, safe_clipboard_copy,
                            safe_clipboard_paste, wait_for_clipboard_change)

PROBE = "TypistProbe123"
COUNTDOWN = 6


def countdown(seconds, message):
    print(f"\n{message}")
    for remaining in range(seconds, 0, -1):
        pid, name = win_input.foreground_process()
        print(f"  {remaining}...  (focus is on {name or 'unknown'})", end="\r")
        time.sleep(1)
    print(" " * 60, end="\r")


def step(number, label):
    print(f"\n[{number}] {label}")


def main():
    print("=" * 68)
    print("  TYPIST TRANSLATOR - game input diagnostic")
    print("=" * 68)
    print(__doc__.split("    python")[0].strip().split("\n\n", 1)[1])

    countdown(COUNTDOWN, "Click into the text box you want to test. Starting in:")

    pid, name = win_input.foreground_process()
    print(f"Target: {name or 'unknown'}  (pid {pid})")
    if not pid:
        print("\nNo foreground window. Nothing to test against.")
        return 1

    results = {}

    # ---------------------------------------------------------------
    step(1, "Can this app send keystrokes to that window at all?")
    try:
        win_input.type_text(PROBE)
        time.sleep(0.35)
        results["send"] = True
        print("     Windows accepted the keystrokes.")
        print(f"     LOOK AT THE BOX: does it now contain '{PROBE}'?")
    except win_input.InputBlocked as exc:
        results["send"] = False
        print(f"     REFUSED: {exc}")
        print("\n  Nothing else can work until this does. If that program runs")
        print("  as administrator, this app has to as well.")
        return 1

    typed = input("     Did the text appear? [y/N] ").strip().lower().startswith("y")
    results["typed"] = typed
    if typed:
        print("     -> Typing works. 'Type instead of paste' mode will work here.")
    else:
        print("     -> Typing does NOT reach this window.")
        print("        Either the box was not focused, or something is")
        print("        discarding injected input - anti-cheat usually.")

    # ---------------------------------------------------------------
    step(2, "Does the box support Ctrl+A and Ctrl+C? (reading the text)")
    sentinel = f"__TYPIST_SENTINEL_{time.time()}__"
    safe_clipboard_copy(sentinel)
    time.sleep(0.05)
    win_input.press_and_release(VK_A, VK_CONTROL, delay=0.04)
    time.sleep(0.05)
    win_input.press_and_release(VK_C, VK_CONTROL, delay=0.04)
    captured = wait_for_clipboard_change(sentinel, timeout=0.6)

    if captured and captured != sentinel:
        results["read"] = True
        print(f"     Read back {len(captured)} characters: {captured[:60]!r}")
        print("     -> Ctrl+A and Ctrl+C work. Normal translation can read this box.")
    else:
        results["read"] = False
        print("     Nothing was copied - the clipboard still holds the sentinel.")
        print("     -> This box does NOT implement Ctrl+A/Ctrl+C.")
        print("        The app cannot read what you typed here, so translating")
        print("        in place is impossible no matter what else is fixed.")

    # ---------------------------------------------------------------
    step(3, "Does the box support Ctrl+V? (writing the translation back)")
    marker = "TypistPasteOK"
    safe_clipboard_copy(marker)
    time.sleep(0.05)
    win_input.press_and_release(VK_V, VK_CONTROL, delay=0.04)
    time.sleep(0.35)
    print(f"     LOOK AT THE BOX: does it now contain '{marker}'?")
    pasted = input("     Did it paste? [y/N] ").strip().lower().startswith("y")
    results["paste"] = pasted
    print("     -> Ctrl+V works." if pasted else
          "     -> Ctrl+V does NOT work here; the app must type instead.")

    # ---------------------------------------------------------------
    print("\n" + "=" * 68)
    print("  RESULT")
    print("=" * 68)
    print(f"  Target application     {name or 'unknown'}")
    print(f"  Keystrokes accepted    {'yes' if results.get('send') else 'NO'}")
    print(f"  Characters arrive      {'yes' if results.get('typed') else 'NO'}")
    print(f"  Ctrl+A / Ctrl+C read   {'yes' if results.get('read') else 'NO'}")
    print(f"  Ctrl+V paste           {'yes' if results.get('paste') else 'NO'}")
    print()

    if results.get("read") and results.get("paste"):
        print("  This window is fully supported. Translation should work as-is.")
    elif results.get("read") and results.get("typed"):
        print("  Reading works, pasting does not.")
        print("  FIX: Settings -> set 'How the translation is written back' to")
        print("       'Type the characters'.")
    elif results.get("typed"):
        print("  This app can write into that box but cannot read out of it.")
        print("  Translating text already typed there is not possible - the")
        print("  box gives nothing back. What would work is typing somewhere")
        print("  else and having the translation typed in.")
    else:
        print("  Nothing reaches this window. Either it runs with higher")
        print("  privileges than this app, or an anti-cheat is discarding")
        print("  injected input. Neither can be worked around from user mode,")
        print("  and trying to would be exactly what anti-cheat exists to stop.")

    print()
    print("  Please include this table when reporting a game that does not work:")
    print(f"  {name}: send={results.get('send')} typed={results.get('typed')} "
          f"read={results.get('read')} paste={results.get('paste')}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(1)
