"""Generate the pixel-art assets used by the Pixel Girlfriend UI.

Everything is drawn on a tiny logical grid (one "pixel" is SCALE screen pixels)
and upscaled with NEAREST resampling, which is what gives the crisp pixel look.

Run directly to (re)build the assets::

    python scripts/make_assets.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

# ---------------------------------------------------------------------------
# Canvas sizes (logical pixels) and the upscale factor.
# ---------------------------------------------------------------------------
SCALE = 5
CHAR_W, CHAR_H = 48, 64          # one sprite frame  -> 240 x 320 on screen
SCENE_W, SCENE_H = 60, 80        # background scene  -> 300 x 400 on screen

ASSETS = Path(__file__).resolve().parent.parent / "assets"

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
SKIN = (255, 216, 190)
SKIN_SHADE = (234, 178, 152)
HAIR = (112, 64, 128)
HAIR_DARK = (74, 40, 88)
HAIR_LIGHT = (154, 100, 172)
EYE_DARK = (52, 30, 66)
IRIS = (255, 118, 168)
WHITE = (255, 255, 255)
BLUSH = (255, 158, 182)
MOUTH = (196, 74, 108)
MOUTH_DARK = (150, 48, 80)
DRESS = (255, 110, 160)
DRESS_DARK = (212, 76, 128)
SHOE = (64, 36, 78)
OUTLINE = (38, 22, 46)
PINK = (255, 111, 168)
PINK_LIGHT = (255, 176, 208)


class Grid:
    """A tiny RGBA pixel buffer with a few drawing helpers."""

    def __init__(self, width: int, height: int) -> None:
        self.w = width
        self.h = height
        self.px: list[list[tuple[int, int, int] | None]] = [
            [None] * width for _ in range(height)
        ]

    # -- primitives ---------------------------------------------------------
    def set(self, x: int, y: int, color) -> None:
        if 0 <= x < self.w and 0 <= y < self.h:
            self.px[y][x] = color

    def rect(self, x0: int, y0: int, x1: int, y1: int, color) -> None:
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                self.set(x, y, color)

    def ellipse(self, cx: int, cy: int, rx: int, ry: int, color) -> None:
        for y in range(cy - ry, cy + ry + 1):
            for x in range(cx - rx, cx + rx + 1):
                dx = (x - cx) / max(rx, 1)
                dy = (y - cy) / max(ry, 1)
                if dx * dx + dy * dy <= 1.0:
                    self.set(x, y, color)

    def outline(self, color) -> None:
        """Add a 1px border around the opaque silhouette."""
        extra = []
        for y in range(self.h):
            for x in range(self.w):
                if self.px[y][x] is not None:
                    continue
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if 0 <= nx < self.w and 0 <= ny < self.h and self.px[ny][nx] is not None:
                        extra.append((x, y))
                        break
        for x, y in extra:
            self.px[y][x] = color

    # -- output -------------------------------------------------------------
    def to_image(self, scale: int = SCALE) -> Image.Image:
        img = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        img.putdata([
            (c[0], c[1], c[2], 255) if c else (0, 0, 0, 0)
            for row in self.px
            for c in row
        ])
        return img.resize((self.w * scale, self.h * scale), Image.NEAREST)


def _heart(g: Grid, x: int, y: int, color) -> None:
    shape = ("01101", "11111", "01110", "00100")
    for dy, row in enumerate(shape):
        for dx, cell in enumerate(row):
            if cell == "1":
                g.set(x + dx, y + dy, color)


# ---------------------------------------------------------------------------
# Character
# ---------------------------------------------------------------------------
def build_character(eyes: str = "open", mouth: str = "smile", bob: int = 0) -> Grid:
    """Draw one 48x64 frame of the girlfriend.

    eyes  : "open" | "blink"
    mouth : "smile" | "open" | "wide"
    bob   : vertical offset in logical pixels (0 or 1)
    """
    g = Grid(CHAR_W, CHAR_H)
    o = bob

    # Long hair behind everything.
    g.ellipse(24, 27 + o, 17, 22, HAIR)
    # Face.
    g.ellipse(24, 23 + o, 12, 12, SKIN)
    # Fringe / bangs: straight hem with one side swept a little lower.
    g.rect(11, 9 + o, 37, 15 + o, HAIR)
    g.rect(11, 16 + o, 20, 16 + o, HAIR)
    # Strand highlights on the fringe.
    for x in range(14, 35, 6):
        g.rect(x, 10 + o, x + 1, 12 + o, HAIR_LIGHT)

    # Side locks framing the face.
    g.rect(8, 15 + o, 13, 41 + o, HAIR)
    g.rect(35, 15 + o, 40, 41 + o, HAIR)
    g.rect(8, 22 + o, 9, 41 + o, HAIR_DARK)
    g.rect(39, 22 + o, 40, 41 + o, HAIR_DARK)

    # Neck.
    g.rect(21, 33 + o, 27, 38 + o, SKIN)
    g.rect(21, 36 + o, 27, 38 + o, SKIN_SHADE)

    # Dress body.
    for y in range(37, 49):
        hw = 8 + int((y - 37) * 0.5)
        g.rect(24 - hw, y + o, 24 + hw, y + o, DRESS)
    # Skirt.
    for y in range(48, 55):
        hw = 13 + int((y - 48) * 0.8)
        g.rect(24 - hw, y + o, 24 + hw, y + o, DRESS)
    # Pleats.
    for x in (15, 24, 33):
        g.rect(x, 50 + o, x, 54 + o, DRESS_DARK)
    # Collar.
    g.rect(20, 37 + o, 28, 38 + o, DRESS_DARK)

    # Arms + sleeves.
    g.rect(9, 39 + o, 13, 49 + o, SKIN)
    g.rect(35, 39 + o, 39, 49 + o, SKIN)
    g.rect(9, 38 + o, 13, 42 + o, DRESS)
    g.rect(35, 38 + o, 39, 42 + o, DRESS)
    # Hands.
    g.rect(9, 49 + o, 13, 51 + o, SKIN_SHADE)
    g.rect(35, 49 + o, 39, 51 + o, SKIN_SHADE)

    # Legs and shoes (kept one row above the frame edge so the "bob"
    # animation frame never loses its outline).
    g.rect(19, 55 + o, 22, 59 + o, SKIN)
    g.rect(26, 55 + o, 29, 59 + o, SKIN)
    g.rect(18, 60 + o, 23, 61 + o, SHOE)
    g.rect(25, 60 + o, 30, 61 + o, SHOE)

    # Eyes.
    if eyes == "blink":
        g.rect(16, 24 + o, 20, 24 + o, EYE_DARK)
        g.rect(28, 24 + o, 32, 24 + o, EYE_DARK)
        g.set(16, 23 + o, EYE_DARK)
        g.set(32, 23 + o, EYE_DARK)
    else:
        for left in (16, 28):
            g.rect(left, 21 + o, left + 4, 21 + o, EYE_DARK)      # lashes
            g.rect(left, 22 + o, left + 4, 25 + o, WHITE)
            g.rect(left + 1, 22 + o, left + 3, 25 + o, IRIS)
            g.set(left + 1, 23 + o, EYE_DARK)
            g.set(left + 1, 22 + o, WHITE)                        # sparkle
            g.set(left + 4, 25 + o, EYE_DARK)                     # corner lash

    # Blush.
    g.rect(14, 27 + o, 17, 28 + o, BLUSH)
    g.rect(31, 27 + o, 34, 28 + o, BLUSH)

    # Mouth.
    if mouth == "open":
        g.ellipse(24, 30 + o, 2, 2, MOUTH)
        g.set(23, 31 + o, MOUTH_DARK)
        g.set(24, 31 + o, MOUTH_DARK)
    elif mouth == "wide":
        g.ellipse(24, 30 + o, 3, 2, MOUTH)
        g.rect(22, 31 + o, 26, 31 + o, MOUTH_DARK)
    else:
        g.set(22, 30 + o, MOUTH)
        g.set(23, 31 + o, MOUTH)
        g.set(24, 31 + o, MOUTH)
        g.set(25, 30 + o, MOUTH)

    g.outline(OUTLINE)
    return g


def build_sprite_sheet() -> Image.Image:
    """Four frames: idle, blink, talking (two mouth shapes)."""
    frames = [
        build_character(eyes="open", mouth="smile", bob=0),
        build_character(eyes="blink", mouth="smile", bob=0),
        build_character(eyes="open", mouth="open", bob=1),
        build_character(eyes="open", mouth="wide", bob=0),
    ]
    fw, fh = CHAR_W * SCALE, CHAR_H * SCALE
    sheet = Image.new("RGBA", (fw * len(frames), fh), (0, 0, 0, 0))
    for i, frame in enumerate(frames):
        sheet.paste(frame.to_image(), (i * fw, 0))
    return sheet


# ---------------------------------------------------------------------------
# Scene background
# ---------------------------------------------------------------------------
def _lerp(c0, c1, t: float):
    return tuple(int(a + (b - a) * t) for a, b in zip(c0, c1))


def build_background() -> Grid:
    """The room behind her.

    The sprite covers the middle of the scene (roughly x=13..47, y=20..80 in
    logical units), so decorations live in the wall band above her head and in
    the narrow strips beside her.
    """
    g = Grid(SCENE_W, SCENE_H)

    # Wall gradient.
    for y in range(59):
        g.rect(0, y, SCENE_W - 1, y, _lerp((48, 32, 66), (26, 16, 38), y / 58))

    # Faint wallpaper stripes.
    for x in range(0, SCENE_W, 8):
        g.rect(x, 0, x, 57, _lerp((54, 37, 74), (30, 19, 43), 0.35))

    # Floor with a chunky checker pattern.
    for y in range(60, SCENE_H):
        for x in range(SCENE_W):
            base = (42, 28, 56) if (x // 3 + y // 2) % 2 else (34, 22, 46)
            g.set(x, y, base)
    g.rect(0, 58, SCENE_W - 1, 59, (66, 44, 84))  # baseboard

    # Tall window on the left, in the strip beside her hair.
    g.rect(1, 5, 13, 33, (88, 60, 106))
    g.rect(3, 7, 11, 31, (18, 13, 38))
    g.ellipse(7, 11, 2, 2, (250, 240, 205))
    for sx, sy in ((5, 16), (9, 19), (4, 24), (10, 27), (7, 29)):
        g.set(sx, sy, (236, 232, 255))
    g.rect(7, 7, 7, 31, (88, 60, 106))      # mullion
    g.rect(3, 18, 11, 18, (88, 60, 106))
    # Curtain rod + curtain.
    g.rect(0, 4, 14, 4, (120, 56, 94))
    g.rect(13, 5, 15, 34, (150, 74, 118))
    g.rect(14, 5, 14, 34, (120, 56, 94))

    # Framed heart picture high on the right wall, clear of her head.
    g.rect(39, 4, 56, 16, (88, 60, 106))
    g.rect(41, 6, 54, 14, (48, 30, 64))
    _heart(g, 46, 8, PINK)

    # Rug under her feet.
    g.ellipse(30, 76, 26, 5, (98, 56, 86))
    g.ellipse(30, 76, 21, 3, (118, 68, 100))

    # Ambient sparkles and floating hearts in the empty corners.
    for sx, sy in ((30, 5), (57, 30), (4, 45), (56, 48), (24, 12)):
        g.set(sx, sy, (255, 210, 230))
    _heart(g, 28, 2, PINK_LIGHT)
    _heart(g, 52, 24, PINK_LIGHT)

    return g


def generate_all(out_dir: Path | None = None) -> dict[str, Path]:
    """Write avatar.png (sprite sheet) and background.png. Returns written paths."""
    out_dir = Path(out_dir) if out_dir else ASSETS
    out_dir.mkdir(parents=True, exist_ok=True)

    avatar = out_dir / "avatar.png"
    background = out_dir / "background.png"

    build_sprite_sheet().save(avatar)
    build_background().to_image().save(background)

    return {"avatar": avatar, "background": background}


if __name__ == "__main__":
    written = generate_all()
    for name, path in written.items():
        with Image.open(path) as im:
            print(f"{name:10s} {path}  {im.width}x{im.height}")
