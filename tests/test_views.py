"""Test the frigate binary sensor."""
from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock, patch

import aiohttp
from aiohttp import hdrs, web
import pytest

from custom_components.frigate.const import DOMAIN
from homeassistant.const import CONF_URL, HTTP_BAD_REQUEST, HTTP_NOT_FOUND, HTTP_OK
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from . import (
    TEST_FRIGATE_INSTANCE_ID,
    create_mock_frigate_client,
    create_mock_frigate_config_entry,
    setup_mock_frigate_config_entry,
    start_frigate_server,
)

_LOGGER = logging.getLogger(__name__)


class FakeStreamResponse(web.StreamResponse):
    """Fake StreamResponse for testing purposes."""

    async def write(self, data: bytes) -> None:
        """Write data."""
        raise aiohttp.ClientError


class FakeAsyncContextManager:
    """Fake AsyncContextManager for testing purposes."""

    async def __aenter__(self, *args: Any, **kwargs: Any) -> FakeAsyncContextManager:
        """Context manager enter."""
        return self

    async def __aexit__(self, *args: Any, **kwargs: Any) -> None:
        """Context manager exit."""


@pytest.fixture
async def hass_client_local_frigate(
    hass: HomeAssistant, hass_client: Any, aiohttp_server: Any
) -> Any:
    """Point the integration at a local fake Frigate server."""
    await async_setup_component(hass, "http", {"http": {}})

    async def handler(request: web.Request) -> web.Response:
        for header in (
            hdrs.CONTENT_LENGTH,
            hdrs.CONTENT_ENCODING,
            hdrs.SEC_WEBSOCKET_EXTENSIONS,
            hdrs.SEC_WEBSOCKET_PROTOCOL,
            hdrs.SEC_WEBSOCKET_VERSION,
            hdrs.SEC_WEBSOCKET_KEY,
        ):
            assert header not in request.headers

        for header in (
            hdrs.X_FORWARDED_HOST,
            hdrs.X_FORWARDED_PROTO,
            hdrs.X_FORWARDED_FOR,
        ):
            assert header in request.headers
        return web.json_response({})

    server = await start_frigate_server(
        aiohttp_server,
        [
            web.get("/clips/present", handler),
            web.get("/recordings/present", handler),
            web.get("/api/events/event_id/thumbnail.jpg", handler),
            web.get("/api/events/event_id/snapshot.jpg", handler),
            web.get("/clips/camera-event_id.mp4", handler),
        ],
    )

    client = create_mock_frigate_client()
    config_entry = create_mock_frigate_config_entry(
        hass, data={CONF_URL: str(server.make_url("/"))}
    )
    await setup_mock_frigate_config_entry(
        hass, config_entry=config_entry, client=client
    )

    return await hass_client()


async def test_clips_proxy_view_success(
    hass_client_local_frigate: Any,
) -> None:
    """Test straightforward clips requests."""

    resp = await hass_client_local_frigate.get("/api/frigate/clips/present")
    assert resp.status == HTTP_OK

    resp = await hass_client_local_frigate.get("/api/frigate/clips/not_present")
    assert resp.status == HTTP_NOT_FOUND


async def test_clips_proxy_view_write_error(
    caplog: Any, hass_client_local_frigate: Any
) -> None:
    """Test clips request with a write error."""

    with patch(
        "custom_components.frigate.views.web.StreamResponse",
        new=FakeStreamResponse,
    ):
        await hass_client_local_frigate.get("/api/frigate/clips/present")
        assert "Stream error" in caplog.text


async def test_clips_proxy_view_read_error(
    hass: HomeAssistant, caplog: Any, hass_client_local_frigate: Any
) -> None:
    """Test clips request with a read error."""

    mock_request = MagicMock(FakeAsyncContextManager())
    mock_request.side_effect = aiohttp.ClientError

    with patch.object(
        hass.helpers.aiohttp_client.async_get_clientsession(),
        "request",
        new=mock_request,
    ):
        await hass_client_local_frigate.get("/api/frigate/clips/present")
        assert "Reverse proxy error" in caplog.text


async def test_recordings_proxy_view_success(hass_client_local_frigate: Any) -> None:
    """Test straightforward clips requests."""

    resp = await hass_client_local_frigate.get("/api/frigate/recordings/present")
    assert resp.status == HTTP_OK

    resp = await hass_client_local_frigate.get("/api/frigate/recordings/not_present")
    assert resp.status == HTTP_NOT_FOUND


async def test_notifications_proxy_view_thumbnail(
    hass_client_local_frigate: Any,
) -> None:
    """Test notification thumbnail."""

    resp = await hass_client_local_frigate.get(
        "/api/frigate/notifications/event_id/thumbnail.jpg"
    )
    assert resp.status == HTTP_OK


