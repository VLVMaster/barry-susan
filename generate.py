#!/usr/bin/env python3
"""
Generates today's Barry & Susan illustration + story, based on a real
"on this day in history" event pulled from Wikipedia.

Barry and Susan are dressed in attire appropriate to the event's era
and appear as witnesses/onlookers to it. 

Run daily by the GitHub Action in .github/workflows/daily-image.yml

- Image: Cloudflare Workers AI (free tier, needs CF_API_TOKEN)
- Story: Groq (free tier, no credit card, needs GROQ_API_KEY)
- History: Wikimedia on-this-day feed (free, no key)
"""
import base64
import json
import os
import random
import sys
import time
from datetime import date, datetime, timezone

import requests

# Pollinations.ai went through several incompatible changes (anonymous
# path 404ing, then requiring a pk_ key with an unfunded $0 balance),
# then Hugging Face's free hf-inference providers stopped serving every
# text-to-image model we tried (400/410 across the board) — switched to
# Cloudflare Workers AI, which has a real free daily allowance (10,000
# neurons/day, one image is a few hundred) and a plain token-based REST
# API. Several candidate models are tried in order since Workers AI's
# model catalog has shifted before too.
CF_API_BASE = "https://api.cloudflare.com/client/v4"
CF_IMAGE_MODELS = [
    "@cf/black-forest-labs/flux-1-schnell",
    "@cf/stabilityai/stable-diffusion-xl-base-1.0",
    "@cf/bytedance/stable-diffusion-xl-lightning",
]
CF_API_TOKEN = os.environ.get("CF_API_TOKEN")
CF_ACCOUNT_ID = os.environ.get("CF_ACCOUNT_ID")
ONTHISDAY_URL = "https://api.wikimedia.org/feed/v1/wikipedia/en/onthisday/events/{month}/{day}"

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

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
Photorealistic photo, not illustration. Two real pigeons, each with
a small handwritten tag on a string around its neck: one reads
BARRY, one reads SUSAN. Same two pigeons, same tags, every time.
""".strip()

PHOTO_ERA_PRE_PHOTOGRAPHY = """
Photography didn't exist yet — style as a damaged, aged sepia
tintype photo, anachronistic but photographically real-looking.
""".strip()

PHOTO_ERA_EARLY_PHOTO = """
Style as a genuine black-and-white or sepia photo typical of this
era — period-correct grain and tone.
""".strip()

PHOTO_ERA_MODERN = """
Style as a real photo for the decade — black-and-white or faded film
for mid-1900s, natural full colour for recent decades.
""".strip()


def photo_era_note(event: dict) -> str:
    """Picks a photographic treatment matching the real history of
    photography — the joke does double duty as a consistency device."""
    year = event.get("year")
    if year is None:
        return PHOTO_ERA_MODERN
    if year < 1850:
        return PHOTO_ERA_PRE_PHOTOGRAPHY
    if year < 1950:
        return PHOTO_ERA_EARLY_PHOTO
    return PHOTO_ERA_MODERN


COMIC_DEVICES_RULE = """
No cartoon speech bubbles — this is a photo. Text only where
plausible in-scene (a sign, a placard, the name tags).
""".strip()

BACKGROUND_RULE = """
Real, physically plausible setting for the event, natural
photographic depth of field.
""".strip()

FALLBACK_EVENT = {
    "year": None,
    "text": "just an ordinary day, nothing of note recorded",
}

IMAGE_NOTE = """
Barry and Susan wear real props/costume pieces evoking the
historical figures or setting of this event (tiny hat, scrap of
period fabric, small prop), full costume. Other real
pigeons may appear similarly dressed as extras. Aim for specific real individuals where possible.
The pigeons should depict the scene, outfit and all. 
""".strip()

REGRET_WINNER_RULE = """
After the paragraph, add exactly two more lines in this exact format:
REGRET: <a percentage 0-100>|<one short witty line about the hindsight regret involved>
WINNER: <one short line answering "who really won this?">

For the REGRET line: base the percentage and remark on how much regret
the people involved arguably should feel in hindsight, played for dry
irony — often the actual historical figures felt none at the time,
which is itself the joke.

