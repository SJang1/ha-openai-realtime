"""Frontend integration for OpenAI Realtime."""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

FRONTEND_PATH = Path(__file__).parent / "frontend"
URL_BASE = "/openai_realtime"
CARD_FILENAME = "openai-realtime-card.js"
CARD_URL = f"{URL_BASE}/{CARD_FILENAME}"


def _get_card_version() -> int:
    """Get the current version from the JS file's modification time."""
    try:
        return int((FRONTEND_PATH / CARD_FILENAME).stat().st_mtime)
    except Exception:
        return 1


async def async_setup_frontend(hass: HomeAssistant) -> None:
    """Set up the frontend for OpenAI Realtime."""
    # Use a separate key for frontend data to avoid polluting entry data
    frontend_key = "_frontend"
    frontend_data = hass.data.setdefault(DOMAIN, {}).setdefault(frontend_key, {})
    
    # Check if already registered to avoid duplicate registration on reload
    if frontend_data.get("registered"):
        _LOGGER.debug("Frontend already registered, skipping static path")
    else:
        # Register static path for the card
        await hass.http.async_register_static_paths([
            StaticPathConfig(
                url_path=CARD_URL,
                path=str(FRONTEND_PATH / CARD_FILENAME),
                cache_headers=False,
            )
        ])
        # Mark as registered
        frontend_data["registered"] = True

    # Store the URL in frontend data for reference
    frontend_data["card_url"] = CARD_URL

    # Always update the card resource version (for cache busting on reload)
    await _register_or_update_card_resource(hass)

    _LOGGER.info(
        "OpenAI Realtime frontend registered at %s",
        CARD_URL,
    )


async def _register_or_update_card_resource(hass: HomeAssistant) -> None:
    """Register or update the card as a Lovelace resource with incremented version."""
    try:
        from homeassistant.components.lovelace import DOMAIN as LOVELACE_DOMAIN
        from homeassistant.components.lovelace.resources import ResourceStorageCollection
        
        lovelace_data = hass.data.get(LOVELACE_DOMAIN)
        if lovelace_data is None:
            _LOGGER.debug("Lovelace not available for auto-registration")
            return
        
        # Use attribute access instead of .get() for HA 2026.2+ compatibility
        resources = getattr(lovelace_data, "resources", None)
        
        if resources is not None and isinstance(resources, ResourceStorageCollection):
            existing_items = await resources.async_get_items()
            
            # Find existing resource
            existing_resource = None
            for resource in existing_items:
                url = resource.get("url", "")
                # Check if this is our card (with or without version query param)
                if CARD_URL in url and CARD_FILENAME in url:
                    existing_resource = resource
                    break
            
            # Get new version based on file modification time
            new_version = _get_card_version()
            new_url = f"{CARD_URL}?v={new_version}"
            
            if existing_resource:
                # Update existing resource with new version
                resource_id = existing_resource.get("id")
                if resource_id:
                    await resources.async_update_item(
                        resource_id,
                        {
                            "res_type": "module",
                            "url": new_url,
                        }
                    )
                    _LOGGER.info("Updated OpenAI Realtime card resource to version %s", new_version)
            else:
                # Create new resource
                await resources.async_create_item({
                    "res_type": "module",
                    "url": new_url,
                })
                _LOGGER.info("Registered OpenAI Realtime card as Lovelace resource (v%s)", new_version)
                
    except Exception as e:
        _LOGGER.debug("Could not auto-register/update Lovelace resource: %s", e)
