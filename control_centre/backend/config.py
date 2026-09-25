"""
config.py
Centralized configuration for the FLEET-IQ Control Centre.

Consolidates environment variables and runtime configuration that was
previously scattered across multiple modules. All FLEETIQ_* environment
variables are accessed through this module.

PRESERVES: All existing environment variable names and default values.
"""

import os
from dataclasses import dataclass, field
from typing import Dict, Any, Optional


# ---------------------------------------------------------------------------
# Environment variable names (preserved for backward compatibility)
# ---------------------------------------------------------------------------

# Authentication
ENV_ADMIN_USER = "FLEETIQ_ADMIN_USER"
ENV_ADMIN_PASSWORD = "FLEETIQ_ADMIN_PASSWORD"
ENV_SESSION_TTL_HOURS = "FLEETIQ_SESSION_TTL_HOURS"

# Camera devices
ENV_DRIVER_CAMERA_DEVICE = "FLEETIQ_DRIVER_CAMERA_DEVICE"
ENV_CABIN_CAMERA_DEVICE = "FLEETIQ_CABIN_CAMERA_DEVICE"
ENV_ROAD_CAMERA_DEVICE = "FLEETIQ_ROAD_CAMERA_DEVICE"
ENV_CAMERA_BUS_ID = "FLEETIQ_CAMERA_BUS_ID"

# Cabin occupancy
ENV_CABIN_INFERENCE_INTERVAL_SEC = "FLEETIQ_CABIN_INFERENCE_INTERVAL_SEC"
ENV_CABIN_DEFAULT_CAPACITY = "FLEETIQ_CABIN_DEFAULT_CAPACITY"
ENV_CABIN_MODEL_PATH = "FLEETIQ_CABIN_MODEL_PATH"
ENV_CABIN_CAMERA_ID = "FLEETIQ_CABIN_CAMERA_ID"

# Persistence
ENV_FLEETIQ_DB = "FLEETIQ_DB"

# Deployment / exposure hardening
ENV_ENVIRONMENT = "FLEETIQ_ENV"
ENV_CORS_ORIGINS = "FLEETIQ_CORS_ORIGINS"
ENV_REQUIRE_AUTH_READS = "FLEETIQ_REQUIRE_AUTH_READS"
ENV_ALLOW_INSECURE = "FLEETIQ_ALLOW_INSECURE_STARTUP"


# ---------------------------------------------------------------------------
# Default values (preserved for backward compatibility)
# ---------------------------------------------------------------------------

DEFAULT_SESSION_TTL_HOURS = 12.0
DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_PASSWORD = "admin123"
DEFAULT_CABIN_INFERENCE_INTERVAL_SEC = 2.0
DEFAULT_CABIN_DEFAULT_CAPACITY = 40
DEFAULT_CAMERA_BUS_ID = "PROTO-001"
DEFAULT_ENVIRONMENT = "development"

_TRUE_VALUES = ("1", "true", "yes", "on")


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE_VALUES


def _parse_origins(raw: Optional[str]) -> tuple:
    """Parse a comma-separated allowlist of exact origins."""
    if not raw:
        return ()
    return tuple(o.strip().rstrip("/") for o in raw.split(",") if o.strip())


# ---------------------------------------------------------------------------
# Server configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ServerConfig:
    """Server port and host configuration."""
    host: str = "127.0.0.1"
    api_port: int = 5001
    websocket_port: int = 8765
    enable_websocket: bool = True
    start_mode: str = "simulation"


# ---------------------------------------------------------------------------
# Authentication configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AuthConfig:
    """Authentication and authorization settings."""
    admin_user: str = field(default_factory=lambda: os.environ.get(ENV_ADMIN_USER, DEFAULT_ADMIN_USER))
    admin_password: str = field(default_factory=lambda: os.environ.get(ENV_ADMIN_PASSWORD, DEFAULT_ADMIN_PASSWORD))
    session_ttl_hours: float = field(default_factory=lambda: float(os.environ.get(ENV_SESSION_TTL_HOURS, DEFAULT_SESSION_TTL_HOURS)))
    
    @property
    def using_default_password(self) -> bool:
        return ENV_ADMIN_PASSWORD not in os.environ


# ---------------------------------------------------------------------------
# Camera configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CameraSlotConfig:
    """Configuration for a single camera slot."""
    env_var: str
    default_device: str
    
    @property
    def device(self) -> str:
        return os.environ.get(self.env_var, self.default_device)
    
    @property
    def enabled(self) -> bool:
        device = self.device.lower()
        return device not in ("none", "off", "")


@dataclass(frozen=True)
class CameraConfig:
    """Multi-camera configuration."""
    driver: CameraSlotConfig = field(default_factory=lambda: CameraSlotConfig(
        env_var=ENV_DRIVER_CAMERA_DEVICE, default_device="0"
    ))
    cabin: CameraSlotConfig = field(default_factory=lambda: CameraSlotConfig(
        env_var=ENV_CABIN_CAMERA_DEVICE, default_device="1"
    ))
    road: CameraSlotConfig = field(default_factory=lambda: CameraSlotConfig(
        env_var=ENV_ROAD_CAMERA_DEVICE, default_device="0"
    ))
    bus_id: str = field(default_factory=lambda: os.environ.get(ENV_CAMERA_BUS_ID, DEFAULT_CAMERA_BUS_ID))


