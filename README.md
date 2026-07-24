# Barry & Susan

A daily cartoon of two pigeons, themed to whatever day it is. GitHub
Actions generates the image once a day and commits it; GitHub Pages
serves it; your Pi just shows it full-screen in a browser.

## One-time setup

1. **Create a repo** on GitHub and push these files to it.

2. **Get a Gemini API key** — https://aistudio.google.com/apikey

3. **Add it as a repo secret**
   Repo → Settings → Secrets and variables → Actions → New repository
   secret → name it `GEMINI_API_KEY`, paste the key.

4. **Enable GitHub Pages**
   Repo → Settings → Pages → Source: "Deploy from a branch" →
   Branch: `main`, folder: `/docs` → Save.
   Your page will be live at `https://<username>.github.io/<repo>/`.

5. **Run it once manually** to check it works, rather than waiting for
   the 6am cron:
   Repo → Actions tab → "Generate today's Barry & Susan" → Run workflow.
   Check `docs/today.png` gets committed and the Pages URL shows it.

6. **Edit `themes.json`** to add your own dates — repeatable annual
   dates in `MM-DD` format. Any date not in the list falls back to an
   "ordinary day" scene (edit `FALLBACK_THEME` in `generate.py` if you
   want that to be something else).

## Pi setup

Raspberry Pi OS with Desktop, then autostart Chromium in kiosk mode
pointed at your Pages URL:

```
chromium-browser --kiosk --app=https://<username>.github.io/<repo>/
```

Add that command to `~/.config/lxsession/LXDE-pi/autostart` (or your
desktop environment's equivalent) so it launches on boot.

## Notes

- Only one image exists at a time (`docs/today.png` gets overwritten
  daily) — there's no history/archive built in. Easy to add later if
  you want a "past days" gallery — just have the workflow copy to a
  dated filename as well as overwriting `today.png`.
- The character description is repeated in every prompt (see
  `CHARACTER_DESCRIPTION` in `generate.py`) — that's what keeps Barry
  and Susan looking like themselves day to day rather than drifting.
  Tweak that block to change their look; it applies retroactively to
  every future generation.
