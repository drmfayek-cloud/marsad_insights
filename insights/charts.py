"""Small server-drawn SVG charts: no chart library and nothing loaded from the internet.

Colours are palette tones (teal, indigo, amber, coral, blue, violet, green, pink) defined as CSS variables in
static/app.css. Labels with a meaning (Unsatisfactory, Maintained, ...) always get the same colour (see theme.SEMANTIC).
"""
import math

from markupsafe import Markup, escape

from .theme import TONES, tone_for


def fmt(v, money=False, pct=False):
    if v is None:
        return "-"
    if pct:
        return f"{v:.1%}" if abs(v) < 0.1 else f"{v:.0%}"
    if money:
        a = abs(v)
        if a >= 1e9:
            return f"{v / 1e9:,.2f}B"
        if a >= 1e6:
            return f"{v / 1e6:,.1f}M"
        if a >= 1e3:
            return f"{v / 1e3:,.0f}K"
        return f"{v:,.0f}"
    if isinstance(v, float) and not v.is_integer():
        return f"{v:,.1f}"
    return f"{v:,.0f}"


def fill(tone, soft=False):
    return f"fill:var(--{tone}{'-soft' if soft else ''})"


def empty(msg="No data for this selection."):
    return Markup(f"<p class='muted small'>{escape(msg)}</p>")


def hbar(items, money=False, pct=False, width=560, max_value=None, rtl=False, tone=None):
    """items: [(label, value)] as horizontal bars, one colour per bar (or one tone for all)."""
    items = [(l, v) for l, v in items if v is not None]
    if not items or not any(v for _, v in items):
        return empty()
    row, lab_w = 30, 200
    h = row * len(items) + 6
    mx = max_value or max(abs(v) for _, v in items) or 1
    bar_w = width - lab_w - 80
    out = [f"<svg class='chart' viewBox='0 0 {width} {h}' role='img'>"]
    for i, (lab, v) in enumerate(items):
        y = i * row + 5
        w = max(3, abs(v) / mx * bar_w)
        txt = fmt(v, money, pct)
        short = str(lab) if len(str(lab)) <= 30 else str(lab)[:29] + "…"
        col = fill(tone or tone_for(lab, i))
        if rtl:
            x0 = width - lab_w
            out.append(f"<text x='{width - 4}' y='{y + 15}' text-anchor='end' class='lab'>{escape(short)}</text>"
                       f"<rect x='{x0 - 8 - w:.1f}' y='{y + 2}' width='{w:.1f}' height='18' rx='9' style='{col}'>"
                       f"<title>{escape(str(lab))}: {txt}</title></rect>"
                       f"<text x='{x0 - 14 - w:.1f}' y='{y + 16}' text-anchor='end' class='val'>{txt}</text>")
        else:
            out.append(f"<text x='{lab_w - 10}' y='{y + 15}' text-anchor='end' class='lab'>{escape(short)}</text>"
                       f"<rect x='{lab_w}' y='{y + 2}' width='{w:.1f}' height='18' rx='9' style='{col}'>"
                       f"<title>{escape(str(lab))}: {txt}</title></rect>"
                       f"<text x='{lab_w + w + 8:.1f}' y='{y + 16}' class='val'>{txt}</text>")
    out.append("</svg>")
    return Markup("".join(out))


