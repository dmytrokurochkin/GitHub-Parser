"""Draws the header images day.png, week.png and month.png next to this file.

    python assets/make_banners.py [--channel @name] [--bold FONT.ttf] [--regular FONT.ttf]

The bot does not run this: the PNGs are committed and Telegram downloads them
from IMAGES_URL. Replace them with your own under the same names if you like,
and bump IMAGES_VERSION in services/digest.py: Telegram caches previews by URL.
"""
import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
WIDTH, HEIGHT = 1280, 640
BACKGROUND = (13, 17, 23)
TEXT = (240, 246, 252)
MUTED = (139, 148, 158)
CHANNEL = "@GitHubMZTop"

BANNERS = {
    "day": ("ДНЯ", (63, 185, 80)),
    "week": ("ТИЖНЯ", (88, 166, 255)),
    "month": ("МІСЯЦЯ", (210, 168, 255)),
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


def draw(key: str, word: str, accent: tuple[int, int, int], channel: str, bold: str, regular: str) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)

    # Soft glow behind the star
    glow = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    ImageDraw.Draw(glow).ellipse((760, 80, 1240, 560), fill=tuple(c // 3 for c in accent))
    image = Image.blend(image, glow.filter(ImageFilter.GaussianBlur(120)), 1.0)
    canvas = ImageDraw.Draw(image)

    # Dot grid
    for x in range(40, WIDTH, 40):
        for y in range(40, HEIGHT, 40):
            canvas.ellipse((x - 1, y - 1, x + 1, y + 1), fill=(33, 38, 45))

    canvas.polygon(star(1000, 320, 190, 78), fill=accent)
    canvas.polygon(star(1000, 320, 150, 62), fill=BACKGROUND)
    canvas.polygon(star(1000, 320, 110, 45), fill=accent)

    small = ImageFont.truetype(bold, 30)
    huge = ImageFont.truetype(bold, 170)
    big = ImageFont.truetype(bold, 120)
    regular_font = ImageFont.truetype(regular, 36)

    canvas.text((80, 70), "G I T H U B   T R E N D I N G", font=small, fill=MUTED)
    canvas.text((72, 110), "ТОП-10", font=huge, fill=TEXT)
    canvas.text((76, 290), word, font=big, fill=accent)
    canvas.text((80, 462), "найпопулярніші репозиторії GitHub", font=regular_font, fill=MUTED)

    hashtag = f"#{key}"
    left, top, right, bottom = canvas.textbbox((0, 0), hashtag, font=small)
    canvas.rounded_rectangle((80, 535, 80 + right - left + 40, 535 + bottom - top + 28), radius=24, outline=accent, width=3)
    canvas.text((100 - left, 549 - top), hashtag, font=small, fill=accent)

    # Channel name centred under the star, on the line of the hashtag
    channel_font = ImageFont.truetype(bold, 40)
    left, top, right, bottom = canvas.textbbox((0, 0), channel, font=channel_font)
    canvas.text((1000 - (right - left) / 2 - left, 560 - (bottom - top) / 2 - top), channel, font=channel_font, fill=TEXT)
    return image


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--channel", default=CHANNEL)
    parser.add_argument("--bold", default=None)
    parser.add_argument("--regular", default=None)
    args = parser.parse_args()
    bold = args.bold or find_font(BOLD_FONTS)
    regular = args.regular or find_font(REGULAR_FONTS)
    for key, (word, accent) in BANNERS.items():
        path = HERE / f"{key}.png"
        draw(key, word, accent, args.channel, bold, regular).save(path, optimize=True)
        print(path)


if __name__ == "__main__":
    main()
