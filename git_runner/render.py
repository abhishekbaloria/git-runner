"""One pixel runner, an empty background, and a circular path."""

from __future__ import annotations

import html
import math
from pathlib import Path
import shutil
import subprocess

from PIL import Image, ImageColor, ImageDraw

from .activity import RunnerState, Snapshot, derive_state

WIDTH = HEIGHT = 768
PIXELS = 256
FPS, FRAME_COUNT = 20, 240
BG = "#0d1117"


def mix(color: str, toward: str, fraction: float) -> str:
    a, b = ImageColor.getrgb(color), ImageColor.getrgb(toward)
    return "#" + "".join(f"{round(x + (y - x) * fraction):02x}" for x, y in zip(a, b))


def fps_for(state: RunnerState) -> int:
    return FPS if state.mode == "run" else 10


def position(phase: float) -> tuple[float, float, float]:
    """Foot position and tangent heading. One complete lap, with no drawn track."""
    theta = math.tau * (phase % 1) - math.pi / 2
    return 128 + 75 * math.cos(theta), 150 + 61 * math.sin(theta), theta + math.pi / 2


def character(state: RunnerState, phase: float, heading: float) -> Image.Image:
    """Render an upright person from a changing three-quarter view.

    Joint positions turn in the ground plane. The character never rotates like
    a flat cutout; his face, shoulders and limbs change with his heading.
    """
    phase = phase % 1
    sprite = Image.new("RGB", (96, 96), BG)
    draw = ImageDraw.Draw(sprite)
    fx, fy = math.cos(heading), math.sin(heading)
    rx, ry = -fy, fx
    running, resting = state.mode == "run", state.mode == "rest"
    cycles = 20 if running else 12 if not resting else 4
    gait = phase * math.tau * cycles + .7
    bob = abs(math.sin(gait)) * (1.4 if running else .5) if not resting else math.sin(gait) * .35
    lean = 4 if running else 1 if not resting else 0
    skin, skin_shadow = "#d9a075", "#ac7351"
    shirt = mix(state.color, "#d0eeff", .65)
    shirt_dark, shorts = mix(shirt, "#193249", .28), "#37475a"
    edge, hair = "#1d2633", "#443735"

    def point(side, forward, height):
        return (round(48 + rx * side + fx * forward),
                round(75 + .62 * (ry * side + fy * forward) - .88 * height))

    def depth(side, forward, height):
        return .85 * (ry * side + fy * forward) + .42 * height

    pieces = []

    def line(a, b, color, width, outline=True):
        z = sum(depth(*p) for p in (a, b)) / 2
        pieces.append((z, "line", (point(*a), point(*b), color, width, outline)))

    for side in (-1, 1):
        swing = 0 if resting else math.sin(gait + (math.pi if side == 1 else 0))
        h = side * 3
        hip = (h, 0, 24 + bob)
        knee = (h, swing * (9 if running else 6), 12 + max(0, swing) * (5 if running else 2))
        ankle = (h, swing * (16 if running else 9), max(0, -swing) * (10 if running else 3) + 1)
        hem = tuple(a + (b - a) * .48 for a, b in zip(hip, knee))
        line(hip, hem, shorts if side == 1 else "#2a3748", 5)
        line(hem, knee, skin if side == 1 else skin_shadow, 4)
        line(knee, ankle, skin if side == 1 else skin_shadow, 3)
        toe = (ankle[0], ankle[1] + 5, ankle[2])
        line(ankle, toe, "#e7f0ed", 4)
        sole_a, sole_b = (ankle[0], ankle[1], ankle[2] - 1), (toe[0], toe[1], toe[2] - 1)
        line(sole_a, sole_b, "#80c4dc", 1, False)

        shoulder = (side * 5, lean, 39 + bob)
        arm_swing = -swing
        elbow = (side * 6, lean + arm_swing * (8 if running else 5), 29 + bob)
        hand = (side * 6, elbow[1] + (7 if running else 2), elbow[2] + (7 if running else -4))
        sleeve = tuple(a + (b - a) * .4 for a, b in zip(shoulder, elbow))
        line(shoulder, sleeve, shirt if side == 1 else shirt_dark, 5)
        line(sleeve, elbow, skin if side == 1 else skin_shadow, 3)
        line(elbow, hand, skin if side == 1 else skin_shadow, 3)

    # A compact shaded shirt, viewed from any direction.
    corners = [(-5, -3, 25 + bob), (5, -3, 25 + bob), (5, 3, 25 + bob), (-5, 3, 25 + bob)]
    tops = [(-5, lean - 3, 40 + bob), (5, lean - 3, 40 + bob),
            (5, lean + 3, 40 + bob), (-5, lean + 3, 40 + bob)]
    for i in range(4):
        quad = [corners[i], corners[(i + 1) % 4], tops[(i + 1) % 4], tops[i]]
        color = shirt if i in (1, 2) else shirt_dark
        pieces.append((sum(depth(*p) for p in quad) / 4, "polygon", ([point(*p) for p in quad], color)))
    line((0, lean, 40 + bob), (0, lean, 44 + bob), skin, 4)

    for _, kind, values in sorted(pieces, key=lambda p: p[0]):
        if kind == "polygon":
            points, color = values
            draw.polygon(points, fill=color)
        else:
            a, b, color, width, outline = values
            if outline:
                draw.line((a, b), fill=edge, width=width + 2)
            draw.line((a, b), fill=color, width=width)

    # Head and hair show front, profile and back as the runner turns.
    hx, hy = point(0, lean + 1, 49 + bob)
    draw.ellipse((hx - 5, hy - 6, hx + 5, hy + 5), fill=edge)
    if fy < -.35:
        draw.ellipse((hx - 4, hy - 5, hx + 4, hy + 4), fill=hair)
        draw.rectangle((hx - 2, hy - 5, hx + 2, hy - 4), fill="#66514a")
        if abs(fx) > .5:
            nx = hx + round(fx * 4)
            draw.rectangle((nx - 1, hy, nx + 1, hy + 3), fill=skin)
    else:
        draw.ellipse((hx - 4, hy - 4, hx + 4, hy + 4), fill=skin)
        draw.rectangle((hx - 4, hy - 5, hx + 3, hy - 2), fill=hair)
        if fx > .3:
            draw.rectangle((hx - 4, hy - 3, hx - 2, hy + 1), fill=hair)
            draw.rectangle((hx + 4, hy, hx + 5, hy + 2), fill=skin)
            draw.point((hx + 3, hy), fill=edge)
        elif fx < -.3:
            draw.rectangle((hx + 2, hy - 3, hx + 4, hy + 1), fill=hair)
            draw.rectangle((hx - 5, hy, hx - 4, hy + 2), fill=skin)
            draw.point((hx - 3, hy), fill=edge)
        else:
            draw.point((hx - 2, hy), fill=edge)
            draw.point((hx + 2, hy), fill=edge)
            draw.line((hx - 1, hy + 3, hx + 1, hy + 3), fill=skin_shadow)
    return sprite


