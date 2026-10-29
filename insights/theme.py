"""Look and feel (Option A, 'Vibrant tiles'): one colour and one icon per KPI, and status colours for categories.

Colours are CSS classes (tone-teal, tone-indigo, ...) defined in static/app.css, so light and dark themes stay in one place.
"""
from markupsafe import Markup

TONES = ["teal", "indigo", "amber", "coral", "blue", "violet", "green", "pink"]

# KPI -> (tone, icon). KPIs not listed take their page's tone and icon.
KPI_STYLE = {
    "EX-01": ("teal", "check"), "EX-02": ("teal", "gauge"), "EX-03": ("indigo", "search"), "EX-04": ("amber", "coin"),
    "EX-05": ("coral", "doc"), "EX-06": ("blue", "send"), "EX-07": ("violet", "shield"), "EX-08": ("violet", "scale"),
    "EX-09": ("pink", "stamp"), "EX-10": ("green", "calendar"),
    "DR-01": ("teal", "pulse"), "DR-02": ("amber", "inbox"), "DR-03": ("blue", "clock"), "DR-04": ("indigo", "layers"),
    "DR-05": ("coral", "target"), "DR-06": ("amber", "coin"), "DR-07": ("pink", "building"), "DR-08": ("green", "link"),
    "HD-01": ("violet", "inbox"), "HD-02": ("amber", "clock"), "HD-03": ("coral", "coin"), "HD-04": ("indigo", "pie"),
    "HD-05": ("green", "shield"), "HD-06": ("blue", "clock"), "HD-07": ("teal", "people"),
    "GS-01": ("pink", "stamp"), "GS-02": ("amber", "inbox"), "GS-03": ("teal", "gauge"), "GS-04": ("indigo", "search"),
    "GS-05": ("coral", "coin"), "GS-06": ("violet", "list"), "GS-07": ("amber", "flag"), "GS-08": ("blue", "clock"),
    "FR-01": ("teal", "doc"), "FR-02": ("indigo", "scissors"), "FR-03": ("coral", "copy"), "FR-04": ("green", "send"),
    "FR-05": ("blue", "calendar"), "FR-06": ("amber", "link"), "FR-07": ("violet", "inbox"), "FR-08": ("pink", "wallet"),
    "FW-01": ("coral", "flag"), "FW-02": ("green", "check"), "FW-03": ("amber", "alert"), "FW-04": ("violet", "send"),
    "FW-05": ("indigo", "funnel"), "FW-06": ("teal", "tree"), "FW-07": ("pink", "repeat"), "FW-08": ("blue", "bulb"),
    "GV-01": ("teal", "doc"), "GV-02": ("green", "stamp"), "GV-03": ("blue", "clock"), "GV-04": ("indigo", "check"),
    "GV-05": ("violet", "people"), "GV-06": ("amber", "bulb"),
    "OP-01": ("teal", "check"), "OP-02": ("amber", "coin"), "OP-03": ("indigo", "layers"), "OP-04": ("blue", "scale"),
    "OP-05": ("violet", "people"), "OP-06": ("green", "send"), "OP-07": ("pink", "calendar"), "OP-08": ("coral", "gauge"),
    "OP-09": ("teal", "pulse"),
}

# Category labels that carry meaning get a fixed colour wherever they appear (charts, legends).
SEMANTIC = {
    "Satisfactory": "green", "Satisfactory with exceptions": "amber", "Unsatisfactory": "coral",
    "Maintained": "green", "Partially maintained": "amber", "Reversed": "coral", "Withdrawn by hospital": "blue",
    "Fail": "coral", "Partial": "amber", "Pass": "green",
    "No issue identified": "green", "Documentation gap": "amber", "Clinical concern": "coral",
    "Financial discrepancy": "violet", "Insufficient information": "blue",
    "Error": "blue", "Waste": "amber", "Abuse": "coral", "Suspected fraud": "pink",
    "Medical and operational review": "teal", "Financial and accounting review": "indigo",
    "Endorse - route to TPA": "green", "Endorse – route to TPA": "green", "Not endorsed": "coral",
}

