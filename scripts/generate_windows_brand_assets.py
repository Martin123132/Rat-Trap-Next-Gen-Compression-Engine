"""Generate deterministic Windows icon assets from the Rat-Trap source mark.

This is a packaging-only helper. It requires Pillow and does not run as part of
Rat-Trap itself.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "packaging" / "branding" / "rat-trap-icon.png"
DEFAULT_ASSET_DIRECTORY = ROOT / "packaging" / "msix" / "Assets"
DEFAULT_ICO = ROOT / "packaging" / "branding" / "rat-trap.ico"
RESAMPLE = Image.Resampling.LANCZOS


def _normalised_mark(source: Image.Image, size: int) -> Image.Image:
    rgba = source.convert("RGBA")
    alpha = rgba.getchannel("A")
    bounds = alpha.getbbox()
    if bounds is None:
        raise ValueError("The source mark has no visible pixels")
    cropped = rgba.crop(bounds)
    content_size = max(1, round(size * 0.78))
    cropped.thumbnail((content_size, content_size), RESAMPLE)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(
        cropped,
        ((size - cropped.width) // 2, (size - cropped.height) // 2),
    )
    return canvas


def _file_type_icon(
    source: Image.Image,
    *,
    size: int,
    badge_colour: tuple[int, int, int, int],
    glyph: str,
) -> Image.Image:
    icon = _normalised_mark(source, size)
    draw = ImageDraw.Draw(icon)
    badge_size = round(size * 0.34)
    margin = round(size * 0.04)
    left = size - badge_size - margin
    top = size - badge_size - margin
    right = size - margin
    bottom = size - margin
    outline_width = max(1, round(size * 0.025))
    draw.ellipse(
        (left, top, right, bottom),
        fill=badge_colour,
        outline=(255, 255, 255, 255),
        width=outline_width,
    )
    white = (255, 255, 255, 255)
    centre_x = (left + right) // 2
    centre_y = (top + bottom) // 2
    stroke = max(1, round(size * 0.026))
    if glyph == "lock":
        body_width = round(badge_size * 0.46)
        body_height = round(badge_size * 0.36)
        body_left = centre_x - body_width // 2
        body_top = centre_y - round(body_height * 0.05)
        draw.rounded_rectangle(
            (
                body_left,
                body_top,
                body_left + body_width,
                body_top + body_height,
            ),
            radius=max(1, round(size * 0.025)),
            fill=white,
        )
        shackle_width = round(badge_size * 0.30)
        shackle_height = round(badge_size * 0.27)
        draw.arc(
            (
                centre_x - shackle_width // 2,
                body_top - shackle_height,
                centre_x + shackle_width // 2,
                body_top + round(shackle_height * 0.25),
            ),
            start=180,
            end=360,
            fill=white,
            width=stroke,
        )
    elif glyph == "archive":
        line_width = round(badge_size * 0.52)
        for offset in (-0.18, 0.0, 0.18):
            y = centre_y + round(badge_size * offset)
            draw.line(
                (
                    centre_x - line_width // 2,
                    y,
                    centre_x + line_width // 2,
                    y,
                ),
                fill=white,
                width=stroke,
            )
    else:
        raise ValueError(f"Unknown file-type glyph: {glyph}")
    return icon


def generate_assets(
    source_path: Path,
    asset_directory: Path,
    ico_path: Path,
) -> list[Path]:
    source = Image.open(source_path)
    asset_directory.mkdir(parents=True, exist_ok=True)
    ico_path.parent.mkdir(parents=True, exist_ok=True)

    outputs: list[Path] = []
    sizes = {
        "Square44x44Logo.png": 44,
        "Square150x150Logo.png": 150,
        "Square310x310Logo.png": 310,
        "StoreLogo.png": 50,
    }
    for name, size in sizes.items():
        destination = asset_directory / name
        _normalised_mark(source, size).save(destination, format="PNG")
        outputs.append(destination)

    sealed_logo = asset_directory / "RTSF.png"
    _file_type_icon(
        source,
        size=64,
        badge_colour=(245, 166, 35, 255),
        glyph="lock",
    ).save(sealed_logo, format="PNG")
    outputs.append(sealed_logo)

    archive_logo = asset_directory / "GMW.png"
    _file_type_icon(
        source,
        size=64,
        badge_colour=(24, 119, 242, 255),
        glyph="archive",
    ).save(archive_logo, format="PNG")
    outputs.append(archive_logo)

    ico_source = _normalised_mark(source, 256)
    ico_source.save(
        ico_path,
        format="ICO",
        sizes=[
            (16, 16),
            (20, 20),
            (24, 24),
            (32, 32),
            (40, 40),
            (48, 48),
            (64, 64),
            (128, 128),
            (256, 256),
        ],
    )
    outputs.append(ico_path)
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument(
        "--asset-directory",
        type=Path,
        default=DEFAULT_ASSET_DIRECTORY,
    )
    parser.add_argument("--ico", type=Path, default=DEFAULT_ICO)
    arguments = parser.parse_args()
    outputs = generate_assets(
        arguments.source.resolve(),
        arguments.asset_directory.resolve(),
        arguments.ico.resolve(),
    )
    for output in outputs:
        print(output)


if __name__ == "__main__":
    main()