def columns(labels, series, money=False, pct=False, width=640, height=220, tones=None, highlight_last=False, highlight=None):
    """labels on x; series: [(name, [values])] as grouped rounded columns, with a legend when there are several.
    highlight_last: one series drawn in a soft tint with the last column in full colour (latest period)."""
    if not labels or not series or not any(v for _, vals in series for v in vals if v):
        return empty()
    tones = tones or [TONES[j % len(TONES)] for j in range(len(series))]
    pad_l, pad_b, pad_t = 56, 30, 12
    mx = max((v or 0) for _, vals in series for v in vals) or 1
    plot_w, plot_h = width - pad_l - 10, height - pad_b - pad_t
    gw = plot_w / len(labels)
    bw = max(3, min(34, (gw - 6) / len(series)))
    legend = 24 if len(series) > 1 else 0
    out = [f"<svg class='chart' viewBox='0 0 {width} {height + legend}' role='img'>"]
    for k in range(5):
        y = pad_t + plot_h - plot_h * k / 4
        out.append(f"<line x1='{pad_l}' x2='{width - 10}' y1='{y:.1f}' y2='{y:.1f}' class='grid'/>"
                   f"<text x='{pad_l - 8}' y='{y + 4:.1f}' text-anchor='end' class='axis'>{fmt(mx * k / 4, money, pct)}</text>")
    step = max(1, math.ceil(len(labels) / 16))
    last = len(labels) - 1
    if highlight is not None and highlight in labels:
        highlight_last, last = True, labels.index(highlight)
    for i, lab in enumerate(labels):
        x0 = pad_l + i * gw + (gw - bw * len(series)) / 2
        for j, (name, vals) in enumerate(series):
            v = vals[i] or 0
            hh = max(0, v / mx * plot_h)
            soft = highlight_last and i != last
            r = min(6, bw / 2, hh / 2) if hh else 0
            out.append(f"<rect x='{x0 + j * bw + 1:.1f}' y='{pad_t + plot_h - hh:.1f}' width='{max(1, bw - 2):.1f}' "
                       f"height='{hh:.1f}' rx='{r:.1f}' style='{fill(tones[j % len(tones)], soft)}'><title>{escape(name)} "
                       f"{escape(lab)}: {fmt(v, money, pct)}</title></rect>")
        if i % step == 0:
            cls = "axis strong" if highlight_last and i == last else "axis"
            out.append(f"<text x='{pad_l + i * gw + gw / 2:.1f}' y='{pad_t + plot_h + 18}' text-anchor='middle' "
                       f"class='{cls}'>{escape(lab)}</text>")
    if legend:
        lx = pad_l
        for j, (name, _) in enumerate(series):
            out.append(f"<rect x='{lx}' y='{height + 8}' width='12' height='12' rx='3' style='{fill(tones[j % len(tones)])}'/>"
                       f"<text x='{lx + 17}' y='{height + 18}' class='axis'>{escape(name)}</text>")
            lx += 30 + 7 * len(name)
    out.append("</svg>")
    return Markup("".join(out))


def donut(parts, money=False, size=170):
    parts = [(l, v) for l, v in parts if v]
    total = sum(v for _, v in parts)
    if not total:
        return empty()
    r, cx, cy, sw = 58, size / 2, size / 2, 26
    out = [f"<div class='donut'><svg viewBox='0 0 {size} {size}' width='{size}' height='{size}' role='img'>"
           f"<circle cx='{cx}' cy='{cy}' r='{r}' fill='none' class='track' stroke-width='{sw}'/>"]
    a0 = -math.pi / 2
    for i, (lab, v) in enumerate(parts):
        frac = v / total
        tone = tone_for(lab, i)
        if frac >= 0.9999:
            out.append(f"<circle cx='{cx}' cy='{cy}' r='{r}' fill='none' style='stroke:var(--{tone})' stroke-width='{sw}'/>")
        else:
            a1 = a0 + frac * 2 * math.pi
            x0, y0 = cx + r * math.cos(a0), cy + r * math.sin(a0)
            x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
            out.append(f"<path d='M{x0:.2f},{y0:.2f} A{r},{r} 0 {1 if frac > 0.5 else 0} 1 {x1:.2f},{y1:.2f}' "
                       f"fill='none' style='stroke:var(--{tone})' stroke-width='{sw}'><title>{escape(lab)}: {fmt(v, money)}</title></path>")
            a0 = a1
    out.append(f"<text x='{cx}' y='{cy + 7}' text-anchor='middle' class='donut-total'>{fmt(total, money)}</text></svg><ul>")
    for i, (lab, v) in enumerate(parts):
        out.append(f"<li><span style='background:var(--{tone_for(lab, i)})'></span>{escape(lab)} "
                   f"<b>{fmt(v, money)}</b> <i>{v / total:.0%}</i></li>")
    out.append("</ul></div>")
    return Markup("".join(out))


def funnel(steps, money=True, pending_label="Data capture in progress"):
    """steps: [(label, value or None)]; None = stage not captured yet."""
    top = next((v for _, v in steps if v), None)
    if not top:
        return empty()
    out = ["<div class='funnel'>"]
    for i, (lab, v) in enumerate(steps):
        if v is None:
            out.append(f"<div class='frow pending'><div class='flab'>{escape(lab)}</div><div class='fbar'></div>"
                       f"<div class='fval'><i>{escape(pending_label)}</i></div></div>")
            continue
        w = max(1.5, v / top * 100)
        out.append(f"<div class='frow'><div class='flab'>{escape(lab)}</div><div class='fbar'><div style='width:{w:.1f}%;"
                   f"background:var(--{TONES[i % len(TONES)]})'></div></div><div class='fval'>{'SAR ' if money else ''}"
                   f"{fmt(v, money)} <i>{v / top:.0%}</i></div></div>")
    out.append("</div>")
    return Markup("".join(out))
