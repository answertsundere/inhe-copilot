from __future__ import annotations

from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import product_media_observation_routes as routes
from app.db import Base
from app.models.product_media_observation import ProductMediaObservationCandidate


def test_observation_review_api_requires_supervisor_and_returns_shadow_contract(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    session.add(ProductMediaObservationCandidate(
        observation_uid="route-test", media_asset_id=1, i_id="IID-1", observed_media_sha256="a" * 64,
        observation_type="labelled_dimension", attribute_key="width", raw_observation="80cm",
    ))
    session.commit()
    monkeypatch.setattr(routes, "SessionLocal", lambda: session)
    app = Flask(__name__)
    app.register_blueprint(routes.product_media_observation_bp)
    client = app.test_client()
    assert client.get("/api/product-media-observations").status_code == 403
    response = client.get("/api/product-media-observations", headers={"X-User-Role": "supervisor"})
    assert response.status_code == 200
    item = response.get_json()["items"][0]
    assert item["direct_answer_allowed"] is False
    assert item["used_for_generation"] is False
    assert item["can_change_can_send"] is False
    session.close()
