# Price & Size Tracker

Checks a list of product pages on a schedule, and emails you when:
- a **price drops**, or
- a **specific size** you're watching becomes available.

Runs for free on GitHub Actions (no server needed). A small dashboard shows
the current status of everything you're tracking.

## 1. Get a Gmail "app password"

You can't use your normal Gmail password for this — Google requires an
app-specific password for programs like this one.

1. Turn on 2-Step Verification on your Google account, if it isn't already:
   https://myaccount.google.com/security
2. Go to https://myaccount.google.com/apppasswords
3. Create an app password (name it anything, e.g. "price-tracker")
4. Copy the 16-character password it gives you — you'll need it in step 3 below.

## 2. Create the GitHub repo

1. Create a new **private** repository on GitHub (private just so your
   tracked items/prices aren't public).
2. Upload all the files in this folder to the repo, keeping the folder
   structure (`.github/workflows/check.yml` must stay at that exact path).

## 3. Add your secrets

In the repo: **Settings → Secrets and variables → Actions → New repository secret**

Add these three:
| Name | Value |
|---|---|
| `GMAIL_USER` | your Gmail address |
| `GMAIL_APP_PASSWORD` | the 16-character app password from step 1 |
| `NOTIFY_EMAIL` | the email address you want alerts sent to (can be the same as GMAIL_USER) |

## 4. Turn on GitHub Pages (for the dashboard)

**Settings → Pages** → Source: "Deploy from a branch" → Branch: `main`,
folder: `/docs` → Save.

GitHub will give you a URL like `https://yourusername.github.io/your-repo/`.
That's your dashboard. It updates every time the checker runs.

## 5. Add the items you want to track

Edit `items.json`. Each entry:

```json
{
  "id": "any-unique-short-id",
  "name": "Human-readable name",
  "url": "https://the-product-page-url",
  "track_price": true,
  "track_sizes": ["S", "M"]
}
```

- `track_price: true` → alerts you when the price goes down.
- `track_sizes` → list of exact size labels to watch (leave `[]` if you
  don't care about sizes for this item). The label has to match what's on
  the page (e.g. `"S"`, `"Medium"`, `"8"`) — check the dashboard after the
  first run to see what labels the script actually found, and adjust if
  needed.

The dress you linked is already in there as an example — just add
`track_sizes` if you want a specific size watched too.

## 6. Run it

- It runs automatically 3x/day (00:00, 08:00, 16:00 UTC) once merged to `main`.
  Adjust the `cron` line in `.github/workflows/check.yml` if you want a
  different schedule.
- To test immediately: **Actions tab → "Check prices and sizes" → Run workflow**.
- Check the run's logs if something looks wrong — the script prints errors
  per item rather than failing the whole run.

## Notes & limitations

- **Failures are retried extensively before being reported.** Each check
  attempts up to 4 times per item, rotating browser fingerprints, waiting
  longer, and specifically detecting CAPTCHA/bot-block pages so it can back
  off and retry rather than give up on the first sign of trouble. Only if
  every attempt fails is it logged.
- **You won't be emailed about failures immediately.** They're logged to
  `failures.json`. Once a week (Saturday night, roughly 8pm Pacific — see
  the cron comment in `weekly-digest.yml` if you want to change the time),
  a separate workflow emails you everything that failed that week, tagged
  `[Claude: check failing update]`, then clears the log.
- **Price drops and size availability still email you right away** —
  nothing about those changed. Only the "site is broken" case is now
  batched weekly instead of per-run.

## When something's still broken after retries: how to get it fixed

There's no automatic loop where I fix and redeploy code on my own — I only
act when you bring something to me in a conversation. Here's the fastest
path when the Saturday digest email shows a failure:

1. **Open the digest email.** It lists each failed item, the URL, and the
   reason (e.g. "the site returned a bot-check/CAPTCHA page" or "page
   loaded but no price could be found").
2. **Come back to a Claude chat** (this one or a new one at claude.ai) and
   paste in the failure line(s) from the email, e.g.:
   > "This item is failing: Gap Dress (pid 898568012), reason: page loaded
   > but no price could be found. Here's the URL: [paste]. Can you fix
   > checker.py?"
3. I'll diagnose it — if it's a selector that changed, I'll update
   `checker.py`; if it's a hard bot-block, I'll tell you honestly if it's
   not fixable and suggest alternatives (e.g. a lower check frequency, or
   dropping that one site).
4. **Apply the fix**: go to your GitHub repo → open `checker.py` → click
   the pencil (edit) icon → select all, delete, paste in what I gave you →
   commit directly to `main`.
5. **Test it immediately** instead of waiting for the next scheduled run:
   repo → **Actions** tab → "Check prices and sizes" → **Run workflow**.

If you'd rather not hand-copy code back and forth, connecting a GitHub
integration to Claude (if you have one available) would let me read and
edit the repo file directly in a future conversation — worth asking me
about if you want to explore that.
- **Size/price selectors are best-effort.** Retail sites change their HTML
  often. If a specific item stops reporting sizes correctly, open the page,
  right-click a size button → Inspect, and I can help you tune
  `extract_available_sizes()` in `checker.py` for that site.
- All data (prices, last-checked times) lives in `data.json` /
  `docs/data.json` in your own repo — nothing goes through a third party.
