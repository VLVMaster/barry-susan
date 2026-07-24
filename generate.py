#!/usr/bin/env python3
"""
Generates today's Barry & Susan illustration + story, based on a real
"on this day in history" event pulled from Wikipedia.

Run daily by the GitHub Action in .github/workflows/daily-image.yml

- Image: Hugging Face Inference API (free tier, needs HF_TOKEN)
- Story: Groq (free tier, no credit card, needs GROQ_API_KEY)
- History: Wikimedia on-this-day feed (free, no key)
"""
import json
import os
import random
import sys
import time
from datetime import date, datetime, timezone

import requests

# Pollinations.ai's anonymous image endpoint bare-404'd, and its
# successor (gen.pollinations.ai/image with a pk_ App Key) turned out to
# require a funded balance, not actually free. Hugging Face's Inference
# API is genuinely free (no payment required) at the cost of needing an
# HF_TOKEN and occasional cold-start waits.
HF_IMAGE_MODEL = "black-forest-labs/FLUX.1-schnell"
HF_IMAGE_API_URL = f"https://api-inference.huggingface.co/models/{HF_IMAGE_MODEL}"
HF_TOKEN = os.environ.get("HF_TOKEN")
ONTHISDAY_URL = "https://api.wikimedia.org/feed/v1/wikipedia/en/onthisday/events/{month}/{day}"

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# Bias event selection toward war/conflict when possible, per preference —
# falls back to any event on days where nothing matches.
CONFLICT_KEYWORDS = [
    "invasion", "massacre", "revolution", "assassinat",
    "coup", "siege", "bombing", "genocide", "uprising", "rebellion",
    "military", "army", "troops", "conquest", "occupation", "riot",
]

# Fixed character description — repeated every single call.
# Consistency comes from restating this every time, not from the model remembering.
CHARACTER_BASE = """
Photorealistic photo, not illustration or painting. Two real pigeons,
Barry and Susan, each with a small handwritten name tag on a string
around its neck reading BARRY or SUSAN — that's how they're told
apart, since real pigeons otherwise look alike. Same two pigeons,
same tags, every time.
""".strip()

IMAGE_SYSTEM_NOTE = """
Barry and Susan are physically present in the scene, right in among
the real historical event, as if actually photographed there.
the real historical event, as if actually photographed there — not
off to the side, not a small background detail, genuinely part of
the shot. They may wear small real props/costume pieces evoking the
event or figures involved (a tiny hat, a scrap of period fabric) —
playful, not a full costume. The rest of the scene (people, setting,
architecture) is real and photographically plausible for the time
and place. No graphic violence, implied only. Keep any real recent
individual's likeness generic rather than exact.
""".strip()

FALLBACK_EVENT = {
    "year": None,
    "text": "just an ordinary day, nothing of note recorded",
}

LOCATION_RULE = """
Also add one more line, before REGRET/WINNER, in this exact format:
LOCATION: <the specific real place this event happened, as a
geocodable name — e.g. "Ypres, Belgium" or "Nocera, Italy" — as
precise as is actually known, city/town level where possible>
""".strip()

REGRET_WINNER_RULE = """
After the paragraph, add exactly two more lines in this exact format:
REGRET: <a percentage 0-100>|<one short deadpan line about the hindsight regret involved>
WINNER: <one short line answering "who really won this?">

REGRET: base the percentage and remark on how much regret the people
involved arguably should feel in hindsight, played completely
straight-faced — often the people at the time felt none, which is
itself the joke.

WINNER: almost never name an actual side, nation, or specific real
person as the winner — that's the boring, obvious answer. Instead
give a genuinely subversive, darkly funny answer about who or what
actually came out ahead once the human cost is weighed honestly — an
industry, an institution, a bureaucracy, an idea, the news cycle,
nobody at all. Never attribute real personal financial gain or
corruption to a specific real named individual — aim the joke at
systems and institutions, not at accusing a real person of a crime.
""".strip()

