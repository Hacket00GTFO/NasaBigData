"""Pruebas sin red del pipeline de predicciones.

Cubre SQLite (upserts idempotentes), los parsers de las respuestas de
cada fuente, la construccion de features y el ciclo completo de
entrenamiento + pronostico + backtest con datos sinteticos.
"""
from datetime import date, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, PropertyMock

import pandas as pd

from app import features, ml
from app.collector import parse_donki_events, parse_eonet_events, parse_open_meteo
from app.db import Store
from config import settings


def synthetic_store(days: int = 900):
    """Store en directorio temporal con series deterministas.

    Flares con patron semanal y clase X cada 30 dias; incendios EONET
    concentrados en el verano boreal; clima mas calido en verano.
    """
    tmp = tempfile.TemporaryDirectory()
    store = Store(Path(tmp.name) / "pipeline.db")
    store.init()
    base = date(2023, 1, 1)
    donki, eonet, climate = [], [], []
    for i in range(days):
        day = base + timedelta(days=i)
        iso = day.isoformat()
        n_flares = (i % 7) + (1 if i % 28 < 14 else 0)
        for j in range(n_flares):
            cls = "M1.0" if j % 3 == 0 else "C4.0"
            donki.append(("FLR", f"FLR-{i}-{j}", iso, f"{iso}T00:0{j}:00Z",
                          f'{{"class": "{cls}", "top_class": "{cls[0]}"}}'))
        if i % 30 == 0:
            donki.append(("FLR", f"FLRX-{i}", iso, f"{iso}T12:00:00Z",
                          '{"class": "X1.0", "top_class": "X"}'))
        if i % 5 == 0:
            donki.append(("CME", f"CME-{i}", iso, f"{iso}T06:00:00Z", '{"speed": 500}'))
        n_fires = 3 if 6 <= day.month <= 9 else (1 if i % 3 == 0 else 0)
        for j in range(n_fires):
            eonet.append((f"EONET-{i}-{j}", f"Incendio {j}", "Wildfires",
                          iso, iso, 10.0 + j, -20.0 - j))
        temp = 30.0 if 6 <= day.month <= 9 else 15.0
        climate.append(("California", iso, temp, temp - 8, 0.0, 5.0))
    store.upsert_donki(donki)
    store.upsert_eonet(eonet)
    store.upsert_open_meteo(climate)
    return store, tmp


class CollectorParseTests(unittest.TestCase):
    def test_parse_donki_extracts_class_and_day(self):
        raw = [{
            "activityID": "2014-01-01T00:00", "startTime": "2014-01-01T00:45Z",
            "classType": "X1.2", "sourceLocation": "S15W12", "activeRegionNum": 11944,
        }]
        rows = parse_donki_events("FLR", raw)
        self.assertEqual(len(rows), 1)
        etype, eid, day, ts, extra = rows[0]
        self.assertEqual((etype, eid, day), ("FLR", "2014-01-01T00:00", "2014-01-01"))
        self.assertIn('"top_class": "X"', extra)

    def test_parse_donki_gst_extracts_max_kp(self):
        raw = [{
            "gstID": "2016-01-01T00:00", "startTime": "2016-01-01T00:00Z",
            "allKpIndex": [{"kpIndex": 5}, {"kpIndex": 8}, {"kpIndex": 7}],
        }]
        rows = parse_donki_events("GST", raw)
        self.assertIn('"max_kp": 8', rows[0][4])

    def test_parse_donki_skips_incomplete_events(self):
        self.assertEqual(parse_donki_events("FLR", [{"startTime": "2014-01-01T00:00Z"}]), [])
        self.assertEqual(parse_donki_events("FLR", [{"activityID": "x"}]), [])

    def test_parse_eonet_first_last_day_and_coords(self):
        raw = [{
            "id": "EONET_1", "title": "Fuego", "categories": [{"title": "Wildfires"}],
            "geometry": [
                {"date": "2023-06-02T00:00:00Z", "coordinates": [-120.1, 36.7]},
                {"date": "2023-06-01T00:00:00Z", "type": "Point", "coordinates": [[[-121.0, 37.0]]]},
            ],
        }]
        rows = parse_eonet_events(raw)
        self.assertEqual(len(rows), 1)
        eid, title, category, first, last, lat, lon = rows[0]
        self.assertEqual((eid, category, first, last), ("EONET_1", "Wildfires", "2023-06-01", "2023-06-02"))
        self.assertEqual((lat, lon), (37.0, -121.0))

    def test_parse_open_meteo_multi_location(self):
        payload = [
            {"daily": {"time": ["2023-01-01"], "temperature_2m_max": [20.0],
                       "temperature_2m_min": [8.0], "precipitation_sum": [0.2],
                       "wind_speed_10m_max": [None]}},
            {"daily": {"time": ["2023-01-01"], "temperature_2m_max": [30.0],
                       "temperature_2m_min": [18.0], "precipitation_sum": [None],
                       "wind_speed_10m_max": [12.0]}},
        ]
        rows = parse_open_meteo(payload, ["California", "Amazonia"])
        self.assertEqual(rows[0][:2], ("California", "2023-01-01"))
        self.assertEqual(rows[0][5], None)  # viento nulo
        self.assertEqual(rows[1][:2], ("Amazonia", "2023-01-01"))
        self.assertEqual(rows[1][5], 12.0)


