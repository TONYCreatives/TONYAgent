"""Main application class for TONYAgent."""

from __future__ import annotations

import sys
import customtkinter as ctk
from loguru import logger

from tonyagent.config import load_config, save_config, migrate_from_config_file, settings
from tonyagent.utils.logging import setup_logging
from tonyagent.utils.threading import start_ui_queue_processor, stop_ui_queue_processor, shutdown_thread_pool
from tonyagent.ui.theme import theme_manager
from tonyagent.folder.manager import folder_manager
from tonyagent.ui.views.main_window import MainWindow


class TONYAgentApp:
    """Main application class."""

    def __init__(self):
        self.root: ctk.CTk | None = None
        self.main_window: MainWindow | None = None
        self._running = False

    def initialize(self) -> None:
        """Initialize the application."""
        # Setup logging first
        setup_logging()
        logger.info("Starting TONYAgent")

        # Load configuration
        config = load_config()
        migrate_from_config_file(str(settings.get_config_dir() / "config.toml"))

        # Initialize theme
        theme_manager.initialize()

        # Create main window
        self._create_main_window()

        # Start UI queue processor
        start_ui_queue_processor(self.root)

        self._running = True
        logger.info("TONYAgent initialized")

    def _create_main_window(self) -> None:
        """Create the main application window."""
        self.root = ctk.CTk()
        self.root.title("TONYAgent")
        self.root.geometry("1200x800")
        self.root.minsize(900, 600)

        # Set window icon (TODO: add icon file)
        # self.root.iconbitmap("icon.ico")

        # Handle window close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Create main window view
        self.main_window = MainWindow(self.root)

    def _on_close(self) -> None:
        """Handle window close event."""
        logger.info("Shutting down TONYAgent")
        self._running = False

        # Stop UI queue processor
        stop_ui_queue_processor()

        # Shutdown thread pool
        shutdown_thread_pool()

        # Save configuration
        try:
            config = {
                "provider": {
                    "name": settings.provider.name,
                    "model": settings.provider.model,
                    "base_url": settings.provider.base_url,
                },
                "custom_provider": {
                    "enabled": settings.custom_provider.enabled,
                    "name": settings.custom_provider.name,
                    "base_url": settings.custom_provider.base_url,
                    "model": settings.custom_provider.model,
                },
                "sandbox": {
                    "type": settings.sandbox.type,
                    "docker_image": settings.sandbox.docker_image,
                    "memory_limit": settings.sandbox.memory_limit,
                    "cpu_limit": settings.sandbox.cpu_limit,
                    "timeout": settings.sandbox.timeout,
                    "enable_network": settings.sandbox.enable_network,
                },
                "tools": {
                    "command_allowlist": settings.tools.command_allowlist,
                    "command_denylist": settings.tools.command_denylist,
                    "confirm_destructive": settings.tools.confirm_destructive,
                    "max_output_size": settings.tools.max_output_size,
                },
                "logging": {
                    "level": settings.logging.level,
                    "file_max_mb": settings.logging.file_max_mb,
                    "file_count": settings.logging.file_count,
                },
                "folder": {
                    "current": settings.folder.current,
                    "recent": settings.folder.recent,
                    "lock_on_generation": settings.folder.lock_on_generation,
                },
                "ui": {
                    "theme": settings.ui.theme,
                    "language": settings.ui.language,
                    "font_size": settings.ui.font_size,
                },
            }
            save_config(config)
        except Exception as e:
            logger.error(f"Failed to save config on exit: {e}")

        # Destroy window
        if self.root:
            self.root.quit()
            self.root.destroy()

    def run(self) -> None:
        """Run the application main loop."""
        if not self.root:
            raise RuntimeError("Application not initialized. Call initialize() first.")

        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        except Exception as e:
            logger.exception(f"Application error: {e}")
            raise
        finally:
            if self._running:
                self._on_close()

    def get_root(self) -> ctk.CTk:
        """Get the main window."""
        if not self.root:
            raise RuntimeError("Application not initialized")
        return self.root


def main() -> int:
    """Main entry point."""
    app = TONYAgentApp()
    try:
        app.initialize()
        app.run()
        return 0
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())