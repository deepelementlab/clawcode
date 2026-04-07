"""
LSP Manager - Manages multiple language server instances.

This module provides the LSPManager class for managing multiple LSP clients
for different programming languages.
"""

import asyncio
import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Union

from .client import LSPClient, ServerState, ServerType
from .types import Diagnostic, LanguageKind


logger = logging.getLogger(__name__)


@dataclass
class LanguageServerConfig:
    """Configuration for a language server."""
    name: str
    command: str
    args: List[str] = field(default_factory=list)
    file_extensions: List[str] = field(default_factory=list)
    enabled: bool = True
    initialization_options: Optional[Dict[str, Any]] = None
    timeout: float = 30.0

    def __post_init__(self):
        """Normalize file extensions to lowercase without dots."""
        self.file_extensions = [
            ext.lower().lstrip(".") for ext in self.file_extensions
        ]


# Default language server configurations
DEFAULT_SERVERS: Dict[str, LanguageServerConfig] = {
    # --- Systems / compiled languages ---
    "python": LanguageServerConfig(
        name="Python",
        command="pylsp",
        args=[],
        file_extensions=["py", "pyi", "pyw"],
    ),
    "go": LanguageServerConfig(
        name="Go",
        command="gopls",
        args=["serve"],
        file_extensions=["go", "mod", "sum"],
    ),
    "typescript": LanguageServerConfig(
        name="TypeScript",
        command="typescript-language-server",
        args=["--stdio"],
        file_extensions=["ts", "tsx", "js", "jsx", "mjs", "cjs"],
    ),
    "rust": LanguageServerConfig(
        name="Rust",
        command="rust-analyzer",
        args=[],
        file_extensions=["rs"],
    ),
    "java": LanguageServerConfig(
        name="Java",
        command="jdtls",
        args=[],
        file_extensions=["java"],
    ),
    "c": LanguageServerConfig(
        name="C/C++",
        command="clangd",
        args=[],
        file_extensions=["c", "cpp", "cc", "cxx", "h", "hpp", "hxx", "m", "mm"],
    ),
    "csharp": LanguageServerConfig(
        name="C#",
        command="omnisharp",
        args=["-lsp"],
        file_extensions=["cs", "csx"],
    ),
    "kotlin": LanguageServerConfig(
        name="Kotlin",
        command="kotlin-language-server",
        args=[],
        file_extensions=["kt", "kts"],
    ),
    "scala": LanguageServerConfig(
        name="Scala",
        command="metals",
        args=[],
        file_extensions=["scala", "sbt", "sc"],
    ),
    "swift": LanguageServerConfig(
        name="Swift",
        command="sourcekit-lsp",
        args=[],
        file_extensions=["swift"],
    ),
    "dart": LanguageServerConfig(
        name="Dart",
        command="dart",
        args=["language-server", "--protocol=lsp"],
        file_extensions=["dart"],
    ),
    "zig": LanguageServerConfig(
        name="Zig",
        command="zls",
        args=[],
        file_extensions=["zig"],
    ),
    # --- Scripting languages ---
    "ruby": LanguageServerConfig(
        name="Ruby",
        command="solargraph",
        args=["stdio"],
        file_extensions=["rb", "rake", "gemspec"],
    ),
    "php": LanguageServerConfig(
        name="PHP",
        command="intelephense",
        args=["--stdio"],
        file_extensions=["php", "phtml"],
    ),
    "lua": LanguageServerConfig(
        name="Lua",
        command="lua-language-server",
        args=[],
        file_extensions=["lua"],
    ),
    "perl": LanguageServerConfig(
        name="Perl",
        command="perlnavigator",
        args=["--stdio"],
        file_extensions=["pl", "pm", "t"],
    ),
    "r": LanguageServerConfig(
        name="R",
        command="R",
        args=["--slave", "-e", "languageserver::run()"],
        file_extensions=["r", "rmd"],
    ),
    # --- Functional languages ---
    "haskell": LanguageServerConfig(
        name="Haskell",
        command="haskell-language-server-wrapper",
        args=["--lsp"],
        file_extensions=["hs", "lhs"],
    ),
    "elixir": LanguageServerConfig(
        name="Elixir",
        command="elixir-ls",
        args=[],
        file_extensions=["ex", "exs", "heex", "leex"],
    ),
    "erlang": LanguageServerConfig(
        name="Erlang",
        command="erlang_ls",
        args=[],
        file_extensions=["erl", "hrl"],
    ),
    "ocaml": LanguageServerConfig(
        name="OCaml",
        command="ocamllsp",
        args=[],
        file_extensions=["ml", "mli"],
    ),
    "clojure": LanguageServerConfig(
        name="Clojure",
        command="clojure-lsp",
        args=[],
        file_extensions=["clj", "cljs", "cljc", "edn"],
    ),
    # --- Web / frontend frameworks ---
    "html": LanguageServerConfig(
        name="HTML",
        command="vscode-html-language-server",
        args=["--stdio"],
        file_extensions=["html", "htm"],
    ),
    "css": LanguageServerConfig(
        name="CSS",
        command="vscode-css-language-server",
        args=["--stdio"],
        file_extensions=["css", "scss", "less"],
    ),
    "vue": LanguageServerConfig(
        name="Vue",
        command="vue-language-server",
        args=["--stdio"],
        file_extensions=["vue"],
    ),
    "svelte": LanguageServerConfig(
        name="Svelte",
        command="svelteserver",
        args=["--stdio"],
        file_extensions=["svelte"],
    ),
    # --- Data / config languages ---
    "json": LanguageServerConfig(
        name="JSON",
        command="vscode-json-language-server",
        args=["--stdio"],
        file_extensions=["json", "jsonc"],
    ),
    "yaml": LanguageServerConfig(
        name="YAML",
        command="yaml-language-server",
        args=["--stdio"],
        file_extensions=["yaml", "yml"],
    ),
    "toml": LanguageServerConfig(
        name="TOML",
        command="taplo",
        args=["lsp", "stdio"],
        file_extensions=["toml"],
    ),
    "sql": LanguageServerConfig(
        name="SQL",
        command="sqls",
        args=[],
        file_extensions=["sql"],
    ),
    "graphql": LanguageServerConfig(
        name="GraphQL",
        command="graphql-lsp",
        args=["server", "-m", "stream"],
        file_extensions=["graphql", "gql"],
    ),
    # --- Shell / scripting ---
    "bash": LanguageServerConfig(
        name="Bash",
        command="bash-language-server",
        args=["start"],
        file_extensions=["sh", "bash", "zsh"],
    ),
    "powershell": LanguageServerConfig(
        name="PowerShell",
        command="pwsh",
        args=["-NoLogo", "-NoProfile", "-Command", "Import-Module PowerShellEditorServices; Start-EditorServices -Stdio"],
        file_extensions=["ps1", "psm1", "psd1"],
    ),
    # --- Infrastructure / DevOps ---
    "terraform": LanguageServerConfig(
        name="Terraform",
        command="terraform-ls",
        args=["serve"],
        file_extensions=["tf", "tfvars"],
    ),
    "dockerfile": LanguageServerConfig(
        name="Dockerfile",
        command="docker-langserver",
        args=["--stdio"],
        file_extensions=["dockerfile"],
    ),
    "protobuf": LanguageServerConfig(
        name="Protobuf",
        command="buf",
        args=["beta", "lsp"],
        file_extensions=["proto"],
    ),
    # --- Documentation ---
    "markdown": LanguageServerConfig(
        name="Markdown",
        command="marksman",
        args=["server"],
        file_extensions=["md", "markdown"],
    ),
    "latex": LanguageServerConfig(
        name="LaTeX",
        command="texlab",
        args=[],
        file_extensions=["tex", "bib", "sty", "cls"],
    ),
}


