from PIL import Image, ImageChops, ImageEnhance, ImageFilter, ImageGrab, ImageDraw

PILL_W, PILL_H, PILL_R = 280, 40, 20
PAD = 8
WIN_W = PILL_W + PAD * 2
WIN_H = PILL_H + PAD * 2
MINI_SIZE = 14
SS = 2

REFRACTION_ZOOM = 0.10
GLASS_BLUR = 18
GLASS_SATURATION = 1.15
GLASS_TINT = (255, 255, 255, 22)

SHADOW_COLOR = (0, 0, 0, 70)
SHADOW_OFFSET_Y = 3
SHADOW_BLUR = 5

WAVE_POINTS = 12
WAVE_MAX_H = 7
WAVE_MIN_H = 0.4
WAVE_WIDTH = 155
WAVE_FILL_HI = (255, 255, 255, 65)
WAVE_FILL_LO = (255, 255, 255, 20)
WAVE_LINE_HI = (255, 255, 255, 190)
WAVE_LINE_LO = (255, 255, 255, 60)
WAVE_GLOW_HI = (255, 255, 255, 30)

DOT_COLOR = (255, 255, 255, 60)

BADGE_ON_BG = (255, 255, 255, 35)
BADGE_ON_FG = (255, 255, 255, 210)
BADGE_OFF_BG = (255, 255, 255, 12)
BADGE_OFF_FG = (255, 255, 255, 120)

COLOR_RESULT = (255, 255, 255, 230)
COLOR_ERROR = (255, 120, 120, 230)

LEVEL_BUF = 48
AUTO_HIDE_MS = 1000


def _lerp(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def capture_background(x, y, w, h):
    try:
        img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
        iw, ih = img.size
        mx = int(iw * REFRACTION_ZOOM / 2)
        my = int(ih * REFRACTION_ZOOM / 2)
        if mx > 0 and my > 0:
            img = img.crop((mx, my, iw - mx, ih - my))
            img = img.resize((iw, ih), Image.LANCZOS)
        img = img.filter(ImageFilter.GaussianBlur(radius=GLASS_BLUR))
        img = ImageEnhance.Color(img).enhance(GLASS_SATURATION)
        return img
    except Exception:
        return None


def draw_glass_pill(img, bg_blur, s):
    pad = PAD * s
    pw, ph, pr = PILL_W * s, PILL_H * s, PILL_R * s
    iw, ih = img.size

    pill_mask = Image.new("L", (pw, ph), 0)
    ImageDraw.Draw(pill_mask).rounded_rectangle(
        [0, 0, pw - 1, ph - 1], radius=pr, fill=255
    )

    shadow = Image.new("RGBA", (iw, ih), (0, 0, 0, 0))
    sh_y = pad + int(SHADOW_OFFSET_Y * s)
    sh_fill = Image.new("RGBA", (pw, ph), SHADOW_COLOR)
    shadow.paste(sh_fill, (pad, sh_y), pill_mask)
    shadow = shadow.filter(ImageFilter.GaussianBlur(int(SHADOW_BLUR * s)))
    img.paste(Image.alpha_composite(img.copy(), shadow), (0, 0))

    if bg_blur:
        glass = bg_blur.resize((pw, ph), Image.LANCZOS).convert("RGBA")
    else:
        glass = Image.new("RGBA", (pw, ph), (50, 52, 60, 255))
    glass = Image.alpha_composite(glass, Image.new("RGBA", (pw, ph), GLASS_TINT))
    img.paste(glass, (pad, pad), pill_mask)

    glow = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    ew = int(pw * 0.6)
    eh = int(ph * 1.0)
    gd.ellipse(
        [(pw - ew) // 2, -int(eh * 0.55), (pw + ew) // 2, int(eh * 0.45)],
        fill=(255, 255, 255, 35),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(int(5 * s)))
    glow_full = Image.new("RGBA", (iw, ih), (0, 0, 0, 0))
    glow_full.paste(glow, (pad, pad), pill_mask)
    img.paste(Image.alpha_composite(img.copy(), glow_full), (0, 0))

    edge = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    ImageDraw.Draw(edge).rounded_rectangle(
        [0, 0, pw - 1, ph - 1],
        radius=pr,
        outline=(255, 255, 255, 140),
        width=max(1, s),
    )
    grad = Image.new("L", (pw, ph), 0)
    for row in range(ph):
        t = 1.0 - (row / ph)
        val = int((0.12 + 0.88 * (t**1.3)) * 255)
        grad.paste(val, (0, row, pw, row + 1))
    edge_alpha = edge.split()[3]
    edge_alpha = ImageChops.multiply(edge_alpha, grad)
    edge.putalpha(edge_alpha)

    edge_full = Image.new("RGBA", (iw, ih), (0, 0, 0, 0))
    edge_full.paste(edge, (pad, pad))
    img.paste(Image.alpha_composite(img.copy(), edge_full), (0, 0))


__all__ = [
    "PILL_W",
    "PILL_H",
    "PILL_R",
    "PAD",
    "WIN_W",
    "WIN_H",
    "MINI_SIZE",
    "SS",
    "REFRACTION_ZOOM",
    "GLASS_BLUR",
    "GLASS_SATURATION",
    "GLASS_TINT",
    "SHADOW_COLOR",
    "SHADOW_OFFSET_Y",
    "SHADOW_BLUR",
    "WAVE_POINTS",
    "WAVE_MAX_H",
    "WAVE_MIN_H",
    "WAVE_WIDTH",
    "WAVE_FILL_HI",
    "WAVE_FILL_LO",
    "WAVE_LINE_HI",
    "WAVE_LINE_LO",
    "WAVE_GLOW_HI",
    "DOT_COLOR",
    "BADGE_ON_BG",
    "BADGE_ON_FG",
    "BADGE_OFF_BG",
    "BADGE_OFF_FG",
    "COLOR_RESULT",
    "COLOR_ERROR",
    "LEVEL_BUF",
    "AUTO_HIDE_MS",
    "_lerp",
    "capture_background",
    "draw_glass_pill",
]
