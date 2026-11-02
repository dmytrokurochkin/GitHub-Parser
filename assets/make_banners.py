"""Draws the header images day.png, week.png and month.png next to this file.

    python assets/make_banners.py [--channel @name] [--bold FONT.ttf] [--regular FONT.ttf]

The bot does not run this: the PNGs are committed and Telegram downloads them
from IMAGES_URL. Replace them with your own under the same names if you like,
and bump IMAGES_VERSION in services/digest.py: Telegram caches previews by URL.
"""
import argparse
import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
WIDTH, HEIGHT = 1280, 640
CHANNEL = "@GitHubMZTop"

Color = tuple[int, int, int]


def hex_color(value: str) -> Color:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def mix(a: Color, b: Color, share: float) -> Color:
    """a with share of b blended in."""
    return tuple(round(x + (y - x) * share) for x, y in zip(a, b))


@dataclass(frozen=True)
class Palette:
    background: Color  # the dark color of the palette
    text: Color  # the light one: "ТОП-10", the channel, the inner star
    accent: Color  # the bright one: the period word, the star, the hashtag

    @property
    def muted(self) -> Color:
        return mix(self.background, self.text, 0.6)


# One three-color palette per period
BANNERS = {
    "day": ("ДНЯ", Palette(hex_color("#49022D"), hex_color("#E4DD95"), hex_color("#F7AF05"))),  # Mulberry, Buttercream, Marigold
    "week": ("ТИЖНЯ", Palette(hex_color("#273E49"), hex_color("#FEE1AF"), hex_color("#A76020"))),  # Slate Blue, Cream, Copper Brown
    "month": ("МІСЯЦЯ", Palette(hex_color("#091B27"), hex_color("#A3AFA5"), hex_color("#D5393A"))),  # Midnight Navy, Sage Mist, Vermilion
}

# Fonts with Cyrillic: Windows, then Debian (fonts-dejavu)
BOLD_FONTS = ("C:/Windows/Fonts/segoeuib.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
REGULAR_FONTS = ("C:/Windows/Fonts/segoeui.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")


def find_font(candidates: tuple[str, ...]) -> str:
    for path in candidates:
        if Path(path).exists():
            return path
    raise SystemExit(f"no font found, pass one: {candidates}")


def star(cx: float, cy: float, outer: float, inner: float) -> list[tuple[float, float]]:
    points = []
    for i in range(10):
        radius = outer if i % 2 == 0 else inner
        angle = math.pi / 2 + i * math.pi / 5
        points.append((cx + radius * math.cos(angle), cy - radius * math.sin(angle)))
    return points


def draw(key: str, word: str, palette: Palette, channel: str, bold: str, regular: str) -> Image.Image:
    accent, text, muted = palette.accent, palette.text, palette.muted

    # Soft glow of the accent behind the star
    glow = Image.new("RGB", (WIDTH, HEIGHT), palette.background)
    ImageDraw.Draw(glow).ellipse((760, 80, 1240, 560), fill=mix(palette.background, accent, 0.45))
    image = glow.filter(ImageFilter.GaussianBlur(120))
    canvas = ImageDraw.Draw(image)

    # Dot grid
    dot = mix(palette.background, text, 0.12)
    for x in range(40, WIDTH, 40):
        for y in range(40, HEIGHT, 40):
            canvas.ellipse((x - 1, y - 1, x + 1, y + 1), fill=dot)

    canvas.polygon(star(1000, 320, 190, 78), fill=accent)
    canvas.polygon(star(1000, 320, 150, 62), fill=palette.background)
    canvas.polygon(star(1000, 320, 110, 45), fill=text)

    small = ImageFont.truetype(bold, 30)
    huge = ImageFont.truetype(bold, 170)
    big = ImageFont.truetype(bold, 120)
    regular_font = ImageFont.truetype(regular, 36)

    canvas.text((80, 70), "G I T H U B   T R E N D I N G", font=small, fill=muted)
    canvas.text((72, 110), "ТОП-10", font=huge, fill=text)
    canvas.text((76, 290), word, font=big, fill=accent)
    canvas.text((80, 462), "найпопулярніші репозиторії GitHub", font=regular_font, fill=muted)

    hashtag = f"#{key}"
    left, top, right, bottom = canvas.textbbox((0, 0), hashtag, font=small)
    canvas.rounded_rectangle((80, 535, 80 + right - left + 40, 535 + bottom - top + 28), radius=24, outline=accent, width=3)
    canvas.text((100 - left, 549 - top), hashtag, font=small, fill=accent)

    # Channel name centred under the star, on the line of the hashtag
    channel_font = ImageFont.truetype(bold, 40)
    left, top, right, bottom = canvas.textbbox((0, 0), channel, font=channel_font)
    canvas.text((1000 - (right - left) / 2 - left, 560 - (bottom - top) / 2 - top), channel, font=channel_font, fill=text)
    return image


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--channel", default=CHANNEL)
    parser.add_argument("--bold", default=None)
    parser.add_argument("--regular", default=None)
    args = parser.parse_args()
    bold = args.bold or find_font(BOLD_FONTS)
    regular = args.regular or find_font(REGULAR_FONTS)
    for key, (word, palette) in BANNERS.items():
        path = HERE / f"{key}.png"
        draw(key, word, palette, args.channel, bold, regular).save(path, optimize=True)
        print(path)


if __name__ == "__main__":
    main()
