"""Render daily report markdown as a PNG image card."""
from __future__ import annotations

import io
import re
from dataclasses import dataclass

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# ── Layout ────────────────────────────────────────────────────────────────────
_W          = 860
_OUTER_PAD  = 32
_INNER_PAD  = 28
_CONTENT_W  = _W - _OUTER_PAD * 2 - _INNER_PAD * 2
_RADIUS     = 14
_LINE_SPC   = 8   # extra pixels below each text line

# ── Palette ───────────────────────────────────────────────────────────────────
_BG      = "#eef2f7"
_CARD    = "#ffffff"
_TITLE   = "#0f172a"
_SECTION = "#1d4ed8"
_BODY    = "#374151"
_MUTED   = "#6b7280"
_BULLET  = "#93c5fd"

# ── Font sizes ────────────────────────────────────────────────────────────────
_SZ_TITLE   = 22
_SZ_SECTION = 15
_SZ_BODY    = 13

_FONT_CACHE: dict = {}


def _font(size: int, bold: bool = False):
    key = (size, bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    candidates = [
        # macOS
        ("/System/Library/Fonts/STHeiti Medium.ttc",                   0),  # bold & regular
        ("/System/Library/Fonts/STHeiti Light.ttc",                    0),  # regular fallback
        ("/System/Library/Fonts/PingFang.ttc",                         5 if bold else 0),
        ("/Library/Fonts/Arial Unicode.ttf",                           0),
        # Linux
        ("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",            0),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",    0),
        # Windows
        ("C:/Windows/Fonts/" + ("msyhbd.ttc" if bold else "msyh.ttc"), 0),
    ]
    for path, idx in candidates:
        try:
            f = ImageFont.truetype(path, size, index=idx)
            _FONT_CACHE[key] = f
            return f
        except (OSError, IOError):
            continue
    f = ImageFont.load_default()
    _FONT_CACHE[key] = f
    return f


def _tw(draw, text: str, font) -> float:
    try:
        return draw.textlength(text, font=font)
    except AttributeError:
        return draw.textsize(text, font=font)[0]  # type: ignore[attr-defined]


def _wrap(draw, text: str, font, max_w: int) -> list[str]:
    if not text:
        return [""]
    result: list[str] = []
    while text:
        if _tw(draw, text, font) <= max_w:
            result.append(text)
            break
        lo, hi = 1, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if _tw(draw, text[:mid], font) <= max_w:
                lo = mid
            else:
                hi = mid - 1
        result.append(text[:lo])
        text = text[lo:]
    return result


def _strip_links(t: str) -> str:
    return re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', t)


def _strip_bold(t: str) -> str:
    return re.sub(r'\*\*([^*]+)\*\*', r'\1', t)


def _strip_emoji(t: str) -> str:
    # Remove supplementary-plane emoji and common symbols fonts typically lack
    t = re.sub(r'[\U00010000-\U0010ffff]', '', t, flags=re.UNICODE)
    t = re.sub(r'[☀-➿⬀-⯿︀-️]', '', t)
    return t.strip()


@dataclass
class _Row:
    text: str
    size: int    = _SZ_BODY
    bold: bool   = False
    color: str   = _BODY
    indent: int  = 0
    top_gap: int = 0
    bullet: bool = False


def _parse(content: str) -> list[_Row]:
    rows: list[_Row] = []
    for raw in content.splitlines():
        s = raw.strip()
        if not s:
            rows.append(_Row("", top_gap=6))
            continue
        if s.startswith("### "):
            rows.append(_Row(_strip_emoji(s[4:]), size=_SZ_TITLE, bold=True, color=_TITLE))
        elif s.startswith("**") and s.endswith("**") and len(s) > 4:
            rows.append(_Row(_strip_emoji(s[2:-2]), size=_SZ_SECTION, bold=True, color=_SECTION, top_gap=16))
        elif s.startswith("> - "):
            rows.append(_Row(_strip_bold(_strip_links(s[4:])), indent=16, bullet=True, top_gap=2))
        elif s.startswith("> "):
            rows.append(_Row(_strip_bold(_strip_links(s[2:])), indent=10, color=_MUTED, top_gap=2))
        else:
            rows.append(_Row(_strip_links(_strip_bold(s))))
    return rows


def _rounded_rect(draw, x0: int, y0: int, x1: int, y1: int, r: int, fill: str) -> None:
    draw.rectangle([x0 + r, y0, x1 - r, y1], fill=fill)
    draw.rectangle([x0, y0 + r, x1, y1 - r], fill=fill)
    draw.ellipse([x0,       y0,       x0 + r*2, y0 + r*2], fill=fill)
    draw.ellipse([x1 - r*2, y0,       x1,       y0 + r*2], fill=fill)
    draw.ellipse([x0,       y1 - r*2, x0 + r*2, y1      ], fill=fill)
    draw.ellipse([x1 - r*2, y1 - r*2, x1,       y1      ], fill=fill)


@dataclass
class _RL:
    text: str
    size: int
    bold: bool
    color: str
    indent: int
    top_gap: int
    bullet: bool


def render_report(content: str) -> bytes:
    """Render markdown report as PNG, return raw bytes."""
    if not PIL_AVAILABLE:
        raise ImportError("Pillow is required: pip install Pillow")

    probe = Image.new("RGB", (1, 1))
    dp = ImageDraw.Draw(probe)

    rows = _parse(content)

    # Expand rows into render lines (text wrapping applied)
    rl_list: list[_RL] = []
    for row in rows:
        if not row.text:
            rl_list.append(_RL("", row.size, row.bold, row.color, row.indent, row.top_gap, False))
            continue
        f = _font(row.size, row.bold)
        avail = _CONTENT_W - row.indent - (14 if row.bullet else 0)
        for i, seg in enumerate(_wrap(dp, row.text, f, avail)):
            rl_list.append(_RL(
                seg, row.size, row.bold, row.color,
                row.indent, row.top_gap if i == 0 else 1, row.bullet and i == 0,
            ))

    total_h = sum(rl.size + _LINE_SPC + rl.top_gap for rl in rl_list)
    card_h  = total_h + _INNER_PAD * 2
    img_h   = card_h  + _OUTER_PAD * 2

    img  = Image.new("RGB", (_W, img_h), _BG)
    draw = ImageDraw.Draw(img)

    cx0, cy0 = _OUTER_PAD, _OUTER_PAD
    cx1, cy1 = _W - _OUTER_PAD, _OUTER_PAD + card_h
    _rounded_rect(draw, cx0, cy0, cx1, cy1, _RADIUS, _CARD)

    y = cy0 + _INNER_PAD
    for rl in rl_list:
        y += rl.top_gap
        if not rl.text:
            y += rl.size + _LINE_SPC
            continue
        f = _font(rl.size, rl.bold)
        x = cx0 + _INNER_PAD + rl.indent
        if rl.bullet:
            bx, by = x, y + rl.size // 2 - 2
            draw.ellipse([bx, by, bx + 5, by + 5], fill=_BULLET)
            x += 14
        draw.text((x, y), rl.text, font=f, fill=rl.color)
        y += rl.size + _LINE_SPC

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