# ---------------------------------------------------------------------------
# Cabin occupancy configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CabinConfig:
    """Cabin occupancy intelligence configuration."""
    inference_interval_sec: float = field(default_factory=lambda: float(
        os.environ.get(ENV_CABIN_INFERENCE_INTERVAL_SEC, DEFAULT_CABIN_INFERENCE_INTERVAL_SEC)
    ))
    default_capacity: int = field(default_factory=lambda: int(
        os.environ.get(ENV_CABIN_DEFAULT_CAPACITY, DEFAULT_CABIN_DEFAULT_CAPACITY)
    ))
    model_path: Optional[str] = field(default_factory=lambda: os.environ.get(ENV_CABIN_MODEL_PATH))
    camera_id: str = field(default_factory=lambda: os.environ.get(ENV_CABIN_CAMERA_ID, "CAM-CAB-001"))
    
    @property
    def model_available(self) -> bool:
        if not self.model_path:
            return False
        return os.path.exists(self.model_path)


# ---------------------------------------------------------------------------
# Persistence configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PersistenceConfig:
    """SQLite persistence configuration."""
    db_path: Optional[str] = field(default_factory=lambda: os.environ.get(ENV_FLEETIQ_DB))


# ---------------------------------------------------------------------------
# Exposure / deployment security configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SecurityConfig:
    """Controls how much of the API may be exposed to a network.

    Defaults are the safe local-development posture: no CORS allowlist
    (same-origin only in practice) and open read-only telemetry. Setting
    FLEETIQ_ENV=production flips read endpoints to authenticated-only and
    turns `startup_blockers` into a hard startup failure.
    """
    environment: str = field(default_factory=lambda: (
        os.environ.get(ENV_ENVIRONMENT, DEFAULT_ENVIRONMENT).strip().lower() or DEFAULT_ENVIRONMENT
    ))
    cors_origins: tuple = field(default_factory=lambda: _parse_origins(os.environ.get(ENV_CORS_ORIGINS)))
    require_auth_reads: bool = field(default_factory=lambda: _env_flag(ENV_REQUIRE_AUTH_READS))
    allow_insecure_startup: bool = field(default_factory=lambda: _env_flag(ENV_ALLOW_INSECURE))

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def effective_require_auth_reads(self) -> bool:
        """Authenticated reads: explicit flag wins, else on in production."""
        if os.environ.get(ENV_REQUIRE_AUTH_READS) is not None:
            return self.require_auth_reads
        return self.is_production

    def cors_options(self) -> Optional[dict]:
        """flask-cors options, or None to keep the permissive local default.

        With no allowlist configured, CORS is left at flask-cors' default
        (all origins, no credentials) so local demos and LAN testing keep
        working. In production an allowlist is mandatory, so this returns
        explicit origins rather than '*'.
        """
        if not self.cors_origins:
            return None
        return {
            "origins": list(self.cors_origins),
            "allow_headers": ["Authorization", "Content-Type"],
            "methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            "supports_credentials": False,
            "max_age": 600,
        }

    def startup_blockers(self) -> list:
        """Configuration faults that make a public deployment unsafe."""
        if not self.is_production:
            return []
        blockers = []
        if os.environ.get(ENV_ADMIN_PASSWORD) is None or self._password_is_default():
            blockers.append(
                f"{ENV_ADMIN_PASSWORD} is unset or still the development default; "
                "set a strong per-deployment password"
            )
        if not self.cors_origins:
            blockers.append(
                f"{ENV_CORS_ORIGINS} is empty; set the exact frontend origin(s) "
                "(comma-separated) so no wildcard CORS is served"
            )
        return blockers

    def _password_is_default(self) -> bool:
        return os.environ.get(ENV_ADMIN_PASSWORD, DEFAULT_ADMIN_PASSWORD) == DEFAULT_ADMIN_PASSWORD


# ---------------------------------------------------------------------------
# Application configuration (aggregates all sub-configs)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AppConfig:
    """Top-level application configuration."""
    server: ServerConfig = field(default_factory=ServerConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    camera: CameraConfig = field(default_factory=CameraConfig)
    cabin: CabinConfig = field(default_factory=CabinConfig)
    persistence: PersistenceConfig = field(default_factory=PersistenceConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)


# ---------------------------------------------------------------------------
# Singleton instance
# ---------------------------------------------------------------------------

_config: Optional[AppConfig] = None


def get_config() -> AppConfig:
    """Get the application configuration singleton.
    
    Configuration is read from environment variables at import time.
    This preserves the existing behavior where env vars are read once
    at startup.
    """
    global _config
    if _config is None:
        _config = AppConfig()
    return _config


def reload_config() -> AppConfig:
    """Force reload configuration from environment variables.
    
    Useful for testing or when environment variables change at runtime.
    """
    global _config
    _config = AppConfig()
    return _config


# ---------------------------------------------------------------------------
# Convenience accessors (backward compatibility)
# ---------------------------------------------------------------------------

def get_admin_user() -> str:
    return get_config().auth.admin_user


def get_admin_password() -> str:
    return get_config().auth.admin_password


def get_session_ttl_hours() -> float:
    return get_config().auth.session_ttl_hours


def get_camera_bus_id() -> str:
    return get_config().camera.bus_id


def get_cabin_default_capacity() -> int:
    return get_config().cabin.default_capacity


def get_cabin_inference_interval() -> float:
    return get_config().cabin.inference_interval_sec


def get_cabin_model_path() -> Optional[str]:
    return get_config().cabin.model_path


def get_db_path() -> Optional[str]:
    return get_config().persistence.db_path


def get_security_config() -> SecurityConfig:
    return get_config().security
