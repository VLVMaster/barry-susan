#!/usr/bin/env python3
"""
Generates today's Barry & Susan illustration + story.
Run daily by the GitHub Action in .github/workflows/daily-image.yml

Uses Pollinations.ai — free, no API key, no signup. Trade-off: it's
anonymous/unauthenticated, so it's rate-limited (roughly 1 request per
15s) and has no uptime guarantee. Completely fine for one image a day.
"""
import json
import os
import sys
import time
import urllib.parse
from datetime import date, datetime, timezone

import requests

IMAGE_BASE_URL = "https://image.pollinations.ai/prompt"
TEXT_BASE_URL = "https://text.pollinations.ai"

# Page background colour — the image is generated on this exact colour so it
# sits on the page with no visible edge/box around the characters.
PAGE_BACKGROUND_HEX = "#F5EFE1"

# Fixed character description — repeated every single call.
# Consistency comes from restating this every time, not from the model remembering.
CHARACTER_DESCRIPTION = """
Two cartoon pigeons in a warm, flat, gently retro illustration style,
bold outlines, limited earthy-plus-one-accent-colour palette, simple
shading, a children's-book-illustration feel, no photorealism.
Barry: a slightly round, scruffy grey pigeon with a bright orange
scarf, always looks a bit pleased with himself. Susan: a sleeker,
iridescent green-and-purple-necked pigeon with small round glasses,
always looks like she's the one actually in charge. Always shown
together, same two characters, same art style. No background scenery
of any kind, no ground, no sky, no props, no shadows. The entire area
behind the characters is a single flat, completely uniform, unbroken
solid colour, exactly {bg_hex}, filling the whole frame edge to edge,
no gradient, no texture. Just the two characters on flat colour,
nothing else.
""".format(bg_hex=PAGE_BACKGROUND_HEX).strip()

FALLBACK_THEME = "just an ordinary day, Barry and Susan pottering about doing nothing in particular"

STORY_SYSTEM_PROMPT = """
You write short, ridiculous, deadpan-funny stories about two pigeons,
Barry and Susan, who live on a windowsill. Given today's theme, write
ONE paragraph (60-100 words) explaining, in an absurdly over-serious
tone, what they're up to today and why. Treat pigeon nonsense with
total gravity. No preamble, no title, just the paragraph itself.
""".strip()


def load_themes(path: str) -> list[dict]:
    with open(path) as f:
        return json.load(f)


def todays_theme(themes: list[dict]) -> str:
    key = date.today().strftime("%m-%d")
    for entry in themes:
        if entry["date"] == key:
            return entry["theme"]
    return FALLBACK_THEME


def build_image_prompt(theme: str) -> str:
    return f"{CHARACTER_DESCRIPTION} Today's scene: {theme}."


def _get_with_retry(url: str, max_attempts: int = 4) -> requests.Response:
    """GET with retry/backoff. Pollinations is unauthenticated and can be
    flaky under load, so a transient failure shouldn't kill the whole run."""
    last_error = None
    for attempt in range(1, max_attempts + 1):
        resp = requests.get(url, timeout=120)
        if resp.status_code == 200:
            return resp

        print(f"Attempt {attempt}/{max_attempts} failed: HTTP {resp.status_code}")
        print(f"Response body: {resp.text[:500]}")
        last_error = resp
        wait = 5 * attempt  # 5s, 10s, 15s, 20s — gentle, since anonymous rate limit is ~1 req/15s
        print(f"Retrying in {wait}s...")
        time.sleep(wait)

    raise RuntimeError(f"Gave up after {max_attempts} attempts. Last status: {last_error.status_code}")


def generate_image(prompt: str) -> bytes:
    encoded = urllib.parse.quote(prompt)
    # width/height keep it a sensible landscape size; seed is left unset
    # on purpose so each day's image varies rather than repeating.
    url = f"{IMAGE_BASE_URL}/{encoded}?width=1024&height=768&nologo=true"
    resp = _get_with_retry(url)
    return resp.content


def generate_story(theme: str) -> str:
    prompt = f"{STORY_SYSTEM_PROMPT}\n\nToday's theme: {theme}"
    encoded = urllib.parse.quote(prompt)
    url = f"{TEXT_BASE_URL}/{encoded}"
    resp = _get_with_retry(url)
    return resp.text.strip()


def main():
    themes = load_themes("themes.json")
    theme = todays_theme(themes)
    image_prompt = build_image_prompt(theme)

    print(f"Theme: {theme}")
    image_bytes = generate_image(image_prompt)

    # Small pause to respect Pollinations' anonymous rate limit between
    # the image call and the text call.
    time.sleep(15)

    story = generate_story(theme)
    print(f"Story: {story}")

    os.makedirs("docs", exist_ok=True)
    with open("docs/today.png", "wb") as f:
        f.write(image_bytes)

    with open("docs/today.json", "w") as f:
        json.dump(
            {
                "date": date.today().isoformat(),
                "theme": theme,
                "story": story,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            f,
            indent=2,
        )

    print("Wrote docs/today.png and docs/today.json")


if __name__ == "__main__":
    sys.exit(main())
