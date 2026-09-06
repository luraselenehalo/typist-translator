"""
Project identity - the one file to edit when the links change.

Everything here is read at start-up and handed to the front end with the rest
of the bootstrap payload, so editing this file is enough: no `build_ui.bat`,
no touching React. Restart the app and the About tab shows the new details.

An empty link is not an error. The About tab lists only the ones that are
filled in, and shows a short note pointing back here for the rest, so the page
never looks broken while a project is still finding its home.

    GITHUB_USER = "octocat"
    GITHUB_REPO = "typist-translator"
      -> https://github.com/octocat/typist-translator
         plus the Issues and Releases links, derived from it
"""

APP_NAME = "Typist Translator"
VERSION = "3.1.0"
AUTHOR = "Mrgunshi"
LICENSE = "MIT"
COPYRIGHT_YEAR = "2026"

# The same person under a different handle. Shown on the About tab so nobody
# has to wonder whether the GitHub account belongs to the author. Set to ""
# to leave the note out entirely.
ALIAS = "luraselenehalo"

# ---------------------------------------------------------------------
# Links. Leave a value as "" to hide that entry.
# ---------------------------------------------------------------------
GITHUB_USER = "luraselenehalo"
GITHUB_REPO = "typist-translator"   # rename here if the repo gets another name
FACEBOOK_URL = ""         # full URL, e.g. "https://facebook.com/yourpage"
CONTACT_EMAIL = ""        # e.g. "you@example.com"

# What the app is built on, shown on the About tab so anyone reading the repo
# can see the stack at a glance without opening requirements.txt.
BUILT_WITH = [
    ("Python", "3.13"),
    ("pywebview", "6.2"),
    ("WebView2", "Chromium"),
    ("React", "18.3"),
    ("Vite", "6.4"),
]


def github_url() -> str:
    """The repository URL, or the profile URL if no repo is named yet."""
    if not GITHUB_USER:
        return ""
    if not GITHUB_REPO:
        return f"https://github.com/{GITHUB_USER}"
    return f"https://github.com/{GITHUB_USER}/{GITHUB_REPO}"


def links() -> list:
    """Every link that is actually configured, in display order.

    Each entry is ``{"id", "url", "icon"}``; the label and description come
    from the interface-language catalogs, keyed by ``about.link.<id>``.
    """
    repo = github_url()
    entries = [
        ("github", repo, "🐙"),
        ("issues", f"{repo}/issues" if GITHUB_USER and GITHUB_REPO else "", "🐞"),
        ("releases", f"{repo}/releases" if GITHUB_USER and GITHUB_REPO else "", "📦"),
        ("facebook", FACEBOOK_URL, "📘"),
        ("email", f"mailto:{CONTACT_EMAIL}" if CONTACT_EMAIL else "", "✉️"),
    ]
    return [{"id": key, "url": url, "icon": icon}
            for key, url, icon in entries if url]


def payload() -> dict:
    """What the About tab needs, in one JSON-safe dictionary."""
    return {
        "appName": APP_NAME,
        "version": VERSION,
        "author": AUTHOR,
        "alias": ALIAS,
        "license": LICENSE,
        "copyright": f"© {COPYRIGHT_YEAR} {AUTHOR}",
        "links": links(),
        "builtWith": [{"name": name, "version": version}
                      for name, version in BUILT_WITH],
        # True while every link is still blank, so the page can say where to
        # fill them in rather than showing an empty box.
        "needsLinks": not links(),
        "linksFile": "about.py",
    }
