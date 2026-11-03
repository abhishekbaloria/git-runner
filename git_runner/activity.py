"""Collect GitHub data and turn it into a small, deterministic runner state."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


USERNAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?\Z")
MODES = ("rest", "walk", "run")


@dataclass(frozen=True)
class Day:
    date: str
    count: int


@dataclass(frozen=True)
class Language:
    name: str
    size: int
    color: str


@dataclass(frozen=True)
class Snapshot:
    username: str
    through: str
    days: tuple[Day, ...]
    languages: tuple[Language, ...]
    demo: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Snapshot":
        username = data["username"]
        if not USERNAME.fullmatch(username):
            raise ValueError("The snapshot has an invalid GitHub username.")
        through = date.fromisoformat(data["through"])
        start = through - timedelta(days=364)
        counts: dict[date, int] = {}
        for item in data["days"]:
            day = date.fromisoformat(item["date"])
            count = item["count"]
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ValueError("Contribution counts must be nonnegative integers.")
            if day in counts:
                raise ValueError("A contribution date occurs more than once.")
            if start <= day <= through:
                counts[day] = count
        days = tuple(
            Day((start + timedelta(days=i)).isoformat(), counts.get(start + timedelta(days=i), 0))
            for i in range(365)
        )
        languages = []
        for item in data.get("languages", []):
            color = item.get("color") or "#76dec5"
            if not re.fullmatch(r"#[A-Fa-f0-9]{6}", color):
                raise ValueError("Language colours must be six-digit hex colours.")
            size = item["size"]
            if isinstance(size, bool) or not isinstance(size, int) or size < 0:
                raise ValueError("Language sizes must be nonnegative integers.")
            languages.append(Language(str(item["name"]), size, color))
        return cls(username, through.isoformat(), days,
                   tuple(sorted(languages, key=lambda lang: (-lang.size, lang.name))),
                   bool(data.get("demo", False)))


@dataclass(frozen=True)
class RunnerState:
    mode: str
    total: int
    last7: int
    streak: int
    language: str
    color: str


def derive_state(snapshot: Snapshot, mode: str | None = None) -> RunnerState:
    counts = [day.count for day in snapshot.days]
    total, last7, last14 = sum(counts), sum(counts[-7:]), sum(counts[-14:])
    streak = 0
    for count in reversed(counts):
        if count == 0:
            break
        streak += 1
    if mode is not None and mode not in MODES:
        raise ValueError("Mode must be rest, walk or run.")
    automatic_mode = "rest" if last14 == 0 else "run" if last7 >= 20 else "walk"
    top = snapshot.languages[0] if snapshot.languages else Language("Mixed", 0, "#76dec5")
    return RunnerState(mode or automatic_mode, total, last7, streak, top.name, top.color)


def demo_snapshot(mode: str = "run", through: date | None = None) -> Snapshot:
    """Fixed synthetic data: never presented as the user's real activity."""
    if mode not in MODES:
        raise ValueError("Unknown demo mode.")
    through = through or datetime.now(timezone.utc).date() - timedelta(days=1)
    days = []
    for i in range(365):
        age = 364 - i
        value = (i * 17 + 3) % 4 if i % 5 != 0 else 0
        if age < 14:
            value = 0 if mode == "rest" else (1 if age in (0, 3, 6, 9) else 0) if mode == "walk" else 3 + i % 6
        days.append(Day((through - timedelta(days=age)).isoformat(), value))
    return Snapshot("demo-runner", through.isoformat(), tuple(days), (
        Language("Python", 62000, "#3572A5"),
        Language("TypeScript", 28000, "#3178c6"),
        Language("HTML", 10000, "#e34c26"),
    ), True)


def _graphql(query: str, variables: dict, token: str) -> dict:
    request = Request("https://api.github.com/graphql", method="POST",
                      data=json.dumps({"query": query, "variables": variables}).encode(),
                      headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                               "User-Agent": "git-runner/0.1", "Accept": "application/vnd.github+json"})
    try:
        with urlopen(request, timeout=45) as response:
            body = json.load(response)
    except HTTPError as error:
        raise RuntimeError(f"GitHub returned HTTP {error.code}; check token access and API limits.") from None
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError("Could not read GitHub's response; check the network and retry.") from error
    if body.get("errors"):
        # Never log request headers or tokens.
        messages = "; ".join(str(item.get("message", "GraphQL error")) for item in body["errors"])
        raise RuntimeError(f"GitHub GraphQL: {messages}")
    return body["data"]


CALENDAR_QUERY = """
query RunnerCalendar($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    login
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar { weeks { contributionDays { date contributionCount } } }
    }
  }
}
"""

LANGUAGE_QUERY = """
query RunnerLanguages($login: String!, $cursor: String) {
  user(login: $login) {
    repositories(first: 50, after: $cursor, privacy: PUBLIC, isFork: false,
                 ownerAffiliations: [OWNER], orderBy: {field: NAME, direction: ASC}) {
      pageInfo { hasNextPage endCursor }
      nodes { name languages(first: 100, orderBy: {field: SIZE, direction: DESC}) {
        edges { size node { name color } }
      } }
    }
  }
}
"""


def collect(username: str, token: str, through: date | None = None,
            exclude_repository: str | None = None) -> Snapshot:
    """Read 365 complete UTC days plus languages from public owned, nonfork repos.

    Token-visible contribution totals can include private counts. The collector
    never downloads source code or private repository names.
    """
    if not USERNAME.fullmatch(username):
        raise ValueError("Enter a valid GitHub username (no URL or @ prefix).")
    if not token:
        raise ValueError("Set GH_TOKEN or GITHUB_TOKEN before collecting live data.")
    through = through or datetime.now(timezone.utc).date() - timedelta(days=1)
    start = through - timedelta(days=364)
    data = _graphql(CALENDAR_QUERY, {"login": username,
                    "from": start.isoformat() + "T00:00:00Z",
                    "to": through.isoformat() + "T23:59:59Z"}, token)
    user = data.get("user")
    if not user:
        raise ValueError(f"GitHub user {username!r} was not found.")
    days = [dict(date=day["date"], count=day["contributionCount"])
            for week in user["contributionsCollection"]["contributionCalendar"]["weeks"]
            for day in week["contributionDays"]]
    sizes: dict[str, int] = defaultdict(int)
    colors: dict[str, str] = {}
    cursor = None
    seen_cursors = set()
    while True:
        page_data = _graphql(LANGUAGE_QUERY, {"login": username, "cursor": cursor}, token)
        connection = page_data["user"]["repositories"]
        for repository in connection["nodes"]:
            if exclude_repository and repository["name"].lower() == exclude_repository.lower():
                continue
            for edge in repository["languages"]["edges"]:
                name = edge["node"]["name"]
                sizes[name] += edge["size"]
                colors[name] = edge["node"]["color"] or "#76dec5"
        page = connection["pageInfo"]
        if not page["hasNextPage"]:
            break
        cursor = page["endCursor"]
        if not cursor or cursor in seen_cursors:
            raise RuntimeError("GitHub returned an invalid repository pagination cursor.")
        seen_cursors.add(cursor)
    return Snapshot.from_dict({"username": user["login"], "through": through.isoformat(),
                               "days": days, "languages": [dict(name=name, size=size, color=colors[name])
                                                            for name, size in sizes.items()]})