STORY_SYSTEM_PROMPT = """
You write a single paragraph (100-150 words) narrating a real
historical event, in the voice of Barry and Susan — two pigeons who
are right there in the middle of it, reacting to what's unfolding
around them. Write in a distinctly British, Blackadder-style deadpan
satirical voice: dry, straight-faced, understated, delivering
absurd or grim facts in the same flat tone as mundane ones, letting
the gap between tone and content do the comedic work. This is a
satirical, not a slapstick, register — closer to a dry aside at a
funeral than a pantomime. The historical facts underneath the wit
must stay completely accurate: real outcomes, real consequences,
real detail. No preamble, no title, just the paragraph, then the
three extra lines described below.

{location_rule}

{regret_winner_rule}
""".format(location_rule=LOCATION_RULE, regret_winner_rule=REGRET_WINNER_RULE).strip()


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
    year_bit = f" in {event['year']}" if event.get("year") else ""
    return f"{CHARACTER_BASE} {IMAGE_SYSTEM_NOTE} Real event{year_bit}: {event['text']}."


def _query_hf_image_with_retry(prompt: str, max_attempts: int = 4) -> bytes:
    """POST the prompt to the HF Inference API, retrying not just on bad
       HTTP status but also when what comes back doesn't actually look
       like a real photo — a 200 response with a JSON error body, or a
       suspiciously tiny file, would otherwise get silently written to
       disk as if it were fine. A 503 means the model is cold-starting,
       which HF reports with an estimated_time to wait before retrying."""
    if not HF_TOKEN:
        raise RuntimeError("HF_TOKEN not set")
    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    MIN_IMAGE_BYTES = 15_000
    last_reason = None
    for attempt in range(1, max_attempts + 1):
        resp = requests.post(
            HF_IMAGE_API_URL, headers=headers, json={"inputs": prompt}, timeout=120
        )
        content_type = resp.headers.get("Content-Type", "")

        if resp.status_code == 503:
            try:
                wait = float(resp.json().get("estimated_time", 20))
            except Exception:
                wait = 20
            last_reason = "model is loading (503)"
            print(f"Attempt {attempt}/{max_attempts}: {last_reason}, waiting {wait:.0f}s...")
            time.sleep(wait)
            continue
        elif resp.status_code != 200:
            last_reason = f"HTTP {resp.status_code}"
            print(f"Attempt {attempt}/{max_attempts} failed: {last_reason}")
            print(f"Response body: {resp.text[:500]}")
        elif not content_type.startswith("image/"):
            last_reason = f"non-image response (Content-Type: {content_type})"
            print(f"Attempt {attempt}/{max_attempts} failed: {last_reason}")
            print(f"Response body: {resp.text[:500]}")
        elif len(resp.content) < MIN_IMAGE_BYTES:
            last_reason = f"suspiciously small image ({len(resp.content)} bytes) — likely a placeholder/blocked-content response"
            print(f"Attempt {attempt}/{max_attempts} failed: {last_reason}")
        else:
            print(f"Got a valid image: {content_type}, {len(resp.content)} bytes")
            return resp.content

        wait = 5 * attempt
        print(f"Retrying in {wait}s...")
        time.sleep(wait)

    raise RuntimeError(f"Gave up after {max_attempts} attempts. Last reason: {last_reason}")


def _groq_post_with_retry(payload: dict, max_attempts: int = 4) -> dict:
    """POST to Groq's OpenAI-compatible chat completions endpoint,
       retrying on 429/5xx with backoff, surfacing the actual error body
       on failure rather than a bare status code."""
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    last_error = None
    for attempt in range(1, max_attempts + 1):
        resp = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=120)
        if resp.status_code == 200:
            return resp.json()

        print(f"Attempt {attempt}/{max_attempts} failed: HTTP {resp.status_code}")
        print(f"Response body: {resp.text[:500]}")

        if resp.status_code == 429 or resp.status_code >= 500:
            last_error = resp
            wait = 2 ** attempt
            print(f"Retrying in {wait}s...")
            time.sleep(wait)
            continue

        resp.raise_for_status()  # non-retryable — fail immediately

    raise RuntimeError(f"Gave up after {max_attempts} attempts. Last status: {last_error.status_code}")


def generate_image(prompt: str) -> bytes:
    MAX_PROMPT_CHARS = 1500
    if len(prompt) > MAX_PROMPT_CHARS:
        print(f"Prompt is {len(prompt)} chars, trimming to {MAX_PROMPT_CHARS}")
        prompt = prompt[:MAX_PROMPT_CHARS]
    return _query_hf_image_with_retry(prompt)