class StoreTests(unittest.TestCase):
    def test_upsert_donki_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "t.db")
            store.init()
            row = ("FLR", "ID1", "2024-01-01", "2024-01-01T00:00Z", None)
            store.upsert_donki([row])
            store.upsert_donki([row])
            self.assertEqual(store.counts()["donki_events"], 1)

    def test_dataset_summary_reports_ranges(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "t.db")
            store.init()
            store.upsert_donki([("FLR", "ID1", "2024-01-01", None, None)])
            store.record_run("donki", "backfill", True, 1)
            summary = store.dataset_summary()
            donki = next(t for t in summary["tables"] if t["table"] == "donki_events")
            self.assertEqual(donki["from"], "2024-01-01")
            self.assertEqual(summary["last_runs"][0]["source"], "donki")


class FeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store, cls.tmp = synthetic_store()
        cls.frame = features.flare_frame(cls.store)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_flare_frame_has_targets_and_lags(self):
        frame = self.frame
        self.assertFalse(frame.empty)
        for column in ("flares_next", "flares_week", "flares_x_next",
                       "flares_lag1", "flares_roll7", "cycle_sin",
                       "flux_max", "flux_sum", "days_since_x"):
            self.assertIn(column, frame.columns)

    def test_flux_scale_is_log_watts(self):
        # Un X1.0 tiene flujo 1e-4 W/m2 -> log10 = -4.0 exacto.
        flux = features.flare_flux_daily(self.store)
        self.assertFalse(flux.empty)
        self.assertTrue((flux["flux_max"] <= -3.9).all())
        self.assertTrue((flux["flux_max"] > -8.1).all())

    def test_days_since_x_resets_and_accumulates(self):
        series = self.frame["days_since_x"]
        x_days = self.frame[self.frame["flares_x"] > 0]
        # En un dia con flare X el contador esta en cero.
        self.assertTrue((series.loc[x_days.index] == 0).all())
        self.assertTrue((series >= 0).all())
        self.assertTrue((series <= 180).all())

    def test_lag_and_target_alignment(self):
        # El objetivo de un dia debe ser el valor del dia siguiente.
        flares = self.frame["flares"]
        nxt = self.frame["flares_next"]
        self.assertTrue((nxt.shift(1).dropna() == flares.loc[nxt.shift(1).dropna().index]).all())
        # El lag1 de un dia debe ser el valor del dia anterior.
        lag1 = self.frame["flares_lag1"]
        self.assertTrue((lag1.shift(-1).dropna() == flares.loc[lag1.shift(-1).dropna().index]).all())

    def test_week_target_sums_next_seven_days(self):
        frame = self.frame
        idx = 100
        expected = frame["flares"].iloc[idx + 1: idx + 8].sum()
        self.assertAlmostEqual(frame["flares_week"].iloc[idx], expected)

    def test_eonet_frame_includes_climate(self):
        eframe = features.eonet_frame(self.store, "Wildfires")
        self.assertFalse(eframe.empty)
        for column in ("events_next", "events_lag1", "t_max", "cycle_sin"):
            self.assertIn(column, eframe.columns)


