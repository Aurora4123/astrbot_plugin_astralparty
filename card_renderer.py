"""Local PNG rendering: no browser, remote renderer, or network required."""
import base64
import io
import os
import tempfile
from pathlib import Path


def find_font(bold=False, configured=""):
    candidates = [configured] if configured else []
    candidates += [
        "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/System/Library/Fonts/PingFang.ttc",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise OSError("未找到中文字体，请安装 fonts-noto-cjk 或配置 font_path")


def render_card(data, output_dir, font_path=""):
    from PIL import Image, ImageDraw, ImageFont

    scale = 2  # Supersample typography and rounded borders.
    regular, bold = find_font(configured=font_path), find_font(True, font_path)
    def font(size, heavy=False):
        path = bold if heavy else regular
        index = 2 if "NotoSansCJK" in path else 0
        return ImageFont.truetype(path, int(size * scale), index=index)
    metadata = data["metadata"]
    meta_height = len(metadata) * 48 + 36
    warning_height = 44 if data["limited"] else 0
    slot_height = 254
    slots_top = 56 + 88 + 28 + meta_height + warning_height
    height = slots_top + len(data["slots"]) * slot_height + 112
    image = Image.new("RGB", (960 * scale, height * scale), "#f5f1f4")
    draw = ImageDraw.Draw(image)
    def rect(box, fill, outline=None, radius=0, width=1):
        draw.rounded_rectangle(tuple(int(x * scale) for x in box),
                               radius=int(radius * scale), fill=fill, outline=outline,
                               width=width * scale)
    def text(x, y, content, size=24, color="#17233d", heavy=False, center=False, max_width=None):
        size_font = font(size, heavy)
        while max_width and draw.textlength(content, font=size_font) > max_width * scale and size > 14:
            size -= 1
            size_font = font(size, heavy)
        while max_width and draw.textlength(content, font=size_font) > max_width * scale and len(content) > 1:
            content = content[:-2] + "…"
        if center:
            x -= draw.textlength(content, font=size_font) / scale / 2
        draw.text((int(x * scale), int(y * scale)), content, font=size_font, fill=color)
    rect((28, 28, 932, height - 28), "#ffffff", "#e8e7eb", 28)
    rect((56, 56, 904, 144), "#ef70b5")
    text(480, 77, data["heading"], 29, "#ffffff", True, True)
    for cx in (340, 620):
        points = [(cx, 87), (cx + 4, 97), (cx + 14, 101), (cx + 4, 105),
                  (cx, 115), (cx - 4, 105), (cx - 14, 101), (cx - 4, 97)]
        draw.polygon([(x * scale, y * scale) for x, y in points], fill="#ffffff")
    top = 172
    rect((84, top, 876, top + meta_height), "#fcf7fa", "#f8dfef", 22, 2)
    for index, (label, value) in enumerate(metadata):
        y = top + 17 + index * 48
        text(112, y, label, 26, "#9141ba", True)
        text(208, y, value, 26, heavy=True, max_width=636)
    if data["limited"]:
        text(86, top + meta_height + 12, "限时地图 · 当前处于已配置的开放时段", 19, "#a0647b")
    for index, slot in enumerate(data["slots"]):
        y = slots_top + index * slot_height
        rect((84, y + 28, 876, y + 31), "#facbdc")
        text(84, y + 49, slot["position"], 27, heavy=True)
        text(194, y + 53, "（抽 1 个）", 23, "#627087", True)
        rect((84, y + 98, 320, y + 242), "#ffffff", "#eeedf1", 20, 2)
        if slot["avatar"]:
            try:
                body = base64.b64decode(slot["avatar"].split(",", 1)[1])
                portrait = Image.open(io.BytesIO(body)).convert("RGBA")
                ratio = min(76 * scale / portrait.width, 76 * scale / portrait.height)
                portrait = portrait.resize(
                    (max(1, int(portrait.width * ratio)), max(1, int(portrait.height * ratio))),
                    Image.Resampling.LANCZOS,
                )
                px = int(202 * scale - portrait.width / 2)
                py = int((y + 108) * scale)
                mask = Image.new("L", portrait.size, 0)
                ImageDraw.Draw(mask).ellipse((0, 0, portrait.width - 1, portrait.height - 1), fill=255)
                from PIL import ImageChops
                mask = ImageChops.multiply(mask, portrait.getchannel("A"))
                image.paste(portrait, (px, py), mask)
            except Exception:
                text(202, y + 112, slot["initial"], 42, "#a452a7", True, True)
        else:
            rect((164, y + 108, 240, y + 184), "#fce3f2", radius=38)
            text(202, y + 112, slot["initial"], 42, "#a452a7", True, True)
        text(202, y + 184, slot["name"], 22, heavy=True, center=True, max_width=212)
        text(202, y + 215, slot["title"], 16, "#8992a4", center=True, max_width=212)
    text(480, height - 90, "Astral Party · AstrBot", 16, "#acb2bf", center=True)
    text(480, height - 62, data["generated_at"] + " CST", 16, "#acb2bf", center=True)
    image = image.resize((960, height), Image.Resampling.LANCZOS)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix="draw-", suffix=".png", dir=output_dir)
    os.close(fd)
    try:
        image.save(path, "PNG", optimize=True)
    except BaseException:
        Path(path).unlink(missing_ok=True)
        raise
    return path
