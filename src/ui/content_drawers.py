import math

from PIL import Image, ImageDraw, ImageFilter

from .glass_renderer import (
    BADGE_OFF_BG,
    BADGE_OFF_FG,
    BADGE_ON_BG,
    BADGE_ON_FG,
    COLOR_ERROR,
    COLOR_RESULT,
    DOT_COLOR,
    PAD,
    PILL_H,
    PILL_R,
    PILL_W,
    TEXT_BACKDROP,
    WAVE_FILL_HI,
    WAVE_FILL_LO,
    WAVE_MAX_H,
    WAVE_MIN_H,
    WAVE_POINTS,
    WAVE_WIDTH,
    _lerp,
)


def downsample_levels(raw, points=WAVE_POINTS):
    n = len(raw)
    chunk = max(1, n // points)
    out = []
    for i in range(points):
        start = i * chunk
        end = min(start + chunk, n)
        out.append(sum(raw[start:end]) / max(1, end - start) if start < end else 0.0)
    return out


def draw_dots(draw, s, cx, cy, alpha=1.0):
    count, sp = 10, 14 * s
    sx = cx - (count - 1) * sp / 2
    a = max(0, int(DOT_COLOR[3] * alpha))
    color = DOT_COLOR[:3] + (a,)
    for i in range(count):
        x, r = sx + i * sp, 2.5 * s
        draw.ellipse([x - r, cy - r, x + r, cy + r], fill=color)


def draw_waveform(img, s, cx, cy, smooth, levels_func, alpha=1.0):
    levels = levels_func()
    ww = WAVE_WIDTH * s
    sx = cx - ww / 2
    step = ww / max(1, WAVE_POINTS - 1)

    for i in range(WAVE_POINTS):
        smooth[i] = smooth[i] * 0.55 + levels[i] * 0.45  # tuned for ~60fps

    # Skip drawing if no actual audio — prevents thin-band artifact on quick tap
    if max(smooth) < 0.02:
        return smooth

    avg = sum(smooth) / len(smooth)
    t = min(1.0, avg * 2.5)

    top, bot = [], []
    for i in range(WAVE_POINTS):
        x = sx + i * step
        lv = max(smooth[i], 0.01)
        h = (WAVE_MIN_H + lv * (WAVE_MAX_H - WAVE_MIN_H)) * s
        top.append((x, cy - h))
        bot.append((x, cy + h))

    wave_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    wd = ImageDraw.Draw(wave_layer)
    poly = top + bot[::-1]
    if len(poly) >= 3:
        wd.polygon(poly, fill=_lerp(WAVE_FILL_LO, WAVE_FILL_HI, t))

    wave_layer = wave_layer.filter(ImageFilter.GaussianBlur(max(1, int(0.6 * s))))

    if alpha < 1.0:
        wa = wave_layer.split()[3]
        wa = wa.point(lambda p: int(p * alpha))
        wave_layer.putalpha(wa)

    result = Image.alpha_composite(img, wave_layer)
    img.paste(result, (0, 0))
    return smooth


def draw_spinner(draw, s, cx, cy, ai, alpha=1.0):
    n, rad = 8, 10 * s
    for i in range(n):
        angle = (2 * math.pi * i / n) - (ai * 0.35)
        x = cx + rad * math.cos(angle)
        y = cy + rad * math.sin(angle)
        bright = ((i + ai) % n) / n
        r = (1.5 + bright * 2) * s
        a = int((25 + bright * 210) * alpha)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, a))


def draw_text(draw, s, cx, cy, text, state, font_func, alpha=1.0):
    # Draw semi-opaque backdrop inside pill for text readability
    pad = PAD * s
    pw, ph, pr = PILL_W * s, PILL_H * s, PILL_R * s
    bd_a = max(0, int(TEXT_BACKDROP[3] * alpha))
    bd_color = TEXT_BACKDROP[:3] + (bd_a,)
    draw.rounded_rectangle(
        [pad, pad, pad + pw - 1, pad + ph - 1],
        radius=pr,
        fill=bd_color,
    )

    txt = text
    if len(txt) > 28:
        txt = txt[:25] + "..."
    base = COLOR_RESULT if state == "result" else COLOR_ERROR
    color = base[:3] + (max(0, int(base[3] * alpha)),)
    font = font_func(int(10 * s), bold=False)
    bb = draw.textbbox((0, 0), txt, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    draw.text((cx - tw / 2, cy - th / 2 - bb[1]), txt, fill=color, font=font)


def draw_badge(draw, s, mode, font_func, alpha=1.0):
    bx = (PAD + PILL_W - 34) * s
    by = (PAD + PILL_H / 2) * s
    bw, bh, r = 30 * s, 16 * s, 5 * s
    x1, y1 = bx - bw / 2, by - bh / 2
    x2, y2 = bx + bw / 2, by + bh / 2

    if mode == "translate":
        bg, fg, label = BADGE_ON_BG, BADGE_ON_FG, "→EN"
    else:
        bg, fg, label = BADGE_OFF_BG, BADGE_OFF_FG, "자동"

    bgc = bg[:3] + (max(0, int(bg[3] * alpha)),)
    fgc = fg[:3] + (max(0, int(fg[3] * alpha)),)
    draw.rounded_rectangle([x1, y1, x2, y2], radius=r, fill=bgc)
    font = font_func(int(7.5 * s), bold=True)
    bb = draw.textbbox((0, 0), label, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    draw.text((bx - tw / 2, by - th / 2 - bb[1]), label, fill=fgc, font=font)


def draw_state_content(
    img,
    s,
    cx,
    cy,
    state,
    alpha,
    ai,
    smooth,
    levels_func,
    result_text,
    font_func,
):
    draw = ImageDraw.Draw(img)
    if state == "idle":
        draw_dots(draw, s, cx, cy, alpha=alpha)
        return smooth
    if state == "recording":
        return draw_waveform(img, s, cx, cy, smooth, levels_func, alpha=alpha)
    if state == "processing":
        draw_spinner(draw, s, cx, cy, ai, alpha=alpha)
        return smooth
    if state in ("result", "error"):
        draw_text(draw, s, cx, cy, result_text, state, font_func, alpha=alpha)
        return smooth
    return smooth
