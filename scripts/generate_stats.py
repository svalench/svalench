#!/usr/bin/env python3
"""
Generate self-hosted GitHub profile stats cards (SVG).

Cards are rendered from the GitHub REST/GraphQL API and committed to the
repository by a GitHub Action, so the profile never depends on third-party
badge services (github-readme-stats / github-profile-summary-cards public
instances are frequently rate limited or paused).

Usage:
    GH_TOKEN=... GITHUB_LOGIN=svalench python scripts/generate_stats.py

Outputs (relative to the repository root):
    stats/contributions.svg  — contribution heatmap for the last year
    stats/stats.svg         — stars / commits / PRs / issues / followers
    stats/languages.svg     — most used languages
"""

import json
import math
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

LOGIN = os.environ.get("GITHUB_LOGIN", "svalench")
OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "stats"
)

# ---- tokyonight palette -----------------------------------------------------
C_BG = "#1a1b27"
C_CARD = "#16161e"
C_BORDER = "#1f2233"
C_TITLE = "#70a5cd"
C_TEXT = "#a9b1d6"
C_MUTED = "#8b93b8"
C_ACCENTS = ["#7aa2f7", "#9ece6a", "#e0af68", "#f7768e", "#bb9af7", "#7dcfff"]
HEAT_LEVELS = ["#16161e", "#2f334d", "#3d59a1", "#7aa2f7", "#b4f9f8"]
FONT = "'Segoe UI', Ubuntu, Sans-Serif"