def generate_story(event: dict) -> dict:
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY not set")
    year_bit = f" (year: {event['year']})" if event.get("year") else ""
    prompt = f"{STORY_SYSTEM_PROMPT}\n\nReal event{year_bit}: {event['text']}"
    payload = {
        "model": GROQ_MODEL,
        "max_tokens": 500,
        "messages": [{"role": "user", "content": prompt}],
    }
    data = _groq_post_with_retry(payload)
    raw = data["choices"][0]["message"]["content"].strip()
    return parse_story_response(raw)


def parse_story_response(raw: str) -> dict:
    """Split the model's reply into the main paragraph plus LOCATION,
    REGRET, and WINNER lines. Falls back gracefully if the model didn't
    follow the format exactly — the paragraph still gets published
    either way."""
    paragraph_lines = []
    location_name = None
    regret_percent = None
    regret_line = None
    winner_line = None

    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("LOCATION:"):
            location_name = stripped.split(":", 1)[1].strip()
        elif stripped.upper().startswith("REGRET:"):
            rest = stripped.split(":", 1)[1].strip()
            if "|" in rest:
                pct, txt = rest.split("|", 1)
                regret_percent = pct.strip().rstrip("%")
                regret_line = txt.strip()
            else:
                regret_line = rest
        elif stripped.upper().startswith("WINNER:"):
            winner_line = stripped.split(":", 1)[1].strip()
        elif stripped:
            paragraph_lines.append(stripped)

    return {
        "story": " ".join(paragraph_lines).strip(),
        "location_name": location_name,
        "regret_percent": regret_percent,
        "regret_line": regret_line,
        "winner_line": winner_line,
    }


def geocode_location(place_name: str) -> dict | None:
    """Look up lat/lon for a place name via Nominatim (OpenStreetMap's
    free geocoder — no key, no billing). Best-effort: returns None on
    any failure rather than blocking the rest of the run, since the map
    is a nice-to-have, not core to the post."""
    if not place_name:
        return None
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": place_name, "format": "json", "limit": 1},
            headers={"User-Agent": "barry-and-susan-history-app/1.0"},
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json()
        if not results:
            print(f"Geocoding found nothing for: {place_name}")
            return None
        return {"lat": float(results[0]["lat"]), "lon": float(results[0]["lon"])}
    except Exception as e:
        print(f"Geocoding failed for '{place_name}': {e}")
        return None


def main():
    event = fetch_todays_event()
    print(f"Event: {event.get('year')} — {event['text']}")

    image_prompt = build_image_prompt(event)
    image_bytes = generate_image(image_prompt)

    story_data = None
    try:
        story_data = generate_story(event)
        print(f"Story: {story_data['story']}")
        print(f"Location: {story_data['location_name']}")
        print(f"Regret: {story_data['regret_percent']}% — {story_data['regret_line']}")
        print(f"Winner: {story_data['winner_line']}")
    except Exception as e:
        print(f"Story generation failed, publishing image without it: {e}")
        story_data = {
            "story": "Barry and Susan witnessed today's history, but the report went unwritten.",
            "location_name": None,
            "regret_percent": None,
            "regret_line": None,
            "winner_line": None,
        }

    coords = geocode_location(story_data["location_name"])
    if coords:
        print(f"Coordinates: {coords['lat']}, {coords['lon']}")

    os.makedirs("docs", exist_ok=True)
    with open("docs/today.png", "wb") as f:
        f.write(image_bytes)

    with open("docs/today.json", "w") as f:
        json.dump(
            {
                "date": date.today().isoformat(),
                "event_year": event.get("year"),
                "event_text": event["text"],
                "story": story_data["story"],
                "location_name": story_data["location_name"],
                "lat": coords["lat"] if coords else None,
                "lon": coords["lon"] if coords else None,
                "regret_percent": story_data["regret_percent"],
                "regret_line": story_data["regret_line"],
                "winner_line": story_data["winner_line"],
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            f,
            indent=2,
        )

    print("Wrote docs/today.png and docs/today.json")


if __name__ == "__main__":
    sys.exit(main())
