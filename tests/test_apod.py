import unittest
from unittest.mock import patch

from app.apod import normalize_apod
from app.nasa_client import NasaApiClient, NasaApiError
from config import settings


class ApodTests(unittest.TestCase):
    def setUp(self):
        self.legacy = {'date': '2024-01-01', 'title': 'Galaxy', 'media_type': 'image',
                       'url': 'https://apod.nasa.gov/apod/image/galaxy.jpg',
                       'hdurl': 'https://apod.nasa.gov/apod/image/galaxy-hd.jpg'}
        self.modern = {**self.legacy, 'post_id': 123, 'permalink': 'https://science.nasa.gov/image-article/galaxy/',
                       'url': 'https://science.nasa.gov/image-article/galaxy/',
                       'explanation': '<p>A <strong>galaxy</strong> &amp; stars.</p>',
                       'copyright': '<a href="https://example.org">Photographer</a>'}

    def test_legacy_keeps_normal_size_image(self):
        self.assertEqual(normalize_apod(self.legacy)['url'], self.legacy['url'])

    def test_modern_uses_image_not_article_and_strips_html(self):
        result = normalize_apod(self.modern, '2024-01-01')
        self.assertEqual(result['url'], self.modern['hdurl'])
        self.assertEqual(result['source_url'], self.modern['permalink'])
        self.assertEqual(result['copyright'], 'Photographer')
        self.assertEqual(result['explanation'], 'A galaxy & stars.')

    def test_generic_logo_and_wrong_dates_are_rejected(self):
        for changes in ({'title': 'NASA Science'}, {'url': 'https://science.nasa.gov/nasa-logo@2x.png'},
                        {'date': '2024-01-02'}, {'url': 'javascript:alert(1)'}, {'media_type': 'unknown'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                normalize_apod({**self.legacy, **changes}, '2024-01-01')

    def test_video_comes_from_embed_not_permalink(self):
        data = {**self.modern, 'media_type': 'iframe',
                'basic_html': '<script>alert(1)</script><iframe src="https://www.youtube.com/embed/abc"></iframe>'}
        result = normalize_apod(data)
        self.assertEqual(result['url'], 'https://www.youtube.com/embed/abc')
        self.assertEqual(result['media_type'], 'video')
        self.assertNotIn('basic_html', result)

    def test_missing_featured_image_is_not_replaced_with_article(self):
        with self.assertRaises(ValueError):
            normalize_apod({**self.modern, 'hdurl': ''})

    def test_generic_primary_uses_official_fallback_and_caches_correct_content(self):
        client = NasaApiClient()
        self.addCleanup(client._executor.shutdown)
        with patch.object(client, '_request', side_effect=[{**self.legacy, 'title': 'NASA Science'}, self.modern]) as get:
            result = client.get_apod(date='2024-01-01')
            self.assertEqual(result['title'], 'Galaxy')
            self.assertEqual(client.get_apod(date='2024-01-01'), result)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args.args, (settings.apod_fallback_base_url + '/240101', {}))

    def test_invalid_fallback_is_not_cached(self):
        client = NasaApiClient()
        self.addCleanup(client._executor.shutdown)
        with patch.object(client, '_request', return_value={**self.legacy, 'title': 'NASA Science'}):
            with self.assertRaises(NasaApiError):
                client.get_apod(date='2024-01-01')
        self.assertEqual(len(client._cache), 0)

    def test_rate_limit_does_not_trigger_fallback(self):
        client = NasaApiClient()
        self.addCleanup(client._executor.shutdown)
        with patch.object(client, '_request', side_effect=NasaApiError('Espera', 429)) as get:
            with self.assertRaises(NasaApiError):
                client.get_apod(date='2024-01-01')
        self.assertEqual(get.call_count, 1)


if __name__ == '__main__':
    unittest.main()
