"""
Runs once a week (Saturday night). Sends one email summarizing every item
that failed to check during the past week — after checker.py already
retried each one multiple times with different strategies — then clears
the log so next week starts fresh.

If nothing failed all week, this sends nothing.
"""

from checker import load_json, save_json, send_email

FAILURES_FILE = "failures.json"


def main():
    failures = load_json(FAILURES_FILE, [])
    if not failures:
        print("No failures logged this week — nothing to send.")
        return

    lines = [
        f"{f['when']} — {f['name']}\nReason: {f['reason']}\n{f['url']}"
        for f in failures
    ]
    body = (
        f"{len(failures)} check(s) failed this week after retrying each one "
        f"multiple times with different strategies:\n\n" + "\n\n".join(lines)
    )
    send_email("[Claude: check failing update]", body)
    save_json(FAILURES_FILE, [])


if __name__ == "__main__":
    main()