For the WINNER line, especially on any large-scale war or conflict:
almost never name an actual side or nation as the winner — that's the
boring, expected answer. Instead give a genuinely subversive, darkly
witty answer about who or what actually came out ahead when the human
cost is weighed honestly — an industry, an idea, a future generation
of historians, arms manufacturers, bureaucracy, nobody at all. Think
"the real winner was the war machine itself," not "France won." For
smaller-scale or modern tragedies involving real identifiable victims,
keep this line understated and somber rather than jokey — a short,
genuine line like "No one. There's no winner in this one." is exactly
right there; do not force a punchline onto real, recent grief.
""".strip()

HEADLINE_RULE = """
Start your reply with one line in this exact format:
HEADLINE: <a short, punchy, real headline for this specific event —
think proper newspaper or documentary title, evocative and specific
to what actually happened, not generic and not mentioning pigeons>
""".strip()

STORY_PROMPT = """
You write a paragraph (180-260 words) narrating a real historical
event as a dry, witty exchange between Barry and Susan — two pigeons
perched somewhere absurd and close to the action — who are playing
the actual historical figures involved, or narrating what those
figures are doing, whichever reads better. Write in a distinctly
British sense of humour: dry, deadpan, understated, wry
self-deprecation, irony over slapstick, the sort of thing that gets
a raised eyebrow rather than a belly laugh, like blackadder. Model your voice on this
example, which is the target quality bar: dialogue-driven, genuinely
funny through specific and surprising real detail rather than
slapstick or forced accents, dry asides, and enough actual substance
that a reader comes away understanding exactly what happened and why
it mattered — nothing vague, nothing hand-wavy.

{headline_rule}

EXAMPLE (match this style, not this event):
"Barry eyed the man below with the mirrored sunglasses and
ceremonial dagger. 'That's Colonel Gaddafi, Susan. 1977. Just
invented a whole system of government called the Jamahiriya —
Arabic, roughly, for "nobody's technically in charge, wink wink."
No president, no parliament, no parties. Just "the people," directly
ruling themselves. And who's stood at the podium in the safari suit
explaining how the people rule themselves? Him. Constantly. Even
written a little book about it — The Green Book — required reading,
rather like a cult pamphlet with better production values. Calls
himself "Brotherly Leader," no official title, purely coincidental
he controls the army, the oil money, and everyone's postbox.'
Susan ruffled her feathers. 'Builds a hospital with one hand,
disappears a critic with the other. Funds revolutionaries abroad
like it's a hobby. Frightfully generous with other people's
countries.' Barry took off. 'Man commits to a costume change,
though. Give him that.'"

For anything involving real people within living memory, large-scale
atrocities, or terrorism: keep the same dry, dialogue-driven clarity,
but pull the humour right back and let the facts carry the weight
instead — Barry and Susan stay commentating bystanders, never
identified as or standing in for any real specific person involved.
Only use a regional voice or accent where it genuinely fits and
adds something — never force a phonetic accent as decoration, it
should read as clean, sharp prose above all else. The historical
facts must be completely accurate and specific: real names, real
terms, real numbers, real outcomes. No preamble beyond the headline
line, then the paragraph, then the two extra lines described below.