class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store, cls.tmp = synthetic_store()
        cls.models_dir = Path(cls.tmp.name) / "models"
        patcher = patch.object(type(settings), "models_path",
                               new_callable=PropertyMock, return_value=cls.models_dir)
        patcher.start()
        cls.patcher = patcher
        cls.results = ml.train_all(cls.store)

    @classmethod
    def tearDownClass(cls):
        cls.patcher.stop()
        cls.tmp.cleanup()

    def test_all_core_models_train(self):
        self.assertEqual(self.results["flares_next_day"]["status"], "ok")
        self.assertEqual(self.results["flares_week_total"]["status"], "ok")
        self.assertEqual(self.results["flares_x_next_day"]["status"], "ok")

    def test_regression_reports_baseline_and_skill(self):
        metrics = self.results["flares_next_day"]
        for key in ("mae", "rmse", "r2", "baseline_mae", "skill",
                    "variant", "val_scores", "params", "top_features", "level_col"):
            self.assertIn(key, metrics)
        self.assertIn(metrics["variant"], ("persistencia", "delta", "directa"))
        self.assertIn("delta", metrics["val_scores"])
        self.assertGreaterEqual(metrics["mae"], 0)

    def test_models_are_registered(self):
        models = self.store.registered_models()
        names = {m["name"] for m in models}
        self.assertIn("flares_next_day", names)
        for model in models:
            self.assertIsInstance(model["feature_cols"], list)
            self.assertIn("status", model["metrics"])

    def test_predict_uses_last_row(self):
        forecasts = ml.predict(self.store)
        self.assertIn("flares_next_day", forecasts)
        forecast = forecasts["flares_next_day"]
        self.assertEqual(forecast["status"], "ok")
        self.assertGreaterEqual(forecast["value"], 0)
        self.assertEqual(forecast["date"],
                         (pd.Timestamp(forecast["last_day"]) + pd.Timedelta(days=1)).strftime("%Y-%m-%d"))
        self.assertGreaterEqual(forecasts["flares_x_next_day"]["probability"], 0)

    def test_backtest_aligns_actual_and_predicted(self):
        backtests = ml.backtest(self.store, days=30)
        for name, bt in backtests.items():
            self.assertEqual(len(bt["dates"]), len(bt["actual"]))
            self.assertEqual(len(bt["predicted"]), len(bt["actual"]))
            self.assertTrue(all(v >= 0 for v in bt["predicted"]))

    def test_persistence_model_predicts_level(self):
        """La variante persistencia se sirve sin artefacto joblib."""
        fresh, tmp = synthetic_store(days=300)
        self.addCleanup(tmp.cleanup)
        fresh.register_model({
            "name": "flares_fake_persist", "frame": "flare", "target": "flares_next",
            "horizon_days": 1, "kind": "persistence", "feature_cols": ["flares"],
            "metrics": {"status": "ok", "kind": "persistence", "variant": "persistencia",
                        "level_col": "flares"},
            "model_path": None, "trained_at": "test",
        })
        forecasts = ml.predict(fresh)
        forecast = forecasts["flares_fake_persist"]
        self.assertEqual(forecast["status"], "ok")
        expected = float(features.flare_frame(fresh)["flares"].iloc[-1])
        self.assertEqual(forecast["value"], round(max(0.0, expected), 2))
        backtests = ml.backtest(fresh, days=15)
        bt = backtests["flares_fake_persist"]
        self.assertEqual(len(bt["dates"]), len(bt["predicted"]))
        self.assertTrue(all(v >= 0 for v in bt["predicted"]))


class PredictionEndpointTests(unittest.TestCase):
    def test_predictions_without_models_reports_not_ready(self):
        from app import create_app
        with tempfile.TemporaryDirectory() as tmp:
            test_store = Store(Path(tmp) / "api.db")
            test_store.init()
            with patch("app.api.store", test_store):
                app = create_app()
                client = app.test_client()
                response = client.get("/api/predictions")
                body = response.get_json()
                self.assertEqual(response.status_code, 200)
                self.assertFalse(body["ready"])
                self.assertIn("message", body)

    def test_train_requires_dataset(self):
        from app import create_app
        with tempfile.TemporaryDirectory() as tmp:
            test_store = Store(Path(tmp) / "api.db")
            test_store.init()
            with patch("app.api.store", test_store):
                app = create_app()
                client = app.test_client()
                response = client.post("/api/train")
                self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