_P = {
    "check": '<path d="M9 11l3 3 8-8"/><path d="M20 12v6a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h9"/>',
    "gauge": '<path d="M12 14l4-4"/><path d="M3.3 19a10 10 0 1 1 17.4 0"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',
    "coin": '<path d="M12 2v20"/><path d="M17 6H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>',
    "doc": '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/>',
    "send": '<path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4 20-7z"/>',
    "shield": '<path d="M12 3l8 4v5c0 5-3.5 8-8 9-4.5-1-8-4-8-9V7l8-4z"/>',
    "scale": '<path d="M12 3v18M5 21h14M6 7h12"/><path d="M6 7l-3 6a3 3 0 0 0 6 0L6 7zM18 7l-3 6a3 3 0 0 0 6 0l-3-6z"/>',
    "stamp": '<path d="M5 21h14"/><path d="M6 17h12l-1-4H7l-1 4z"/><path d="M10 13V9a2 2 0 1 1 4 0v4"/>',
    "calendar": '<rect x="3" y="4" width="18" height="17" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/><path d="M9 15l2 2 4-4"/>',
    "pulse": '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    "inbox": '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.5 5h13L22 12v6a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-6L5.5 5z"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "layers": '<path d="M12 2l10 5-10 5L2 7l10-5z"/><path d="M2 17l10 5 10-5M2 12l10 5 10-5"/>',
    "target": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
    "building": '<rect x="4" y="2" width="16" height="20" rx="1"/><path d="M9 22v-4h6v4M8 6h2M14 6h2M8 10h2M14 10h2M8 14h2M14 14h2"/>',
    "link": '<path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"/><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/>',
    "pie": '<path d="M21 15.9A10 10 0 1 1 8.1 3"/><path d="M22 12A10 10 0 0 0 12 2v10z"/>',
    "people": '<circle cx="9" cy="8" r="4"/><path d="M2 21v-1a6 6 0 0 1 12 0v1"/><path d="M16 4a4 4 0 0 1 0 8M22 21v-1a6 6 0 0 0-4-5.7"/>',
    "list": '<path d="M9 6h12M9 12h12M9 18h12"/><path d="M4 6l1 1 2-2M4 12l1 1 2-2M4 18l1 1 2-2"/>',
    "flag": '<path d="M4 22V4"/><path d="M4 4h13l-2 4 2 4H4"/>',
    "scissors": '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M20 4L8.1 15.9M14.5 14.5L20 20M8.1 8.1L12 12"/>',
    "copy": '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/>',
    "wallet": '<rect x="2" y="6" width="20" height="14" rx="2"/><path d="M16 13h2M2 10h20M6 6V4h12v2"/>',
    "alert": '<path d="M12 3l10 18H2L12 3z"/><path d="M12 10v4M12 17.5v.5"/>',
    "funnel": '<path d="M3 4h18l-7 8v7l-4 2v-9L3 4z"/>',
    "tree": '<circle cx="12" cy="5" r="2"/><circle cx="5" cy="19" r="2"/><circle cx="19" cy="19" r="2"/><path d="M12 7v5M12 12H5v5M12 12h7v5"/>',
    "repeat": '<path d="M17 2l4 4-4 4"/><path d="M3 11V9a3 3 0 0 1 3-3h15"/><path d="M7 22l-4-4 4-4"/><path d="M21 13v2a3 3 0 0 1-3 3H3"/>',
    "bulb": '<path d="M9 18h6M10 22h4"/><path d="M12 2a7 7 0 0 0-4 12.7V16h8v-1.3A7 7 0 0 0 12 2z"/>',
}


def style(kid):
    return KPI_STYLE.get(kid, ("teal", "pulse"))


def icon(name, size=20):
    p = _P.get(name, _P["pulse"])
    return Markup(f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
                  f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{p}</svg>')


def tone_for(label, i):
    """Fixed colour for meaningful labels, otherwise cycle through the palette."""
    return SEMANTIC.get(str(label).strip(), TONES[i % len(TONES)])


def sparkline(values, tone="teal", w=96, h=28):
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return Markup("")
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    step = w / (len(values) - 1)
    pts = []
    for i, v in enumerate(values):
        if v is None:
            continue
        pts.append(f"{i * step:.1f},{h - 3 - (v - lo) / span * (h - 6):.1f}")
    last = pts[-1].split(",")
    return Markup(f'<svg class="spark t-{tone}" width="{w}" height="{h}" viewBox="0 0 {w} {h}" aria-hidden="true">'
                  f'<polyline points="{" ".join(pts)}" fill="none" stroke="currentColor" stroke-width="2.5" '
                  f'stroke-linecap="round" stroke-linejoin="round"/><circle cx="{last[0]}" cy="{last[1]}" r="3" fill="currentColor"/></svg>')