class LSPManager:
    """
    Manager for multiple LSP clients.

    This class manages multiple language server instances, automatically
    selecting the appropriate server based on file extensions.
    """

    def __init__(
        self,
        workspace_dir: Optional[str] = None,
        servers: Optional[Dict[str, LanguageServerConfig]] = None,
        auto_start: bool = False,
        debug: bool = False,
    ):
        """
        Initialize the LSP manager.

        Args:
            workspace_dir: The workspace directory path.
            servers: Custom server configurations (merged with defaults).
            auto_start: Whether to auto-start servers when needed.
            debug: Enable debug logging.
        """
        self.workspace_dir = workspace_dir or os.getcwd()
        self.auto_start = auto_start
        self.debug = debug

        # Merge default and custom server configs
        self._server_configs: Dict[str, LanguageServerConfig] = {
            **DEFAULT_SERVERS,
            **(servers or {}),
        }

        # Client instances
        self._clients: Dict[str, LSPClient] = {}
        self._clients_lock = threading.Lock()

        # Extension to server mapping
        self._extension_map: Dict[str, str] = {}
        self._build_extension_map()

        # Initialization state
        self._initialized = False
        self._init_lock = threading.Lock()

        # Diagnostic change callbacks
        self._diagnostic_callbacks: List[Callable[[str, List[Diagnostic]], None]] = []

    def _build_extension_map(self):
        """Build the mapping from file extensions to server names."""
        self._extension_map.clear()
        for name, config in self._server_configs.items():
            if config.enabled:
                for ext in config.file_extensions:
                    self._extension_map[ext] = name

    def register_server(self, config: LanguageServerConfig):
        """
        Register a language server configuration.

        Args:
            config: The server configuration.
        """
        self._server_configs[config.name.lower()] = config
        self._build_extension_map()

    def unregister_server(self, name: str):
        """
        Unregister a language server.

        Args:
            name: The server name.
        """
        self._server_configs.pop(name.lower(), None)
        self._build_extension_map()

    def get_server_for_file(self, file_path: str) -> Optional[str]:
        """
        Get the appropriate server name for a file.

        Args:
            file_path: The file path.

        Returns:
            The server name or None if no server is configured.
        """
        ext = Path(file_path).suffix.lstrip(".").lower()
        return self._extension_map.get(ext)

    def get_client(self, name: str) -> Optional[LSPClient]:
        """
        Get an LSP client by name.

        Args:
            name: The server name.

        Returns:
            The LSP client or None if not running.
        """
        with self._clients_lock:
            return self._clients.get(name.lower())

    def register_diagnostic_callback(
        self, callback: Callable[[str, List[Diagnostic]], None]
    ):
        """
        Register a callback for diagnostic changes.

        Args:
            callback: A function that takes (uri, diagnostics).
        """
        self._diagnostic_callbacks.append(callback)

    def unregister_diagnostic_callback(
        self, callback: Callable[[str, List[Diagnostic]], None]
    ):
        """Unregister a diagnostic callback."""
        try:
            self._diagnostic_callbacks.remove(callback)
        except ValueError:
            pass

    async def start_server(self, name: str) -> Optional[LSPClient]:
        """
        Start a specific language server.

        Args:
            name: The server name.

        Returns:
            The LSP client or None if failed.
        """
        name = name.lower()
        config = self._server_configs.get(name)

        if not config:
            logger.warning(f"No configuration for server: {name}")
            return None

        if not config.enabled:
            logger.debug(f"Server {name} is disabled")
            return None

        with self._clients_lock:
            # Check if already running
            existing = self._clients.get(name)
            if existing and existing.state != ServerState.STOPPED:
                return existing

            # Create new client
            client = LSPClient(
                command=config.command,
                args=config.args,
                debug=self.debug,
            )

            # Register diagnostic callback
            client.register_notification_handler(
                "textDocument/publishDiagnostics",
                lambda params: self._on_diagnostics(name, params)
            )

            self._clients[name] = client

        # Start the server
        if not await client.start():
            logger.error(f"Failed to start server: {name}")
            return None

        # Initialize
        try:
            init_options = config.initialization_options
            await client.initialize(
                self.workspace_dir,
                client_name="clawcode-lsp-manager",
            )
            return client

        except Exception as e:
            logger.error(f"Failed to initialize server {name}: {e}")
            await client.stop()
            return None

    async def stop_server(self, name: str):
        """
        Stop a specific language server.

        Args:
            name: The server name.
        """
        name = name.lower()

        with self._clients_lock:
            client = self._clients.pop(name, None)

        if client:
            await client.stop()

    async def stop_all(self):
        """Stop all running language servers."""
        with self._clients_lock:
            clients = list(self._clients.items())
            self._clients.clear()

        for name, client in clients:
            try:
                await client.stop()
            except Exception as e:
                logger.debug(f"Error stopping server {name}: {e}")

    async def start_for_file(self, file_path: str) -> Optional[LSPClient]:
        """
        Start the appropriate server for a file if not already running.

        Args:
            file_path: The file path.

        Returns:
            The LSP client or None if no server is configured.
        """
        name = self.get_server_for_file(file_path)
        if not name:
            return None

        client = self.get_client(name)
        if client and client.state != ServerState.STOPPED:
            return client

        if self.auto_start:
            return await self.start_server(name)

        return None

    async def open_file(self, file_path: str) -> bool:
        """
        Open a file in the appropriate language server.

        Args:
            file_path: The file path.

        Returns:
            True if successful.
        """
        client = await self.start_for_file(file_path)
        if not client:
            return False

        return await client.open_file(file_path)

    async def close_file(self, file_path: str) -> bool:
        """
        Close a file in its language server.

        Args:
            file_path: The file path.

        Returns:
            True if successful.
        """
        name = self.get_server_for_file(file_path)
        if not name:
            return True

        client = self.get_client(name)
        if not client:
            return True

        return await client.close_file(file_path)

    async def notify_change(self, file_path: str) -> bool:
        """
        Notify that a file has changed.

        Args:
            file_path: The file path.

        Returns:
            True if successful.
        """
        name = self.get_server_for_file(file_path)
        if not name:
            return True

        client = self.get_client(name)
        if not client:
            return True

        return await client.notify_change(file_path)

    def get_diagnostics(
        self, file_path: Optional[str] = None
    ) -> Union[List[Diagnostic], Dict[str, List[Diagnostic]]]:
        """
        Get diagnostics for a file or all files.

        Args:
            file_path: Optional file path. If None, returns all diagnostics.

        Returns:
            List of diagnostics for the file, or dict of all diagnostics.
        """
        if file_path:
            name = self.get_server_for_file(file_path)
            if not name:
                return []

            client = self.get_client(name)
            if not client:
                return []

            return client.get_file_diagnostics(file_path)

        # Collect diagnostics from all clients
        all_diagnostics: Dict[str, List[Diagnostic]] = {}
        with self._clients_lock:
            for client in self._clients.values():
                diagnostics = client.get_diagnostics()
                if isinstance(diagnostics, dict):
                    all_diagnostics.update(diagnostics)

        return all_diagnostics

    async def document_symbols(
        self, file_path: str, *, timeout: float = 5.0
    ) -> List[Dict[str, Any]]:
        """Delegate textDocument/documentSymbol to the appropriate LSP client."""
        client = await self.start_for_file(file_path)
        if not client:
            return []
        if not client.is_file_open(file_path):
            await client.open_file(file_path)
        return await client.document_symbols(file_path, timeout=timeout)

    async def get_diagnostics_for_file(
        self, file_path: str, wait_time: float = 0.1
    ) -> List[Diagnostic]:
        """
        Get diagnostics for a file, opening it if needed.

        Args:
            file_path: The file path.
            wait_time: Time to wait for diagnostics.

        Returns:
            List of diagnostics.
        """
        name = self.get_server_for_file(file_path)
        if not name:
            return []

        client = self.get_client(name)
        if not client:
            if self.auto_start:
                client = await self.start_server(name)
            if not client:
                return []

        return await client.get_diagnostics_for_file(file_path, wait_time)

    def _on_diagnostics(self, server_name: str, params: Any):
        """Handle diagnostics notification from a server."""
        try:
            from .types import PublishDiagnosticsParams

            diag_params = PublishDiagnosticsParams.from_dict(params)
            uri = diag_params.uri
            diagnostics = diag_params.diagnostics

            # Notify callbacks
            for callback in self._diagnostic_callbacks:
                try:
                    callback(uri, diagnostics)
                except Exception as e:
                    logger.debug(f"Error in diagnostic callback: {e}")

        except Exception as e:
            logger.error(f"Error processing diagnostics: {e}")

    @property
    def running_servers(self) -> Set[str]:
        """Get the names of currently running servers."""
        with self._clients_lock:
            return {
                name for name, client in self._clients.items()
                if client.state != ServerState.STOPPED
            }

    @property
    def available_servers(self) -> Dict[str, LanguageServerConfig]:
        """Get all available server configurations."""
        return dict(self._server_configs)

    def is_server_running(self, name: str) -> bool:
        """Check if a specific server is running."""
        client = self.get_client(name)
        return client is not None and client.state != ServerState.STOPPED

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.stop_all()
        return False


# Utility function for quick diagnostics
async def get_file_diagnostics(
    file_path: str,
    workspace_dir: Optional[str] = None,
    server_name: Optional[str] = None,
) -> List[Diagnostic]:
    """
    Get diagnostics for a file.

    This is a convenience function that creates a temporary LSPManager
    to get diagnostics for a single file.

    Args:
        file_path: The file path.
        workspace_dir: Optional workspace directory.
        server_name: Optional server name to use.

    Returns:
        List of diagnostics.
    """
    workspace_dir = workspace_dir or os.path.dirname(file_path)

    async with LSPManager(workspace_dir=workspace_dir, auto_start=True) as manager:
        if server_name:
            await manager.start_server(server_name)

        return await manager.get_diagnostics_for_file(file_path)
