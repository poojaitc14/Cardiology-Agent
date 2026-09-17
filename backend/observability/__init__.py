"""Langfuse observability configuration."""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


class LangfuseConfig:
    """Configuration for Langfuse observability."""

    def __init__(self):
        """Initialize Langfuse configuration from environment variables."""
        self.enabled = os.environ.get("LANGFUSE_ENABLED", "true").lower() == "true"
        self.public_key = os.environ.get("LANGFUSE_PUBLIC_KEY")
        self.secret_key = os.environ.get("LANGFUSE_SECRET_KEY")
        self.host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")
        
        # Validate configuration
        if self.enabled:
            if not self.public_key or not self.secret_key:
                logger.warning(
                    "Langfuse enabled but LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY not set. "
                    "Disabling Langfuse observability."
                )
                self.enabled = False
            else:
                logger.info("Langfuse observability enabled")
    
    def is_enabled(self) -> bool:
        """Check if Langfuse is enabled."""
        return self.enabled


# Global config instance
_config: LangfuseConfig | None = None


def get_config() -> LangfuseConfig:
    """Get or create the global Langfuse configuration."""
    global _config
    if _config is None:
        _config = LangfuseConfig()
    return _config


def get_langfuse_client():
    """Get Langfuse client instance if enabled."""
    config = get_config()
    if not config.is_enabled():
        return None
    
    try:
        from langfuse import Langfuse
        
        return Langfuse(
            public_key=config.public_key,
            secret_key=config.secret_key,
            host=config.host,
        )
    except ImportError:
        logger.warning("langfuse package not installed")
        return None