def frame(snapshot: Snapshot, state: RunnerState, index: int, name: str = "Abhishek") -> Image.Image:
    phase = (index % FRAME_COUNT) / FRAME_COUNT
    image = Image.new("RGB", (PIXELS, PIXELS), BG)
    if state.mode == "rest":
        x, y, heading = 128, 151, math.pi / 2
    else:
        x, y, heading = position(phase)
    sprite = character(state, phase, heading)
    image.paste(sprite, (round(x) - 48, round(y) - 75))
    return image.resize((WIDTH, HEIGHT), Image.Resampling.NEAREST)


def _atomic_gif(frames: list[Image.Image], path: Path, fps: int = FPS) -> None:
    # Collect a shared palette from every heading, including the back of the head.
    swatches = Image.new("RGB", (96 * 8, 96), BG)
    for i in range(8):
        sample = frames[i * len(frames) // 8].resize((256, 256), Image.Resampling.NEAREST)
        colors = sample.getcolors(65536) or []
        tile = Image.new("RGB", (96, 96), BG)
        for j, (_, color) in enumerate(colors):
            ImageDraw.Draw(tile).rectangle((j * 2 % 96, j * 2 // 96 * 2, j * 2 % 96 + 1, j * 2 // 96 * 2 + 1), fill=color)
        swatches.paste(tile, (i * 96, 0))
    palette = swatches.quantize(colors=128, method=Image.Quantize.MEDIANCUT)
    indexed = [im.quantize(palette=palette, dither=Image.Dither.NONE) for im in frames]
    temporary = path.with_name(path.name + ".tmp")
    indexed[0].save(temporary, format="GIF", save_all=True, append_images=indexed[1:],
                    duration=1000 // fps, loop=0, optimize=False, disposal=1)
    temporary.replace(path)


def video(frames, path: Path, fps: int = FPS) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("MP4 export needs FFmpeg on PATH.")
    temporary = path.with_name(path.stem + ".tmp.mp4")
    process = subprocess.Popen([ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo",
        "-vcodec", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{WIDTH}x{HEIGHT}",
        "-r", str(fps), "-i", "-", "-an", "-c:v", "libx264", "-crf", "17",
        "-preset", "fast", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(temporary)],
        stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert process.stdin is not None
        for im in frames:
            process.stdin.write(im.convert("RGB").tobytes())
        process.stdin.close()
        assert process.stderr is not None
        error = process.stderr.read().decode(errors="replace")
        if process.wait() != 0:
            raise RuntimeError("FFmpeg could not encode the MP4: " + error[-500:])
        temporary.replace(path)
    except BaseException:
        if process.poll() is None:
            process.kill()
            process.wait()
        temporary.unlink(missing_ok=True)
        raise


def render(snapshot: Snapshot, output: Path, name: str = "Abhishek", mode: str | None = None,
           mp4: bool = False) -> RunnerState:
    state = derive_state(snapshot, mode)
    output.mkdir(parents=True, exist_ok=True)
    frames = [frame(snapshot, state, i, name) for i in range(FRAME_COUNT)]
    fps = fps_for(state)
    _atomic_gif(frames, output / "runner.gif", fps)
    frames[0].save(output / "runner.png")
    if mp4:
        video(iter(frames), output / "runner.mp4", fps)
    title = html.escape(name + "'s Git Runner")
    (output / "preview.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{title}</title><style>html,body{{margin:0;background:{BG};height:100%}}'
        'body{display:grid;place-items:center}img{display:block;width:min(100vw,100vh,768px);height:auto}</style>'
        f'<img src="runner.gif" alt="A single pixel runner jogging in a circle on an empty dark background"></html>',
        encoding="utf-8")
    return state
