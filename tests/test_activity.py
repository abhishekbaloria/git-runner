import unittest
from datetime import date, timedelta
from unittest.mock import patch

from git_runner.activity import Snapshot, collect, demo_snapshot, derive_state


class ActivityTests(unittest.TestCase):
    def test_behavior_thresholds_and_streak(self):
        for mode in ("rest", "walk", "run"):
            with self.subTest(mode=mode):
                state = derive_state(demo_snapshot(mode, date(2026, 11, 2)))
                self.assertEqual(state.mode, mode)
        running = derive_state(demo_snapshot("run"))
        self.assertEqual(running.streak, 14)
        self.assertEqual(running.language, "Python")

    def test_missing_days_break_streak_and_future_days_are_excluded(self):
        data = {"username": "octocat", "through": "2026-11-02", "days": [
            {"date": "2026-10-31", "count": 8},
            {"date": "2026-11-02", "count": 2},
            {"date": "2026-11-03", "count": 500},
        ]}
        snap = Snapshot.from_dict(data)
        self.assertEqual(len(snap.days), 365)
        state = derive_state(snap)
        self.assertEqual((state.total, state.last7, state.streak), (10, 10, 1))
        self.assertEqual(state.mode, "walk")

    def test_roundtrip_and_invalid_snapshot(self):
        snap = demo_snapshot("run", date(2026, 11, 2))
        self.assertEqual(Snapshot.from_dict(snap.to_dict()), snap)
        data = snap.to_dict()
        data["days"][0]["count"] = -1
        with self.assertRaises(ValueError):
            Snapshot.from_dict(data)

    def test_calendar_window_and_repository_pagination(self):
        pages = [
            {"user": {"login": "octocat", "contributionsCollection": {"contributionCalendar": {
                "weeks": [{"contributionDays": [{"date": "2026-11-02", "contributionCount": 7}]}]
            }}}},
            {"user": {"repositories": {"pageInfo": {"hasNextPage": True, "endCursor": "next"}, "nodes": [
                {"name": "git-runner", "languages": {"edges": [{"size": 10000, "node": {"name": "Python", "color": "#3572A5"}}]}},
                {"name": "app", "languages": {"edges": [{"size": 10, "node": {"name": "JavaScript", "color": "#f1e05a"}}]}},
            ]}}},
            {"user": {"repositories": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [
                {"name": "web", "languages": {"edges": [{"size": 20, "node": {"name": "JavaScript", "color": "#f1e05a"}}]}},
            ]}}},
        ]
        with patch("git_runner.activity._graphql", side_effect=pages) as api:
            snap = collect("octocat", "test-token", date(2026, 11, 2), "git-runner")
        self.assertEqual(api.call_count, 3)
        self.assertEqual(api.call_args_list[2].args[1]["cursor"], "next")
        window = api.call_args_list[0].args[1]
        self.assertEqual(window["to"], "2026-11-02T23:59:59Z")
        first = date.fromisoformat(window["from"][:10])
        self.assertEqual(date(2026, 11, 2) - first, timedelta(days=364))
        self.assertEqual(snap.languages[0].size, 30)
        self.assertEqual(snap.languages[0].name, "JavaScript")

    def test_missing_token_and_invalid_username_do_not_call_network(self):
        with patch("git_runner.activity._graphql") as api:
            with self.assertRaises(ValueError):
                collect("octocat", "")
            with self.assertRaises(ValueError):
                collect("https://github.com/octocat", "test-token")
            api.assert_not_called()


if __name__ == "__main__":
    unittest.main()
