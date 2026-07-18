"""Smoke tests for the backend scaffold (Task 1.1).

These verify the package tree, the application factory, and the
Hypothesis min-100-examples profile are wired up correctly.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import settings

from app.main import create_app


def test_create_app_returns_fastapi_instance() -> None:
    app = create_app()
    assert isinstance(app, FastAPI)
    assert app.title == "Ubuntu Connect API"


def test_health_endpoint_responds_ok() -> None:
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize(
    "module_name",
    [
        "app",
        "app.routers",
        "app.services",
        "app.repositories",
        "app.ai",
        "app.ai.fallback",
        "app.ai.prompts",
        "app.integrations",
        "app.models",
        "app.schemas",
    ],
)
def test_package_tree_is_importable(module_name: str) -> None:
    assert importlib.import_module(module_name) is not None


def test_hypothesis_profile_enforces_minimum_examples() -> None:
    # The active profile must run at least 100 generated examples.
    assert settings().max_examples >= 100
