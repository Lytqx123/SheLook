"""核心业务回归测试"""

import asyncio
import json
from datetime import date
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pytest

from app.config import settings
from app.services import fairness_service
from app.services.c2pa_service import AI_SOURCE_TYPE, verify_c2pa_manifest_v2
from app.services.clustering_service import _run_kmeans
from app.services.fairness_service import _classify_images, _distribution_metrics
from app.services.image_fetcher import (
    ImageFetchError,
    _configured_minio_location,
    validate_remote_image_url,
)
from app.services.metrics_collector import AmazonCollector
from app.services.predictor import CTRPredictor
from app.services.storage_service import get_minio_presign_client


class _ReturnClassifier:
    def predict_proba(self, _features):
        return np.array([[0.2, 0.8]])


class _SingleClassHitClassifier:
    classes_ = np.array([0])

    def predict_proba(self, _features):
        return np.array([[1.0]])


def test_return_risk_uses_classifier_probability_once():
    predictor = CTRPredictor()
    predictor.is_trained = True
    predictor.return_classifier = _ReturnClassifier()
    predictor._predict_return_risk_heuristic = lambda _features: {"source": "heuristic"}

    result = predictor.predict_return_risk([0.0])

    assert result["return_risk_probability"] == 0.8
    assert result["risk_score"] == 80.0
    assert result["return_risk_level"] == "high"


def test_hit_prediction_handles_training_data_with_only_negative_class():
    predictor = CTRPredictor()
    predictor.is_trained = True
    predictor.hit_classifier = _SingleClassHitClassifier()

    result = predictor.predict_hit_probability([0.0])

    assert result == {"hit_probability": 0.0, "verdict": "low"}


def test_fairness_metrics_exclude_unknown_classifications_from_denominator():
    result = _distribution_metrics(
        {"light": 4, "medium": 3, "dark": 2, "no_person": 1, "unknown": 90},
        "default",
    )

    assert result["ratios"] == {"light": 0.4, "medium": 0.3, "dark": 0.2}


def test_fairness_reuses_cached_labels_and_caps_fresh_classification(monkeypatch):
    images = [
        SimpleNamespace(quality_scores={"skin_tone": "light"}, image_url="cached"),
        SimpleNamespace(quality_scores={}, image_url="fresh"),
        SimpleNamespace(quality_scores={}, image_url="deferred"),
    ]
    db = mock.AsyncMock()
    classify = mock.AsyncMock(return_value="dark")
    resolve = mock.AsyncMock(side_effect=lambda image: image.image_url)
    monkeypatch.setattr(settings, "FAIRNESS_MAX_CLASSIFICATIONS_PER_REQUEST", 1)
    monkeypatch.setattr(fairness_service, "_classify_skin_tone", classify)
    monkeypatch.setattr("app.services.storage_service.resolve_image_url", resolve)

    labels = asyncio.run(_classify_images(db, images))

    assert labels == ["light", "dark", "unknown"]
    assert images[1].quality_scores["skin_tone"] == "dark"
    classify.assert_awaited_once_with("fresh")
    db.commit.assert_awaited_once()


def test_kmeans_accepts_a_single_sample():
    result = _run_kmeans(np.array([[1.0, 2.0]]), n_clusters=None)

    assert result["n_clusters"] == 1
    assert result["labels"].tolist() == [0]
    assert result["silhouette"] is None


def test_image_fetcher_blocks_private_ip_without_explicit_trust(monkeypatch):
    monkeypatch.setattr(settings, "IMAGE_FETCH_ALLOWED_HOSTS", ["169.254.169.254"])
    monkeypatch.setattr(settings, "IMAGE_FETCH_TRUSTED_PRIVATE_HOSTS", [])

    with pytest.raises(ImageFetchError, match="受限网络"):
        validate_remote_image_url("http://169.254.169.254/latest/meta-data")


def test_configured_minio_url_uses_object_mapping_not_general_ssrf_trust(monkeypatch):
    monkeypatch.setattr(settings, "MINIO_PUBLIC_BASE_URL", "http://localhost:9000")
    monkeypatch.setattr(settings, "MINIO_BUCKET", "product-images")
    monkeypatch.setattr(settings, "MINIO_PRIVATE_BUCKET", "product-images-private")
    monkeypatch.setattr(settings, "IMAGE_FETCH_ALLOWED_HOSTS", [])
    monkeypatch.setattr(settings, "IMAGE_FETCH_TRUSTED_PRIVATE_HOSTS", [])

    assert _configured_minio_location(
        "http://localhost:9000/product-images/demo/item.jpg?signature=test"
    ) == ("product-images", "demo/item.jpg")
    assert _configured_minio_location("http://localhost:9000/admin") is None
    with pytest.raises(ImageFetchError, match="allowlist"):
        validate_remote_image_url("http://localhost:9000/admin")


def test_private_presigned_url_uses_browser_visible_origin(monkeypatch):
    monkeypatch.setattr(settings, "MINIO_PUBLIC_BASE_URL", "http://localhost:9000")
    monkeypatch.setattr(settings, "MINIO_REGION", "us-east-1")

    url = get_minio_presign_client().presigned_get_object(
        "product-images-private",
        "drafts/item.jpg",
    )

    assert url.startswith("http://localhost:9000/product-images-private/drafts/item.jpg?")


def test_c2pa_verifier_requires_sdk_store_and_ai_source_assertion():
    manifest = {
        "active_manifest": "urn:c2pa:test",
        "manifests": {
            "urn:c2pa:test": {
                "assertions": [
                    {
                        "label": "c2pa.actions.v2",
                        "data": {
                            "actions": [
                                {
                                    "action": "c2pa.created",
                                    "digitalSourceType": AI_SOURCE_TYPE,
                                }
                            ]
                        },
                    },
                    {
                        "label": "com.shelook.ai-generation",
                        "data": {
                            "ai_generated": True,
                            "generation_model": "test-model",
                            "generation_timestamp": "2026-07-16T00:00:00Z",
                            "prompt_hash_sha256": "a" * 64,
                        },
                    },
                ]
            }
        },
    }

    assert verify_c2pa_manifest_v2(json.dumps(manifest))["passed"] is True


def test_amazon_report_parser_does_not_fabricate_clicks_or_ctr():
    payload = {
        "salesAndTrafficByAsin": [
            {
                "childAsin": "B012345678",
                "salesByAsin": {"orderedProductSales": {"amount": 42.5}},
                "trafficByAsin": {
                    "pageViews": 100,
                    "sessions": 80,
                    "unitSessionPercentage": 12.5,
                },
            }
        ]
    }

    item = AmazonCollector._parse_daily_report(payload, date(2026, 7, 16))[0]

    assert item.external_id == "B012345678"
    assert item.impressions == 0
    assert item.clicks == 0
    assert item.ctr is None
    assert item.cvr == 0.125
    assert item.revenue == 42.5
