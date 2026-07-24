#!/usr/bin/env python3
"""
Generates today's Barry & Susan illustration + story, based on a real
"on this day in history" event pulled from Wikipedia.

Barry and Susan are dressed in attire appropriate to the event's era
and appear as witnesses/onlookers to it. They are never depicted as,
or made to resemble, any specific real historical individual — the
event and its details are real and accurate; the pigeons are not.

Run daily by the GitHub Action in .github/workflows/daily-image.yml
Uses Pollinations.ai for generation (free, no key) and Wikimedia's
on-this-day feed for history (free, no key).
"""
import json
import os
import random
import sys
import time
import urllib.parse
from datetime import date, datetime, timezone

import requests

IMAGE_BASE_URL = "https://image.pollinations.ai/prompt"
TEXT_BASE_URL = "https://gen.pollinations.ai/text"
ONTHISDAY_URL = "https://api.wikimedia.org/feed/v1/wikipedia/en/onthisday/events/{month}/{day}"

# Page background colour — the image is generated on this exact colour so it
# sits on the page with no visible edge/box around the characters.
PAGE_BACKGROUND_HEX = "#F5EFE1"

# Bias event selection toward war/conflict when possible, per preference —
# falls back to any event on days where nothing matches.
CONFLICT_KEYWORDS = [
    "war", "battle", "invasion", "massacre", "revolution", "assassinat",
    "coup", "siege", "bombing", "genocide", "uprising", "rebellion",
    "military", "army", "troops", "conquest", "occupation", "riot",
]

# Fixed character description — repeated every single call.
# Consistency comes from restating this every time, not from the model remembering.
CHARACTER_BASE = """
Two cartoon pigeons in a warm, flat, gently retro illustration style,
bold outlines, limited earthy-plus-one-accent-colour palette, simple
shading, a children's-book-illustration feel, but like theyve suffered at the historical event in question. 
Barry: a slightly round, scruffy grey pigeon, always looks a bit
pleased with himself and wears red adidas tracksuit bottoms.
Susan: a sleeker, ginger haired iridescent green-and-purple-
necked pigeon with small round glasses, always looks like she's the
one actually in charge. Always shown together, same two characters,
same underlying style. 
""".strip()

BACKGROUND_RULE = """
No scenery beyond what's specified below, no extra props unless relevant to the event. The area
behind the characters is a single flat, completely uniform, unbroken
solid colour, exactly {bg_hex}, filling the whole frame edge to edge,
no gradient, no texture.
""".format(bg_hex=PAGE_BACKGROUND_HEX).strip()

FALLBACK_EVENT = {
    "year": None,
    "text": "just an ordinary day, nothing of note recorded",
}

STORY_SYSTEM_PROMPT = """
You write a single short paragraph (70-110 words) about a real
historical event, narrated as if Barry and Susan — two pigeons — were
small, incidental witnesses to it. The historical facts you state
must be accurate to the real event given below: real dates, real
outcomes, real consequences. Barry and Susan only observe and narrate from their ridiculous perspective. 
The tone should be absurd and factual to relfect the events. No preamble, no title, just the
paragraph itself. 
""".strip()

IMAGE_SYSTEM_NOTE = """
Depict Barry and Susan as onlookers present at the scene, dressed in
clothing typical of the event's time and place. If possible, depict them
as, or give them the likeness of, the specific real historical
individual(s) — they remain the same two pigeon characters, but in costume if possible. For example, if they are narrative the iraq war, they should be in relevant tactical gear.
""".strip()


def fetch_todays_event() -> dict:
    """Pull today's on-this-day events from Wikimedia, prefer a
    war/conflict-related one, fall back to any event, then to a
    generic placeholder if the feed is unreachable."""
    today = date.today()
    url = ONTHISDAY_URL.format(month=f"{today.month:02d}", day=f"{today.day:02d}")
    try:
        resp = requests.get(url, headers={"User-Agent": "barry-and-susan/1.0"}, timeout=30)
        resp.raise_for_status()
        events = resp.json().get("events", [])
    except Exception as e:
        print(f"Could not fetch on-this-day events, using fallback: {e}")
        return FALLBACK_EVENT

    if not events:
        return FALLBACK_EVENT

    conflict_events = [
        e for e in events
        if any(kw in e.get("text", "").lower() for kw in CONFLICT_KEYWORDS)
    ]
    pool = conflict_events if conflict_events else events
    return random.choice(pool)


def build_image_prompt(event: dict) -> str:
    year_bit = f" set in the year {event['year']}," if event.get("year") else ""
    return (
        f"{CHARACTER_BASE} {IMAGE_SYSTEM_NOTE} {BACKGROUND_RULE} "
        f"Today's real historical event,{year_bit} to reference for "
        f"costume and setting only: {event['text']}."
    )


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
    url = f"{IMAGE_BASE_URL}/{encoded}?width=1024&height=768&nologo=true"
    resp = _get_with_retry(url)
    return resp.content


def generate_story(event: dict) -> str:
    year_bit = f" (year: {event['year']})" if event.get("year") else ""
    prompt = f"{STORY_SYSTEM_PROMPT}\n\nReal event{year_bit}: {event['text']}"
    encoded = urllib.parse.quote(prompt)
    url = f"{TEXT_BASE_URL}/{encoded}"
    resp = _get_with_retry(url)
    return resp.text.strip()


def main():
    event = fetch_todays_event()
    print(f"Event: {event.get('year')} — {event['text']}")

    image_prompt = build_image_prompt(event)
    image_bytes = generate_image(image_prompt)

    # Small pause to respect Pollinations' anonymous rate limit between
    # the image call and the text call.
    time.sleep(15)

    story = None
    try:
        story = generate_story(event)
        print(f"Story: {story}")
    except Exception as e:
        print(f"Story generation failed, publishing image without it: {e}")
        story = "Barry and Susan witnessed today's history, but the report went unwritten."

    os.makedirs("docs", exist_ok=True)
    with open("docs/today.png", "wb") as f:
        f.write(image_bytes)

    with open("docs/today.json", "w") as f:
        json.dump(
            {
                "date": date.today().isoformat(),
                "event_year": event.get("year"),
                "event_text": event["text"],
                "story": story,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            f,
            indent=2,
        )

    print("Wrote docs/today.png and docs/today.json")


if __name__ == "__main__":
    sys.exit(main())
