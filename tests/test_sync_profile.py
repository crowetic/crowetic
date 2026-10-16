import datetime as dt
from pathlib import Path
import sys
import unittest
from unittest import mock
import urllib.error
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import sync_profile as s

NOW = dt.datetime(2026, 10, 15, 20, 0, tzinfo=dt.timezone.utc)


def gitea_event(event_id=42, *, private=False):
    return {
        'id': event_id,
        'is_private': private,
        'act_user': {'login': 'crowetic'},
        'repo': {'full_name': 'NuQloud-Public/nuqloud-ai', 'private': private},
        'op_type': 'commit_repo',
        'created': '2026-10-15T19:00:00Z',
    }


def github_event(event_id='43', *, public=True):
    return {
        'id': event_id, 'public': public,
        'actor': {'login': 'crowetic'},
        'repo': {'name': 'Qortal/qortal'},
        'type': 'PushEvent',
        'created_at': '2026-10-15T18:00:00Z',
    }


class TestSync(unittest.TestCase):
    def test_gitea_public_actor_org_repos(self):
        row = s.normalize_gitea_event(gitea_event())
        self.assertEqual(row['url'], 'https://gitea.qortal.link/NuQloud-Public/nuqloud-ai')
        self.assertEqual(row['source'], 'Gitea')

    def test_gitea_private_not_included(self):
        self.assertIsNone(s.normalize_gitea_event(gitea_event(private=True)))
        row = gitea_event()
        row['repo'].pop('private')
        self.assertIsNone(s.normalize_gitea_event(row))
        row = gitea_event()
        row['act_user']['login'] = 'somebody-else'
        self.assertIsNone(s.normalize_gitea_event(row))

    def test_disallow_untrusted_repo_names(self):
        row = gitea_event()
        row['repo']['full_name'] = 'NuQloud-Public/nuqloud-ai](https://bad.example)'
        self.assertIsNone(s.normalize_gitea_event(row))

    def test_github_public_only(self):
        self.assertEqual(s.normalize_github_event(github_event())['source'], 'GitHub')
        self.assertIsNone(s.normalize_github_event(github_event(public=False)))
        row = github_event()
        row['repo']['name'] = 'crowetic/crowetic'
        self.assertIsNone(s.normalize_github_event(row))

    def test_api_gitea_date_scoped(self):
        seen = []
        def fake(url, token=None):
            seen.append(url)
            return [gitea_event(event_id=42)] if 'date=2026-10-15' in url else []
        with mock.patch.object(s, 'get_json', side_effect=fake):
            events = s.fetch_gitea_events(NOW.date())
        self.assertEqual(len(events), 1)
        self.assertEqual(len(seen), 8)
        self.assertTrue(all('only-performed-by=true' in url for url in seen))

    def test_failure_keeps_valid_cached_events(self):
        past = s.normalize_gitea_event(gitea_event())
        cache = {
            'gitea': {'events': [past], 'feed_updated_at': '2026-10-14T15:00:00Z'},
            'github': {'events': []},
        }
        with (mock.patch.object(s, 'fetch_gitea_events', side_effect=urllib.error.URLError('network down')),
              mock.patch.object(s, 'fetch_gitea_heatmap', side_effect=urllib.error.URLError('network down')),
              mock.patch.object(s, 'fetch_github_events', return_value=[])):
            result = s.sync(cache, NOW)
        self.assertEqual(len(result['gitea']['events']), 1)
        self.assertEqual(result['gitea']['feed_updated_at'], '2026-10-14T15:00:00Z')

    def test_readme_markers_and_svg(self):
        source = f'# hello\n{s.START}\nold\n{s.END}\nbye\n'
        replaced = s.replace_activity(source, 'new')
        self.assertEqual(replaced, f'# hello\n{s.START}\nnew\n{s.END}\nbye\n')
        with self.assertRaises(ValueError):
            s.replace_activity('bad readme', 'X')
        blob = s.render_svg({'gitea': {'events': []}, 'github': {'events': []}}, NOW)
        ET.fromstring(blob)
        self.assertIn('PUBLIC ACTIVITY / 28 DAYS', blob)

    def test_cache_sanitizes_bad_untrusted_fields(self):
        cached = s.normalize_github_event(github_event())
        cached['url'] = 'https://evil.example'
        sanitized = s.sanitize_old_events([cached], 'GitHub')
        self.assertEqual(sanitized[0]['url'], 'https://github.com/Qortal/qortal')


if __name__ == '__main__':
    unittest.main()
