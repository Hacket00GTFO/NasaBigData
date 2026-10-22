"""Pruebas sin red: caché real, concurrencia, errores y contrato del frontend."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
import threading
import unittest
from unittest.mock import Mock, patch

import requests

from app import create_app
from app.nasa_client import NasaApiClient, NasaApiError
from app.stats import donki_time_series, donki_latest_events, eonet_map_points, neo_flatten
from config import settings


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.client = NasaApiClient()
        self.addCleanup(self.client._executor.shutdown)

    def response(self, status=200, data=None, headers=None):
        response = Mock(status_code=status, headers=headers or {})
        response.json.return_value = data
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        return response

    def test_repeated_requests_use_cache(self):
        with patch.object(self.client, '_request', return_value=[]) as request:
            for _ in range(2):
                self.assertEqual(self.client.get_donki_events('CME', '2026-01-01', '2026-01-02'), [])
            self.assertEqual(request.call_count, 1)

    def test_cache_expires_and_is_bounded(self):
        with patch.object(settings, 'cache_timeout', 10), patch.object(settings, 'cache_max_entries', 2):
            with patch('app.nasa_client.time.monotonic', return_value=0):
                for key in ('a', 'b', 'c'):
                    self.client._cached(key, lambda: key)
            self.assertEqual(list(self.client._cache), ['b', 'c'])
            with patch('app.nasa_client.time.monotonic', return_value=11):
                self.assertEqual(self.client._cached('c', lambda: 'fresh'), 'fresh')
                self.assertEqual(len(self.client._cache), 1)

    def test_simultaneous_requests_share_download(self):
        entered, release = threading.Event(), threading.Event()
        def load():
            entered.set()
            self.assertTrue(release.wait(2))
            return [1]
        with ThreadPoolExecutor(max_workers=2) as pool, patch.object(self.client, '_request', side_effect=lambda *_: load()) as request:
            first = pool.submit(self.client.get_donki_events, 'CME', '2026-01-01', '2026-01-02')
            self.assertTrue(entered.wait(2))
            second = pool.submit(self.client.get_donki_events, 'CME', '2026-01-01', '2026-01-02')
            release.set()
            self.assertEqual(first.result(), second.result())
            self.assertEqual(request.call_count, 1)

    def test_failures_are_not_cached(self):
        with patch.object(self.client, '_request', side_effect=[NasaApiError('Temporal'), []]) as request:
            with self.assertRaises(NasaApiError):
                self.client.get_donki_events('CME', '2026-01-01', '2026-01-02')
            self.assertEqual(self.client.get_donki_events('CME', '2026-01-01', '2026-01-02'), [])
            self.assertEqual(request.call_count, 2)

    def test_donki_partial_failure_is_explicit(self):
        def get(kind, *_):
            if kind == 'FLR':
                raise NasaApiError('No disponible')
            return []
        with patch.object(self.client, 'get_donki_events', side_effect=get):
            data, errors = self.client.get_donki_all('2026-01-01', '2026-01-02')
        self.assertNotIn('FLR', data)
        self.assertIn('FLR', errors)
        self.assertEqual(len(data), 6)

    def test_eonet_uses_exact_range_and_all_status(self):
        with patch.object(self.client, '_request', return_value={'events': []}) as request:
            self.client.get_eonet_events(start_date='2020-01-01', end_date='2020-01-02')
        self.assertEqual(request.call_args.args[1], {'start': '2020-01-01', 'end': '2020-01-02', 'status': 'all'})

    def test_only_nasa_receives_key(self):
        with patch.object(self.client._session, 'get', return_value=self.response(data={})) as get:
            self.client._request(self.client.base_url + '/planetary/apod', {})
            self.assertEqual(get.call_args.kwargs['params']['api_key'], self.client.api_key)
            self.client._request(self.client.eonet_url + '/events', {})
            self.assertNotIn('api_key', get.call_args.kwargs['params'])

    def test_donki_uses_migrated_public_endpoint_without_key(self):
        with patch.object(self.client._session, 'get', return_value=self.response(data=[])) as get:
            self.client.get_donki_events('CME', '2026-01-01', '2026-01-02')
        self.assertEqual(get.call_args.args[0], self.client.donki_url + '/CME')
        self.assertNotIn('api_key', get.call_args.kwargs['params'])

    def test_unauthorized_is_not_retried_or_leaked(self):
        with patch.object(self.client._session, 'get', return_value=self.response(status=403)) as get:
            with self.assertRaises(NasaApiError) as caught:
                self.client._request(self.client.base_url + '/DONKI/CME', {})
        self.assertEqual(get.call_count, 1)
        self.assertNotIn(self.client.api_key, str(caught.exception))

    def test_transient_errors_retry(self):
        with patch.object(self.client._session, 'get', side_effect=[self.response(status=503), self.response(data=[])]) as get:
            with patch('app.nasa_client.time.sleep'):
                self.assertEqual(self.client._request(self.client.base_url + '/DONKI/CME', {}), [])
        self.assertEqual(get.call_count, 2)

    def test_network_errors_do_not_leak_url(self):
        with patch.object(self.client._session, 'get', side_effect=requests.ConnectionError('url?api_key=' + self.client.api_key)):
            with patch('app.nasa_client.time.sleep'), self.assertRaises(NasaApiError) as caught:
                self.client._request(self.client.base_url + '/DONKI/CME', {})
        self.assertNotIn(self.client.api_key, str(caught.exception))

    def test_rate_limit_prevents_following_requests(self):
        with patch.object(self.client._session, 'get', return_value=self.response(status=429, headers={'Retry-After': '30'})) as get:
            for _ in range(2):
                with self.assertRaises(NasaApiError) as caught:
                    self.client._request(self.client.base_url + '/DONKI/CME', {})
                self.assertEqual(caught.exception.status_code, 429)
        self.assertEqual(get.call_count, 1)

    def test_invalid_json_is_reported(self):
        response = self.response()
        response.json.side_effect = ValueError('html')
        with patch.object(self.client._session, 'get', return_value=response):
            with self.assertRaisesRegex(NasaApiError, 'JSON'):
                self.client._request(self.client.base_url + '/DONKI/CME', {})

    def test_invalid_feed_structure_is_not_cached(self):
        with patch.object(self.client, '_request', side_effect=[{}, {'near_earth_objects': {}}]):
            with self.assertRaises(NasaApiError):
                self.client.get_neo_feed('2026-01-01', '2026-01-02')
            self.assertEqual(self.client.get_neo_feed('2026-01-01', '2026-01-02'), {'near_earth_objects': {}})


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.http = create_app().test_client()
        self.params = {source + suffix: '2026-01-01' for source in ('donki', 'eonet', 'neo') for suffix in ('_start', '_end')}
        self.raw = patch('app.nasa_client.nasa_client._request', side_effect=self.payload)
        self.request = self.raw.start()
        self.addCleanup(self.raw.stop)
        from app.nasa_client import nasa_client
        nasa_client._cache.clear()
        nasa_client._cooldowns.clear()

    @staticmethod
    def payload(url, params):
        if '/DONKI-API/get/' in url:
            return []
        if '/events' in url:
            return {'events': []}
        if '/feed' in url:
            return {'near_earth_objects': {}}
        return {'title': 'APOD', 'date': params['date'], 'url': 'https://example.org/image.jpg'}

    def test_config_and_static_do_not_expose_key(self):
        for path in ('/api/config', '/', '/static/js/app.js'):
            response = self.http.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(settings.nasa_api_key, response.get_data(as_text=True))
            response.close()

    def test_valid_same_day_and_cache_across_http_requests(self):
        first = self.http.get('/api/fetch', query_string=self.params)
        self.assertEqual(first.status_code, 200)
        self.assertFalse(first.json['partial'])
        self.assertEqual(first.json['kpis']['cme'], 0)
        self.assertEqual(first.json['donki']['time_series']['dates'], ['2026-01-01'])
        self.assertEqual(self.request.call_count, 9)
        self.http.get('/api/fetch', query_string=self.params)
        self.assertEqual(self.request.call_count, 9)

    def test_invalid_ranges_fail_before_network(self):
        for field, value in [('donki_start', 'bad'), ('eonet_start', '2026-02-30'),
                             ('donki_end', '2025-12-31'), ('neo_end', '2026-01-08'),
                             ('donki_end', '2028-01-01'), ('eonet_start', '2026-01-01T00:00:00')]:
            with self.subTest(field=field, value=value):
                response = self.http.get('/api/fetch', query_string={**self.params, field: value})
                self.assertEqual(response.status_code, 400)
        self.assertEqual(self.request.call_count, 0)

    def test_seven_inclusive_days_allowed(self):
        response = self.http.get('/api/fetch', query_string={**self.params, 'neo_end': '2026-01-07'})
        self.assertEqual(response.status_code, 200)

    def test_partial_errors_preserve_other_sources_and_null_kpis(self):
        def payload(url, params):
            if url.endswith('/FLR'):
                raise NasaApiError('Temporal')
            return self.payload(url, params)
        self.request.side_effect = payload
        result = self.http.get('/api/fetch', query_string=self.params).json
        self.assertTrue(result['partial'])
        self.assertIn('FLR', result['errors']['donki'])
        self.assertIsNone(result['kpis']['flr'])
        self.assertEqual(result['eonet']['total'], 0)

    def test_sources_download_concurrently(self):
        barrier = threading.Barrier(3, timeout=3)
        from app.nasa_client import nasa_client
        with patch.object(nasa_client, 'get_donki_all', side_effect=lambda *_: wait_value(barrier, ({}, {}))):
            with patch.object(nasa_client, 'get_eonet_events', side_effect=lambda **_: wait_value(barrier, [])):
                with patch.object(nasa_client, 'get_neo_feed', side_effect=lambda *_: wait_value(barrier, {'near_earth_objects': {}})):
                    self.assertEqual(self.http.get('/api/fetch', query_string=self.params).status_code, 200)

    def test_apod_validation_cache_and_rate_limit(self):
        for value in ('1995-06-15', 'invalid', (date.today() + timedelta(days=1)).isoformat()):
            self.assertEqual(self.http.get('/api/apod', query_string={'date': value}).status_code, 400)
        self.assertEqual(self.request.call_count, 0)
        for _ in range(2):
            self.assertEqual(self.http.get('/api/apod?date=2020-01-01').status_code, 200)
        self.assertEqual(self.request.call_count, 1)
        self.request.side_effect = NasaApiError('Espera', 429)
        self.assertEqual(self.http.get('/api/apod?date=2020-01-02').status_code, 429)

    def test_eonet_filters_geometries_without_mutating_cache(self):
        events = [{'geometry': [{'type': 'Point', 'coordinates': [1, 2], 'date': '2025-12-31T00:00:00Z'},
                                {'type': 'Point', 'coordinates': [3, 4], 'date': '2026-01-01T00:00:00Z'}]}]
        from app.nasa_client import nasa_client
        with patch.object(nasa_client, 'get_eonet_events', return_value=events):
            data = self.http.get('/api/fetch', query_string=self.params).json
        self.assertEqual(data['eonet']['map_points'][0]['lat'], 4)
        self.assertEqual(len(events[0]['geometry']), 2)


def wait_value(barrier, value):
    barrier.wait()
    return value


class StatsTests(unittest.TestCase):
    def test_latest_event_is_not_lost_by_table_limit(self):
        result = donki_latest_events({'CME': [{'startTime': '2026-01-03T00:00Z'}] * 30,
                                      'GST': [{'startTime': '2026-01-01T00:00Z'}]})
        self.assertEqual(result['GST'], '2026-01-01T00:00Z')

    def test_empty_days_are_included(self):
        series = donki_time_series({'CME': [{'startTime': '2026-01-02T01:00Z'}], 'GST': []}, '2026-01-01', '2026-01-03')
        self.assertEqual(series['CME'].tolist(), [0, 1, 0])
        self.assertEqual(series['GST'].tolist(), [0, 0, 0])

    def test_polygon_produces_numeric_coordinates(self):
        result = eonet_map_points([{'geometry': [{'type': 'Polygon', 'coordinates': [[[1, 2], [3, 4], [1, 2]]]}]}])
        self.assertEqual(result.iloc[0]['lat'], 2)
        self.assertEqual(result.iloc[0]['lon'], 1)

    def test_neo_selects_approach_for_feed_day(self):
        result = neo_flatten({'near_earth_objects': {'2026-01-02': [{
            'close_approach_data': [
                {'close_approach_date': '2025-01-01', 'miss_distance': {'kilometers': '100'}},
                {'close_approach_date': '2026-01-02', 'miss_distance': {'kilometers': '200'}},
            ]}]}})
        self.assertEqual(result.iloc[0]['miss_km'], 200)


if __name__ == '__main__':
    unittest.main()