{regret_winner_rule}
""".format(regret_winner_rule=REGRET_WINNER_RULE, headline_rule=HEADLINE_RULE).strip()


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
    era_note = photo_era_note(event)
    return (
        f"{CHARACTER_BASE} {IMAGE_NOTE} {era_note} {COMIC_DEVICES_RULE} {BACKGROUND_RULE} "
        f"Today's real historical event,{year_bit} to reference for "
        f"costume and setting only: {event['text']}."
    )


def _cf_account_id() -> str:
    """Return the Cloudflare account ID to run models against. Uses
    CF_ACCOUNT_ID if set, otherwise looks up the token's first
    accessible account (a scoped API token normally only has one)."""
    if CF_ACCOUNT_ID:
        return CF_ACCOUNT_ID
    headers = {"Authorization": f"Bearer {CF_API_TOKEN}"}
    resp = requests.get(f"{CF_API_BASE}/accounts", headers=headers, timeout=30)
    resp.raise_for_status()
    accounts = resp.json().get("result", [])
    if not accounts:
        raise RuntimeError("CF_API_TOKEN has no accessible Cloudflare accounts")
    return accounts[0]["id"]


def _query_cf_image(prompt: str, max_attempts: int = 3) -> bytes:
    """POST the prompt to Cloudflare Workers AI, trying each candidate
    model in turn. A 400/404 naming the model as unknown/unauthorized
    means that model isn't available on this account — move on to the
    next one. A 429 means rate-limited, worth backing off and retrying
    the same model. Workers AI responses are either the raw image
    bytes (Content-Type: image/*) or a JSON envelope with a base64
    image string, depending on the model."""
    if not CF_API_TOKEN:
        raise RuntimeError("CF_API_TOKEN not set")
    account_id = _cf_account_id()
    headers = {"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "application/json"}
    last_reason = None

    for model in CF_IMAGE_MODELS:
        url = f"{CF_API_BASE}/accounts/{account_id}/ai/run/{model}"
        for attempt in range(1, max_attempts + 1):
            resp = requests.post(url, headers=headers, json={"prompt": prompt}, timeout=120)
            content_type = resp.headers.get("Content-Type", "")

            if resp.status_code in (400, 404):
                last_reason = f"{model}: HTTP {resp.status_code} — {resp.text[:300]}"
                print(f"{last_reason} — trying next model")
                break
            elif resp.status_code == 429:
                wait = 5 * attempt
                print(f"{model}: rate-limited (429), waiting {wait}s...")
                time.sleep(wait)
                continue
            elif resp.status_code != 200:
                last_reason = f"{model}: HTTP {resp.status_code}"
                print(f"Attempt {attempt}/{max_attempts} failed: {last_reason}")
                print(f"Response body: {resp.text[:500]}")
            elif content_type.startswith("image/"):
                print(f"Got a valid image from {model}: {content_type}, {len(resp.content)} bytes")
                return resp.content
            else:
                try:
                    data = resp.json()
                    b64 = data["result"]["image"]
                    if "," in b64[:40]:  # strip a data:image/...;base64, prefix if present
                        b64 = b64.split(",", 1)[1]
                    image_bytes = base64.b64decode(b64)
                    print(f"Got a valid image from {model}: decoded {len(image_bytes)} bytes")
                    return image_bytes
                except Exception as e:
                    last_reason = f"{model}: could not parse JSON image response: {e}"
                    print(f"Attempt {attempt}/{max_attempts} failed: {last_reason}")
                    print(f"Response body: {resp.text[:500]}")

            wait = 5 * attempt
            print(f"Retrying in {wait}s...")
            time.sleep(wait)

    raise RuntimeError(f"Gave up on all Cloudflare Workers AI models. Last reason: {last_reason}")


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
    return _query_cf_image(prompt)


def generate_story(event: dict) -> dict:
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY not set")
    year_bit = f" (year: {event['year']})" if event.get("year") else ""
    prompt = f"{STORY_PROMPT}\n\nReal event{year_bit}: {event['text']}"
    payload = {
        "model": GROQ_MODEL,
        "max_tokens": 600,
        "messages": [{"role": "user", "content": prompt}],
    }
    data = _groq_post_with_retry(payload)
    raw = data["choices"][0]["message"]["content"].strip()
    return parse_story_response(raw)


def parse_story_response(raw: str) -> dict:
    """Split the model's reply into headline, main paragraph, REGRET,
    and WINNER lines. Falls back gracefully if the model didn't follow
    the format exactly — the paragraph still gets published either way."""
    headline = None
    paragraph_lines = []
    regret_percent = None
    regret_line = None
    winner_line = None

    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("HEADLINE:"):
            headline = stripped.split(":", 1)[1].strip().strip('"')
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
        "headline": headline,
        "story": " ".join(paragraph_lines).strip(),
        "regret_percent": regret_percent,
        "regret_line": regret_line,
        "winner_line": winner_line,
    }


def main():
    event = fetch_todays_event()
    print(f"Event: {event.get('year')} — {event['text']}")

    image_prompt = build_image_prompt(event)
    image_bytes = generate_image(image_prompt)

    story_data = None
    try:
        story_data = generate_story(event)
        print(f"Headline: {story_data['headline']}")
        print(f"Story: {story_data['story']}")
        print(f"Regret: {story_data['regret_percent']}% — {story_data['regret_line']}")
        print(f"Winner: {story_data['winner_line']}")
    except Exception as e:
        print(f"Story generation failed, publishing image without it: {e}")
        story_data = {
            "headline": event.get("text", "History, unwritten today")[:80],
            "story": "Barry and Susan witnessed today's history, but the report went unwritten.",
            "regret_percent": None,
            "regret_line": None,
            "winner_line": None,
        }

    os.makedirs("docs", exist_ok=True)
    with open("docs/today.png", "wb") as f:
        f.write(image_bytes)

    with open("docs/today.json", "w") as f:
        json.dump(
            {
                "date": date.today().isoformat(),
                "event_year": event.get("year"),
                "event_text": event["text"],
                "headline": story_data["headline"],
                "story": story_data["story"],
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