async def test_notifications_proxy_view_snapshot(
    hass_client_local_frigate: Any,
) -> None:
    """Test notification snapshot."""

    resp = await hass_client_local_frigate.get(
        "/api/frigate/notifications/event_id/snapshot.jpg"
    )
    assert resp.status == HTTP_OK


async def test_notifications_proxy_view_clip(
    hass_client_local_frigate: Any,
) -> None:
    """Test notification clip."""

    resp = await hass_client_local_frigate.get(
        "/api/frigate/notifications/event_id/camera/clip.mp4"
    )
    assert resp.status == HTTP_OK


async def test_notifications_proxy_other(
    hass_client_local_frigate: Any,
) -> None:
    """Test notification clip."""

    resp = await hass_client_local_frigate.get(
        "/api/frigate/notifications/event_id/camera/not_present"
    )
    assert resp.status == HTTP_NOT_FOUND


async def test_headers(
    hass_client_local_frigate: Any,
) -> None:
    """Test notification clip."""

    resp = await hass_client_local_frigate.get(
        "/api/frigate/notifications/event_id/thumbnail.jpg",
        headers={hdrs.CONTENT_ENCODING: "foo"},
    )
    assert resp.status == HTTP_OK

    resp = await hass_client_local_frigate.get(
        "/api/frigate/notifications/event_id/thumbnail.jpg",
        headers={hdrs.X_FORWARDED_FOR: "forwarded_for"},
    )
    assert resp.status == HTTP_OK


async def test_clips_with_frigate_instance_id(
    hass_client_local_frigate: Any,
    hass: Any,
) -> None:
    """Test clips with config entry ids."""

    frigate_entries = hass.config_entries.async_entries(DOMAIN)
    assert frigate_entries

    # A Frigate instance id is specified.
    resp = await hass_client_local_frigate.get(
        f"/api/frigate/{TEST_FRIGATE_INSTANCE_ID}/clips/present"
    )
    assert resp.status == HTTP_OK

    # An invalid instance id is specified.
    resp = await hass_client_local_frigate.get(
        "/api/frigate/NOT_A_REAL_ID/clips/present"
    )
    assert resp.status == HTTP_BAD_REQUEST

    # No default allowed when there are multiple entries.
    create_mock_frigate_config_entry(hass, entry_id="another_id")
    resp = await hass_client_local_frigate.get("/api/frigate/clips/present")
    assert resp.status == HTTP_BAD_REQUEST


async def test_recordings_with_frigate_instance_id(
    hass_client_local_frigate: Any,
    hass: Any,
) -> None:
    """Test recordings with config entry ids."""

    frigate_entries = hass.config_entries.async_entries(DOMAIN)
    assert frigate_entries

    # A Frigate instance id is specified.
    resp = await hass_client_local_frigate.get(
        f"/api/frigate/{TEST_FRIGATE_INSTANCE_ID}/recordings/present"
    )
    assert resp.status == HTTP_OK

    # An invalid instance id is specified.
    resp = await hass_client_local_frigate.get(
        "/api/frigate/NOT_A_REAL_ID/recordings/present"
    )
    assert resp.status == HTTP_BAD_REQUEST

    # No default allowed when there are multiple entries.
    create_mock_frigate_config_entry(hass, entry_id="another_id")
    resp = await hass_client_local_frigate.get("/api/frigate/recordings/present")
    assert resp.status == HTTP_BAD_REQUEST


async def test_notifications_with_frigate_instance_id(
    hass_client_local_frigate: Any,
    hass: Any,
) -> None:
    """Test notifications with config entry ids."""

    frigate_entries = hass.config_entries.async_entries(DOMAIN)
    assert frigate_entries

    # A Frigate instance id is specified.
    resp = await hass_client_local_frigate.get(
        f"/api/frigate/{TEST_FRIGATE_INSTANCE_ID}"
        "/notifications/event_id/snapshot.jpg"
    )
    assert resp.status == HTTP_OK

    # An invalid instance id is specified.
    resp = await hass_client_local_frigate.get(
        "/api/frigate/NOT_A_REAL_ID/notifications/event_id/snapshot.jpg"
    )
    assert resp.status == HTTP_BAD_REQUEST

    # No default allowed when there are multiple entries.
    create_mock_frigate_config_entry(hass, entry_id="another_id")
    resp = await hass_client_local_frigate.get(
        "/api/frigate/notifications/event_id/snapshot.jpg"
    )
    assert resp.status == HTTP_BAD_REQUEST