"""Configuration settings for TONYAgent using Pydantic."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProviderSettings(BaseModel):
    """Settings for a single API provider."""

    name: str = ""
    api_key: str = ""  # Stored in keyring, not here
    model: str = ""
    base_url: str = ""
    extra_headers: dict[str, str] = Field(default_factory=dict)
    timeout: int = 60
    max_retries: int = 3


class SandboxSettings(BaseModel):
    """Sandbox configuration.

    The defaults are the *restrictive* ones. Isolation flags are on; network is
    OFF, because shell commands do not need egress and an AI-chosen command has
    no business reaching the internet. The browser_* tools are the one feature
    that legitimately needs egress, so they fail with an explicit "enable
    sandbox.enable_network" message rather than silently failing.
    """

    type: Literal["auto", "docker", "windows"] = "auto"
    docker_image: str = "tonyagent/sandbox:latest"
    memory_limit: str = "2g"
    cpu_limit: str = "2.0"
    timeout: int = 300
    enable_network: bool = False
    auto_start: bool = True
    health_check_interval: int = 30

    # --- Container isolation (docker backend) ---
    pids_limit: int = 512
    """Cap on processes/threads. Blocks fork bombs."""

    no_new_privileges: bool = True
    """--security-opt=no-new-privileges: setuid binaries cannot gain rights."""

    drop_capabilities: bool = True
    """--cap-drop=ALL. Disable if Chromium's own sandbox misbehaves."""

    tmpfs_size_mb: int = 256
    """Size of the writable /tmp tmpfs, so scratch space cannot fill the disk."""

    ulimit_nofile: int = 1024
    """Max open file descriptors inside the container."""

    ulimit_nproc: int = 256
    """Max user processes inside the container."""

    workspace_read_only: bool = False
    """Mount /workspace read-only. The agent normally writes via the host-side
    file tools, so this is usually safe to turn on; set False if the agent must
    write files from inside the container."""



class ToolsSettings(BaseModel):
    """Tool system configuration."""

    command_allowlist: list[str] = Field(
        default_factory=lambda: [
            "python",
            "node",
            "npm",
            "pip",
            "git",
            "pytest",
            "playwright",
            "uv",
            "poetry",
        ]
    )
    command_denylist: list[str] = Field(
        default_factory=lambda: [
            r"rm\s+-rf\s+/",
            r"del\s+/s\s+/q",
            r"format\s+[a-z]:",
            r"shutdown",
            r"reboot",
            r"powershell\s+-enc",
            r"curl\s+\|\s*sh",
            r"wget\s+\|\s*sh",
        ]
    )
    confirm_destructive: bool = True
    max_output_size: int = 1048576  # 1MB
    default_timeout: int = 30
    fallback_to_local: bool = False
    """Allow host execution when the sandbox is not running.

    Default False: sandbox_required tools fail closed with a clear error
    instead of silently running on the host. Set True (or
    TONYAGENT_TOOLS__FALLBACK_TO_LOCAL=true) for offline/dev use.
    """

    allow_internal_http: bool = False
    """Allow http_request to reach loopback/private/link-local addresses.

    Default False. This is an SSRF guard and is deliberately INDEPENDENT of
    sandbox.enable_network - that setting controls the container's egress, not
    what the host can be asked to fetch. Reaching 169.254.169.254 (cloud
    instance metadata) can hand out cloud credentials, so it stays blocked
    unless you opt in. Set TONYAGENT_TOOLS__ALLOW_INTERNAL_HTTP=true to enable.
    """


class LoggingSettings(BaseModel):
    """Logging configuration."""

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    file_max_mb: int = 10
    file_count: int = 5
    json_format: bool = False


class FolderSettings(BaseModel):
    """Folder management settings."""

    current: str = ""
    recent: list[str] = Field(default_factory=list)
    lock_on_generation: bool = True
    max_recent: int = 10


class UISettings(BaseModel):
    """UI configuration."""

    theme: Literal["light", "dark", "system"] = "system"
    language: str = "en"
    font_size: int = 13
    show_token_count: bool = True
    auto_scroll: bool = True
    compact_mode: bool = False


class Settings(BaseSettings):
    """Main application settings."""

    model_config = SettingsConfigDict(
        env_prefix="TONYAGENT_",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    provider: ProviderSettings = Field(default_factory=ProviderSettings)
    sandbox: SandboxSettings = Field(default_factory=SandboxSettings)
    tools: ToolsSettings = Field(default_factory=ToolsSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    folder: FolderSettings = Field(default_factory=FolderSettings)
    ui: UISettings = Field(default_factory=UISettings)

    @field_validator("folder", mode="before")
    @classmethod
    def validate_folder_recent(cls, v: dict[str, Any] | FolderSettings) -> FolderSettings:
        if isinstance(v, dict):
            recent = v.get("recent", [])
            if len(recent) > 10:
                v["recent"] = recent[-10:]
        return v

    def get_config_dir(self) -> Path:
        """Get the configuration directory."""
        if os.name == "nt":
            base = Path(os.environ.get("APPDATA", "")) / "TONYAgent"
        else:
            base = Path.home() / ".config" / "tonyagent"
        base.mkdir(parents=True, exist_ok=True)
        return base

    def get_logs_dir(self) -> Path:
        """Get the logs directory."""
        log_dir = self.get_config_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir

    def get_chats_dir(self, project_hash: str) -> Path:
        """Get the chat history directory for a project."""
        chat_dir = self.get_config_dir() / "chats" / project_hash
        chat_dir.mkdir(parents=True, exist_ok=True)
        return chat_dir

    def get_sandbox_artifacts_dir(self, project_path: Path) -> Path:
        """Get the sandbox artifacts directory within the project."""
        artifacts_dir = project_path / ".tonyagent" / "sandbox"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        return artifacts_dir


# Global settings instance
settings = Settings()