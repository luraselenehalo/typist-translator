"""
Icon builder - regenerate icon.ico and the transparent PNGs from icon.png.

The source artwork is a glossy badge painted on an opaque dark square. Windows
composites icons over the taskbar, the titlebar and the tray, so that baked-in
square shows up as a dark block on light backgrounds. This cuts the badge out
of its background and writes:

    icon.ico            multi-size icon for the window and taskbar
    icon_alpha.png      the badge with transparency (source for the tray)
    ui/public/icon.png  small copy used by the React header

Run it again after replacing icon.png:

    python make_icon.py
"""
import os
import sys

from PIL import Image, ImageChops, ImageFilter

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(BASE_DIR, "icon.png")
ICO_OUT = os.path.join(BASE_DIR, "icon.ico")
PNG_OUT = os.path.join(BASE_DIR, "icon_alpha.png")
UI_OUT = os.path.join(BASE_DIR, "ui", "public", "icon.png")

# Windows asks for these; supplying each one avoids ugly rescaling in the
# taskbar, alt-tab, the titlebar and Explorer.
ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]

BACKGROUND_TOLERANCE = 26


def _fill_convex(mask):
    """Close interior holes in a convex silhouette.

    The badge is convex, so a pixel is inside it exactly when it lies between
    the first and last lit pixel of both its row and its column. That rebuilds
    the shape without needing scipy, and without a flood fill leaking through
    the dark parts of the artwork.
    """
    width, height = mask.size
    pixels = mask.load()

    rows = Image.new("L", mask.size, 0)
    row_px = rows.load()
    for y in range(height):
        lit = [x for x in range(width) if pixels[x, y]]
        if lit:
            for x in range(lit[0], lit[-1] + 1):
                row_px[x, y] = 255

    cols = Image.new("L", mask.size, 0)
    col_px = cols.load()
    for x in range(width):
        lit = [y for y in range(height) if pixels[x, y]]
        if lit:
            for y in range(lit[0], lit[-1] + 1):
                col_px[x, y] = 255

    return ImageChops.multiply(rows, cols)


def build_alpha(source_path=SOURCE):
    """Return the badge as an RGBA image with its dark backdrop removed."""
    image = Image.open(source_path).convert("RGB")

    # The four corners are backdrop by definition; average them so a subtle
    # gradient in the backdrop does not throw the threshold off.
    w, h = image.size
    corners = [image.getpixel(p) for p in
               ((4, 4), (w - 5, 4), (4, h - 5), (w - 5, h - 5))]
    backdrop = tuple(sum(c[i] for c in corners) // len(corners) for i in range(3))

    difference = ImageChops.difference(
        image, Image.new("RGB", image.size, backdrop)).convert("L")
    rough = difference.point(lambda v: 255 if v > BACKGROUND_TOLERANCE else 0)

    silhouette = _fill_convex(rough)
    # Feather the cut so the edge does not look jagged once downscaled.
    silhouette = silhouette.filter(ImageFilter.GaussianBlur(1.6))
    silhouette = silhouette.point(lambda v: 0 if v < 110 else min(255, int(v * 1.35)))

    rgba = image.convert("RGBA")
    rgba.putalpha(silhouette)

    bbox = silhouette.getbbox()
    if bbox:
        rgba = rgba.crop(bbox)
        # Square it off so every icon size keeps the badge's proportions.
        side = max(rgba.size)
        square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        square.paste(rgba, ((side - rgba.width) // 2, (side - rgba.height) // 2))
        rgba = square
    return rgba


def main():
    if not os.path.exists(SOURCE):
        print(f"source artwork not found: {SOURCE}")
        return 1

    badge = build_alpha()
    print(f"badge cut out: {badge.size[0]}x{badge.size[1]} with alpha")

    badge.save(PNG_OUT)
    print(f"wrote {os.path.relpath(PNG_OUT, BASE_DIR)} "
          f"({os.path.getsize(PNG_OUT):,} bytes)")

    # Downscale each size separately: Pillow's own ICO writer resamples from
    # one bitmap, which smears the small sizes.
    frames = [badge.resize((size, size), Image.LANCZOS) for size in ICO_SIZES]
    frames[-1].save(ICO_OUT, format="ICO",
                    sizes=[(s, s) for s in ICO_SIZES],
                    append_images=frames[:-1])
    print(f"wrote {os.path.relpath(ICO_OUT, BASE_DIR)} "
          f"({os.path.getsize(ICO_OUT):,} bytes) with sizes {ICO_SIZES}")

    os.makedirs(os.path.dirname(UI_OUT), exist_ok=True)
    badge.resize((96, 96), Image.LANCZOS).save(UI_OUT, optimize=True)
    print(f"wrote {os.path.relpath(UI_OUT, BASE_DIR)} "
          f"({os.path.getsize(UI_OUT):,} bytes)")
    print("\nRebuild the UI so the header picks up the new file: build_ui.bat")
    return 0


if __name__ == "__main__":
    sys.exit(main())