def gh(*args):
    """Run `gh api` and return parsed JSON."""
    proc = subprocess.run(
        ["gh", "api", *args],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        sys.exit(f"gh api {' '.join(args)} failed:\n{proc.stderr}")
    return json.loads(proc.stdout) if proc.stdout.strip() else {}


def esc(s):
    s = str(s)
    return (s.replace(chr(38), chr(38) + "amp;")
             .replace(chr(60), chr(38) + "lt;")
             .replace(chr(62), chr(38) + "gt;")
             .replace(chr(34), chr(38) + "quot;"))


def fmt(n):
    return f"{n:,}"


# ---- data -------------------------------------------------------------------
def fetch_user():
    return gh(f"users/{LOGIN}")


def fetch_repos():
    repos, page = [], 1
    while True:
        chunk = gh(
            f"users/{LOGIN}/repos", "-X", "GET",
            "-f", "per_page=100", "-f", f"page={page}",
            "-F", "sort=pushed",
        )
        if not chunk:
            break
        repos.extend(chunk)
        if len(chunk) < 100:
            break
        page += 1
    return repos


def fetch_languages(repos, limit=40):
    """Aggregate language bytes across the user's non-fork repos."""
    totals = {}
    for repo in [r for r in repos if not r.get("fork")][:limit]:
        try:
            langs = gh(f"repos/{repo['full_name']}/languages")
        except SystemExit:
            continue
        for lang, size in langs.items():
            totals[lang] = totals.get(lang, 0) + size
    return sorted(totals.items(), key=lambda kv: -kv[1])[:6]


def fetch_search_count(kind):
    res = gh(
        "search/issues", "-X", "GET",
        "-f", f"q=author:{LOGIN} type:{kind}",
    )
    return res.get("total_count", 0)


def fetch_contributions():
    now = datetime.now(timezone.utc)
    frm = (now - timedelta(days=364)).isoformat()
    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          contributionCalendar {
            totalContributions
            weeks { contributionDays { date contributionCount } }
          }
        }
      }
    }"""
    payload = gh(
        "graphql", "-f", f"query={query}",
        "-f", f"login={LOGIN}", "-f", f"from={frm}", "-f", f"to={now.isoformat()}",
    )
    return payload["data"]["user"]["contributionsCollection"]["contributionCalendar"]


# ---- rendering ---------------------------------------------------------------
def card(w, h, body):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}">\n'
        f'<style>text {{ font-family: {FONT}; }}</style>\n'
        f'<rect width="{w}" height="{h - 1}" rx="6" fill="{C_BG}" '
        f'stroke="{C_BORDER}"/>\n{body}</svg>\n'
    )


def render_contributions(total, weeks):
    W, H = 640, 178
    ox, oy = 16, 44  # grid origin
    cell, gap = 10, 2
    bw = W - ox * 2  # border-ish padding
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    b = []
    b.append(
        f'<text x="16" y="24" fill="{C_TITLE}" font-size="15" '
        f'font-weight="600">{esc(LOGIN)}&#8217;s Contributions</text>'
    )
    b.append(
        f'<text x="{W - 16}" y="24" fill="{C_TEXT}" font-size="12" '
        f'text-anchor="end">{fmt(total)} contributions in the last year</text>'
    )

    # month labels above the grid
    last_month = -1
    for col, week in enumerate(weeks):
        if not week["contributionDays"]:
            continue
        first = datetime.strptime(week["contributionDays"][0]["date"], "%Y-%m-%d")
        if first.day <= 7 and first.month != last_month:
            last_month = first.month
            b.append(
                f'<text x="{ox + col * (cell + gap)}" y="{oy - 6}" '
                f'fill="{C_MUTED}" font-size="10">{months[first.month - 1]}</text>'
            )

    def level(n):
        if n == 0:
            return 0
        if n < 4:
            return 1
        if n < 8:
            return 2
        if n < 13:
            return 3
        return 4

    for col, week in enumerate(weeks):
        for day in week["contributionDays"]:
            d = datetime.strptime(day["date"], "%Y-%m-%d")
            row = (d.weekday() + 1) % 7  # Sunday first
            x = ox + col * (cell + gap)
            y = oy + row * (cell + gap)
            fill = HEAT_LEVELS[level(day["contributionCount"])]
            b.append(
                f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" '
                f'rx="2" fill="{fill}"><title>{day["date"]}: '
                f'{day["contributionCount"]} contributions</title></rect>'
            )

    # legend
    lx = W - 16 - (5 * 12 + 70)
    b.append(
        f'<text x="{lx - 8}" y="{H - 14}" fill="{C_MUTED}" font-size="10" '
        f'text-anchor="end">Less</text>'
    )
    for i, color in enumerate(HEAT_LEVELS):
        b.append(
            f'<rect x="{lx + i * 12}" y="{H - 24}" width="10" height="10" '
            f'rx="2" fill="{color}"/>'
        )
    b.append(
        f'<text x="{lx + 5 * 12 + 8}" y="{H - 14}" fill="{C_MUTED}" '
        f'font-size="10">More</text>'
    )
    return card(W, H, "\n".join(b) + "\n")


def render_stats(stars, commits, prs, issues, followers, repos):
    W, H = 495, 195
    icons = {
        "star": '<path d="M6 0.3 L7.4 4.1 L11.5 4.3 L8.3 6.9 L9.4 10.9 L6 8.7 '
                'L2.6 10.9 L3.7 6.9 L0.5 4.3 L4.6 4.1 Z"/>',
        "bolt": '<path d="M7 0 L1.2 7 H4.9 L4.1 12 L10.9 4.7 H6.5 Z"/>',
        "pr": '<circle cx="3.2" cy="3.4" r="2.1" fill="none" stroke="{c}" '
              'stroke-width="1.4"/><circle cx="3.2" cy="8.6" r="2.1" '
              'fill="none" stroke="{c}" stroke-width="1.4"/><circle cx="9.3" '
              'cy="8.6" r="2.1" fill="none" stroke="{c}" '
              'stroke-width="1.4"/><path d="M3.2 5.5 V6.5 M5.3 8.6 H7.2" '
              'stroke="{c}" stroke-width="1.4"/>',
        "issue": '<circle cx="6" cy="6" r="5" fill="none" stroke="{c}" '
                 'stroke-width="1.4"/><circle cx="6" cy="6" r="1.6"/>',
        "people": '<circle cx="4.4" cy="3.1" r="2.3"/><path d="M0.7 11.9 '
                  'C0.7 9.3 2.3 7.6 4.4 7.6 C6.5 7.6 8.1 9.3 8.1 11.9 Z"/>',
        "box": '<rect x="1" y="2" width="10" height="8.5" rx="1.5" fill="none" '
               'stroke="{c}" stroke-width="1.4"/><path d="M1 5.4 H11" '
               'stroke="{c}" stroke-width="1.4"/>',
    }
    rows = [
        (icons["star"], "Total Stars", fmt(stars), C_ACCENTS[4]),
        (icons["bolt"], "Commits (last year)", fmt(commits), C_ACCENTS[0]),
        (icons["pr"], "Total PRs", fmt(prs), C_ACCENTS[1]),
        (icons["issue"], "Total Issues", fmt(issues), C_ACCENTS[2]),
        (icons["people"], "Followers", fmt(followers), C_ACCENTS[5]),
        (icons["box"], "Public Repos", fmt(repos), C_ACCENTS[3]),
    ]
    b = [
        f'<text x="25" y="36" fill="{C_TITLE}" font-size="16" '
        f'font-weight="600">{esc(LOGIN)}&#8217;s GitHub Stats</text>'
    ]
    y = 66
    for icon, label, value, color in rows:
        b.append(
            f'<g transform="translate(25, {y - 11.5})" fill="{color}">'
            f'{icon.replace("{c}", color)}</g>'
        )
        b.append(
            f'<text x="50" y="{y}" fill="{C_TEXT}" font-size="13">{label}</text>'
        )
        b.append(
            f'<text x="{W - 25}" y="{y}" fill="{C_TEXT}" font-size="13" '
            f'font-weight="600" text-anchor="end">{value}</text>'
        )
        y += 22
    return card(W, H, "\n".join(b) + "\n")


def render_languages(langs):
    W = 495
    H = 66 + len(langs) * 30 + 10
    b = [
        f'<text x="25" y="36" fill="{C_TITLE}" font-size="16" '
        f'font-weight="600">Most Used Languages</text>'
    ]
    total = sum(v for _, v in langs) or 1
    bar_w = W - 50
    y = 58
    for i, (name, size) in enumerate(langs):
        pct = size / total * 100
        color = C_ACCENTS[i % len(C_ACCENTS)]
        b.append(
            f'<text x="25" y="{y}" fill="{C_TEXT}" font-size="12.5">{esc(name)}</text>'
        )
        b.append(
            f'<text x="{W - 25}" y="{y}" fill="{C_TEXT}" font-size="12.5" '
            f'text-anchor="end">{pct:.1f}%</text>'
        )
        b.append(
            f'<rect x="25" y="{y + 6}" width="{bar_w}" height="8" rx="4" '
            f'fill="{C_CARD}"/>'
        )
        b.append(
            f'<rect x="25" y="{y + 6}" width="{max(4, bar_w * pct / 100):.1f}" '
            f'height="8" rx="4" fill="{color}"/>'
        )
        y += 30
    return card(W, H, "\n".join(b) + "\n")


# ---- main --------------------------------------------------------------------
def main():
    print(f"Collecting data for {LOGIN} ...")
    user = fetch_user()
    repos = fetch_repos()
    stars = sum(r["stargazers_count"] for r in repos if not r.get("fork"))
    langs = fetch_languages(repos)
    prs = fetch_search_count("pr")
    issues = fetch_search_count("issue")
    contrib = fetch_contributions()

    os.makedirs(OUT_DIR, exist_ok=True)
    outputs = {
        "contributions.svg": render_contributions(
            contrib["totalContributions"], contrib["weeks"]
        ),
        "stats.svg": render_stats(
            stars,
            contrib["totalContributions"],
            prs,
            issues,
            user["followers"],
            user["public_repos"],
        ),
        "languages.svg": render_languages(langs),
    }
    for name, content in outputs.items():
        path = os.path.join(OUT_DIR, name)
        with open(path, "w") as f:
            f.write(content)
        print(f"wrote {path} ({len(content)} bytes)")


if __name__ == "__main__":
    main()
