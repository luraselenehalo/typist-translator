"""
System Tray Manager Module
Handles Windows System Tray (Taskbar Notification Area) icon, menu, and background daemon.
"""
import os
import threading
from PIL import Image, ImageDraw, ImageFont
import pystray

from i18n import t


def create_default_icon_image():
    """Generate a crisp, stylish icon image using Pillow."""
    size = (64, 64)
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    
    # Modern rounded square with gradient look
    draw.rounded_rectangle([(3, 3), (61, 61)], radius=14, fill="#1f6aa5", outline="#4da6ff", width=2)
    
    # Stylized "A / 文" or "T" for translation
    # Draw a bold letter 'T' in white
    # Top bar
    draw.rounded_rectangle([(18, 16), (46, 24)], radius=3, fill="#ffffff")
    # Vertical bar
    draw.rounded_rectangle([(28, 24), (36, 48)], radius=3, fill="#ffffff")
    # Little accent dot
    draw.ellipse([(44, 42), (50, 48)], fill="#66d9ef")
    
    return image


class TrayManager:
    def __init__(self, on_show_window=None, on_toggle_service=None, on_quit=None):
        self.on_show_window = on_show_window
        self.on_toggle_service = on_toggle_service
        self.on_quit = on_quit
        
        self.service_active = True
        self.tray_icon = None
        self._thread = None

    def _get_icon_image(self):
        """Load the tray icon, preferring the cut-out version.

        icon_alpha.png has the dark backdrop removed, so the tray icon does not
        show a dark block on a light taskbar. icon.png is the original artwork
        and is only a fallback.
        """
        base = os.path.dirname(os.path.abspath(__file__))
        for name in ("icon_alpha.png", "icon.png"):
            path = os.path.join(base, name)
            if not os.path.exists(path):
                continue
            try:
                image = Image.open(path)
                # The source art is ~1 MB at full resolution; the tray renders
                # it at 16-32 px, so downsample instead of holding the original.
                image.thumbnail((64, 64), Image.LANCZOS)
                return image.convert("RGBA")
            except Exception:
                continue
        # Never write over the user's artwork - just draw something usable.
        return create_default_icon_image()

    def _create_menu(self):
        # Labels are callables so pystray re-reads them when the menu is
        # refreshed, which is how the tray follows an interface language change.
        return pystray.Menu(
            pystray.MenuItem(
                lambda item: t("tray.open"),
                self._handle_show_window,
                default=True
            ),
            pystray.MenuItem(
                lambda item: t("tray.enabled"),
                self._handle_toggle_service,
                checked=lambda item: self.service_active
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda item: t("tray.exit"),
                self._handle_quit
            )
        )

    def refresh_labels(self):
        """Re-read the menu and tooltip after the interface language changes."""
        if not self.tray_icon:
            return
        try:
            self.tray_icon.title = t("tray.tooltip")
            self.tray_icon.update_menu()
        except Exception:
            pass

    def _handle_show_window(self, icon=None, item=None):
        if self.on_show_window:
            self.on_show_window()

    def _handle_toggle_service(self, icon=None, item=None):
        self.service_active = not self.service_active
        if self.on_toggle_service:
            self.on_toggle_service(self.service_active)

    def _handle_quit(self, icon=None, item=None):
        self.stop()
        if self.on_quit:
            self.on_quit()

    def set_service_active(self, active: bool):
        self.service_active = active
        if self.tray_icon:
            self.tray_icon.update_menu()

    def start(self):
        """Start system tray in a separate background thread."""
        image = self._get_icon_image()
        menu = self._create_menu()
        self.tray_icon = pystray.Icon(
            "TypistTranslator",
            image,
            t("tray.tooltip"),
            menu
        )
        self._thread = threading.Thread(target=self.tray_icon.run, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop system tray icon."""
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
            self.tray_icon = None
