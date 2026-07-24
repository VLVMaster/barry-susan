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

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
MODEL = "gemini-2.5-flash-image"
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"

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

They are always shown together, same two characters, same art style,
on a plain uncluttered background so they read clearly at a glance
from across a room.
""".strip()

FALLBACK_THEME = "just an ordinary day, Barry and Susan pottering about doing nothing in particular"


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


def generate_image(prompt: str) -> bytes:
    resp = requests.post(
        API_URL,
        params={"key": GEMINI_API_KEY},
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    parts = data["candidates"][0]["content"]["parts"]
    for part in parts:
        if "inlineData" in part:
            return base64.b64decode(part["inlineData"]["data"])
    raise RuntimeError(f"No image returned. Response: {data}")


def main():
    themes = load_themes("themes.json")
    theme = todays_theme(themes)
    prompt = build_prompt(theme)

    print(f"Theme: {theme}")
    image_bytes = generate_image(prompt)

    os.makedirs("docs", exist_ok=True)
    with open("docs/today.png", "wb") as f:
        f.write(image_bytes)

    with open("docs/today.json", "w") as f:
        json.dump(
            {
                "date": date.today().isoformat(),
                "theme": theme,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            f,
            indent=2,
        )

    print("Wrote docs/today.png and docs/today.json")


if __name__ == "__main__":
    sys.exit(main())
