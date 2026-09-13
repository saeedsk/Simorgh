"""Five funny Unicode cartoon splash screens. Plain data -- the runtime
gains no new dependency; colour, if any, is the caller's business.
Shown at random after the logo splash at startup (the creator, 2026)."""

import random

CARTOON_SPLASHES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("the phoenix and the coffee", (
        r"      ╭───────╮      ",
        r"      │ ☕ 🔥 │      ",
        r"   ╭──┴─────┴──╮   ",
        r"   │  ◉     ◉  │~  ",
        r"   ╰──┬───┬───┬╯~~~",
        r"      │ ﹏﹏﹏ │ ~  ",
        r"      ╰───────╯    ",
    )),
    ("thirty birds, one queue", (
        r"  🐦 🐦 🐦 🐦 🐦 🐦   ",
        r"  ▶ 🐦 🐦 🐦 🐦 🐦   ",
        r"  🐦 🐦 🐦 🐦 🐦 ⏳  ",
        r"  (the queue for wisdom)",
    )),
    ("the dramatic reader", (
        r"   ╭─────────────╮   ",
        r"   │ 📖 ╭ o o ╮  │   ",
        r"   │   ╰─ ▽ ─╯  │   ",
        r"   ╰──────┬──────╯   ",
        r"      ╶───┴───╮      ",
        r"      │ →  🐌 │      ",
        r"      ╰───────╯      ",
    )),
    ("the monday mood", (
        r"  ╔═══════════════╗  ",
        r"  ║  ◉  z Z z  ◉ ║  ",
        r"  ║  ~\______/~  ║  ",
        r"  ╚═══╦═══════╦═══╝  ",
        r"    ══╩═══════╩══    ",
    )),
    ("the grumpy printer", (
        r"  ┌─────────────┐    ",
        r"  │ ▤ ⚠  ▒▒▒▒▒ │    ",
        r"  │ (╯°□°)╯ ⚡  │    ",
        r"  └───┬─────┬───┘    ",
        r"   ═══╧═════╧═══    ",
        r"   paper jam. again. ",
    )),
)


def pick() -> tuple[str, tuple[str, ...]]:
    """Return one of the cartoons, chosen at random."""
    return random.choice(CARTOON_SPLASHES)
