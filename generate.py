#!/usr/bin/env python3
"""
Generates today's Barry & Susan illustration.
Run daily by the GitHub Action in .github/workflows/daily-image.yml
"""
import base64
import json
import os
import sys
from datetime import date, datetime, timezone

import requests

import time

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
IMAGE_MODEL = "gemini-2.5-flash-image"
TEXT_MODEL = "gemini-2.5-flash"
IMAGE_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{IMAGE_MODEL}:generateContent"
TEXT_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{TEXT_MODEL}:generateContent"

# Page background colour — the image is generated on this exact colour so it
# sits on the page with no visible edge/box around the characters.
PAGE_BACKGROUND_HEX = "#F5EFE1"

# Fixed character description — repeated every single call.
# Consistency comes from restating this every time, not from the model remembering.
CHARACTER_DESCRIPTION = """
Two cartoon pigeons in a warm, flat, gently retro illustration style —
bold outlines, limited earthy-plus-one-accent-colour palette, simple
shading, a children's-book-illustration feel. No photorealism.

Barry: a slightly round, scruffy grey pigeon with a bright orange
scarf, always looks a bit pleased with himself.

Susan: a sleeker, iridescent green-and-purple-necked pigeon with
small round glasses, always looks like she's the one actually in
charge.

They are always shown together, same two characters, same art style.
CRITICAL: no background scenery of any kind — no ground, no sky, no
props, no shadows, no scenery elements. The entire area behind the
characters must be a single flat, completely uniform, unbroken solid
colour, exactly {bg_hex}, filling the whole frame edge to edge with
no gradient, no texture, no vignette. Just the two characters sitting
on flat colour, nothing else.
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


def build_prompt(theme: str) -> str:
    return f"{CHARACTER_DESCRIPTION}\n\nToday's scene: {theme}."


def _post_with_retry(url: str, payload: dict, max_attempts: int = 4) -> dict:
    """POST to the Gemini API, retrying on 429/5xx with backoff, and
    surfacing the actual error body on failure instead of a bare status
    code — that body is where Google says *why* (quota metric, retry
    delay, etc), which a generic raise_for_status() throws away."""
    last_error = None
    for attempt in range(1, max_attempts + 1):
        resp = requests.post(url, params={"key": GEMINI_API_KEY}, json=payload, timeout=120)
        if resp.status_code == 200:
            return resp.json()

        print(f"Attempt {attempt}/{max_attempts} failed: HTTP {resp.status_code}")
        print(f"Response body: {resp.text}")

        if resp.status_code == 429 or resp.status_code >= 500:
            last_error = resp
            wait = 2 ** attempt  # 2s, 4s, 8s, 16s
            print(f"Retrying in {wait}s...")
            time.sleep(wait)
            continue

        resp.raise_for_status()  # non-retryable (e.g. 400 bad request) — fail immediately

    raise RuntimeError(
        f"Gave up after {max_attempts} attempts. Last status: {last_error.status_code}. "
        f"Last body: {last_error.text}"
    )


def generate_image(prompt: str) -> bytes:
    data = _post_with_retry(IMAGE_API_URL, {"contents": [{"parts": [{"text": prompt}]}]})
    parts = data["candidates"][0]["content"]["parts"]
    for part in parts:
        if "inlineData" in part:
            return base64.b64decode(part["inlineData"]["data"])
    raise RuntimeError(f"No image returned. Response: {data}")


def generate_story(theme: str) -> str:
    prompt = f"{STORY_SYSTEM_PROMPT}\n\nToday's theme: {theme}"
    data = _post_with_retry(TEXT_API_URL, {"contents": [{"parts": [{"text": prompt}]}]})
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


def main():
    themes = load_themes("themes.json")
    theme = todays_theme(themes)
    prompt = build_prompt(theme)

    print(f"Theme: {theme}")
    image_bytes = generate_image(prompt)
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
