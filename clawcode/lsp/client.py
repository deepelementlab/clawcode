"""
LSP Client - Language Server Protocol client implementation.

This module provides the LSPClient class for communicating with
language servers using stdio transport.
"""

import asyncio
import json
import os
import sys
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union
import logging

from .types import (
    Diagnostic,
    DidOpenTextDocumentParams,
    DidChangeTextDocumentParams,
    DidCloseTextDocumentParams,
    InitializeParams,
    InitializeResult,
    ClientCapabilities,
    WorkspaceClientCapabilities,
    TextDocumentClientCapabilities,
    TextDocumentSyncClientCapabilities,
    PublishDiagnosticsClientCapabilities,
    WorkspaceFolder,
    ClientInfo,
    TextDocumentItem,
    TextDocumentIdentifier,
    VersionedTextDocumentIdentifier,
    TextDocumentContentChangeEvent,
    PublishDiagnosticsParams,
    Message,
    ResponseError,
    detect_language_id,
)


logger = logging.getLogger(__name__)


class ServerState(Enum):
    """LSP server state."""
    STARTING = "starting"
    READY = "ready"
    ERROR = "error"
    STOPPED = "stopped"


class ServerType(Enum):
    """Type of LSP server."""
    UNKNOWN = "unknown"
    GO = "go"
    TYPESCRIPT = "typescript"
    PYTHON = "python"
    RUST = "rust"
    GENERIC = "generic"


@dataclass
class OpenFileInfo:
    """Information about an open file."""
    uri: str
    version: int = 1


# Type aliases for handlers
NotificationHandler = Callable[[Any], None]
ServerRequestHandler = Callable[[Any], Any]


class LSPClient:
    """
    LSP Client for communicating with language servers.

    This client uses stdio transport to communicate with language servers
    and supports the core LSP protocol methods.
    """

    def __init__(self, command: str, args: List[str] = None, debug: bool = False):
        """
        Initialize the LSP client.

        Args:
            command: The command to start the language server.
            args: Additional arguments for the command.
            debug: Enable debug logging.
        """
        self.command = command
        self.args = args or []
        self.debug = debug

        # Process management
        self._process: Optional[asyncio.subprocess.Process] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None

        # Request/response handling
        self._next_id = 0
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._request_lock = asyncio.Lock()

        # Handlers
        self._notification_handlers: Dict[str, NotificationHandler] = {}
        self._server_request_handlers: Dict[str, ServerRequestHandler] = {}

        # State management
        self._state = ServerState.STOPPED
        self._state_lock = threading.Lock()

        # Diagnostics cache
        self._diagnostics: Dict[str, List[Diagnostic]] = {}
        self._diagnostics_lock = threading.Lock()

        # Open files tracking
        self._open_files: Dict[str, OpenFileInfo] = {}
        self._open_files_lock = threading.Lock()

        # Server capabilities
        self._server_capabilities: Optional[Any] = None
        self._server_info: Optional[Any] = None

        # Server type detection
        self._server_type = ServerType.UNKNOWN

    @property
    def state(self) -> ServerState:
        """Get the current server state."""
        with self._state_lock:
            return self._state

    @state.setter
    def state(self, value: ServerState):
        """Set the server state."""
        with self._state_lock:
            self._state = value

    @property
    def server_capabilities(self) -> Optional[Any]:
        """Get the server capabilities."""
        return self._server_capabilities

    @property
    def server_info(self) -> Optional[Any]:
        """Get the server info."""
        return self._server_info

    def _detect_server_type(self) -> ServerType:
        """Detect the type of language server based on command."""
        cmd_lower = self.command.lower()

        if "gopls" in cmd_lower:
            return ServerType.GO
        elif any(x in cmd_lower for x in ["typescript", "tsserver", "vtsls"]):
            return ServerType.TYPESCRIPT
        elif any(x in cmd_lower for x in ["pyright", "pylsp", "python-lsp", "ruff"]):
            return ServerType.PYTHON
        elif "rust-analyzer" in cmd_lower:
            return ServerType.RUST
        else:
            return ServerType.GENERIC

    async def start(self) -> bool:
        """
        Start the LSP server process.

        Returns:
            True if the server started successfully.
        """
        try:
            # Create subprocess
            full_cmd = [self.command] + self.args
            if self.debug:
                logger.debug(f"Starting LSP server: {' '.join(full_cmd)}")

            self._process = await asyncio.create_subprocess_exec(
                *full_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            self.state = ServerState.STARTING
            self._server_type = self._detect_server_type()

            # Start reader task
            self._reader_task = asyncio.create_task(self._read_messages())

            # Start stderr reader task
            self._stderr_task = asyncio.create_task(self._read_stderr())

            return True

        except Exception as e:
            logger.error(f"Failed to start LSP server: {e}")
            self.state = ServerState.ERROR
            return False

    async def stop(self):
        """Stop the LSP server process."""
        if self._process is None:
            return

        try:
            # Try graceful shutdown
            await self.shutdown()

            # Close stdin to signal exit
            if self._process.stdin:
                self._process.stdin.close()
                try:
                    await self._process.stdin.wait_closed()
                except Exception:
                    pass

            # Wait for process to exit with timeout
            try:
                await asyncio.wait_for(self._process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                # Force kill if needed
                self._process.kill()
                try:
                    await self._process.wait()
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"Error stopping LSP server: {e}")
        finally:
            self._process = None
            self.state = ServerState.STOPPED

            # Cancel reader tasks
            if self._reader_task:
                self._reader_task.cancel()
                self._reader_task = None
            if self._stderr_task:
                self._stderr_task.cancel()
                self._stderr_task = None

    async def _read_stderr(self):
        """Read and log stderr output from the server."""
        if not self._process or not self._process.stderr:
            return

        try:
            while True:
                line = await self._process.stderr.readline()
                if not line:
                    break
                if self.debug:
                    logger.debug(f"LSP stderr: {line.decode('utf-8', errors='replace').strip()}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            if self.debug:
                logger.debug(f"Error reading stderr: {e}")

    async def _read_messages(self):
        """Read and dispatch messages from the server."""
        if not self._process or not self._process.stdout:
            return

        try:
            while True:
                message = await self._read_message()
                if message is None:
                    break

                await self._handle_message(message)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error reading messages: {e}")
            self.state = ServerState.ERROR

    async def _read_message(self) -> Optional[Message]:
        """Read a single LSP message from the server."""
        if not self._process or not self._process.stdout:
            return None

        try:
            # Read headers
            content_length = 0
            while True:
                line = await self._process.stdout.readline()
                if not line:
                    return None

                line_str = line.decode("utf-8").strip()
                if not line_str:
                    break

                if line_str.lower().startswith("content-length:"):
                    content_length = int(line_str.split(":", 1)[1].strip())

            if content_length == 0:
                return None

            # Read content
            content = await self._process.stdout.readexactly(content_length)
            data = json.loads(content.decode("utf-8"))

            return Message.from_dict(data)

        except asyncio.IncompleteReadError:
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse message: {e}")
            return None
        except Exception as e:
            logger.error(f"Error reading message: {e}")
            return None

    async def _handle_message(self, message: Message):
        """Handle an incoming message from the server."""
        # Server request (has method and id)
        if message.method and message.id is not None:
            await self._handle_server_request(message)
            return

        # Notification (has method but no id)
        if message.method:
            await self._handle_notification(message)
            return

        # Response to our request (has id but no method)
        if message.id is not None:
            await self._handle_response(message)

    async def _handle_server_request(self, message: Message):
        """Handle a request from the server."""
        handler = self._server_request_handlers.get(message.method)

        response = Message(id=message.id)

        if handler:
            try:
                result = handler(message.params)
                if asyncio.iscoroutine(result):
                    result = await result
                response.result = result
            except Exception as e:
                response.error = ResponseError(code=-32603, message=str(e))
        else:
            response.error = ResponseError(
                code=-32601,
                message=f"Method not found: {message.method}"
            )

        await self._send_message(response)

    async def _handle_notification(self, message: Message):
        """Handle a notification from the server."""
        handler = self._notification_handlers.get(message.method)

        if handler:
            try:
                result = handler(message.params)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"Error in notification handler for {message.method}: {e}")
        elif self.debug:
            logger.debug(f"No handler for notification: {message.method}")

    async def _handle_response(self, message: Message):
        """Handle a response to our request."""
        future = self._pending_requests.pop(message.id, None)

        if future and not future.done():
            if message.error:
                future.set_exception(
                    Exception(f"{message.error.message} (code: {message.error.code})")
                )
            else:
                future.set_result(message.result)
        elif self.debug:
            logger.debug(f"Received response for unknown request: {message.id}")

    async def _send_message(self, message: Message) -> bool:
        """
        Send a message to the server.

        Args:
            message: The message to send.

        Returns:
            True if the message was sent successfully.
        """
        if not self._process or not self._process.stdin:
            return False

        try:
            content = message.to_json().encode("utf-8")
            header = f"Content-Length: {len(content)}\r\n\r\n".encode("utf-8")

            self._process.stdin.write(header + content)
            await self._process.stdin.drain()

            if self.debug:
                logger.debug(f"Sent message: method={message.method}, id={message.id}")

            return True

        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            return False

    async def call(
        self, method: str, params: Any = None, timeout: float = 30.0
    ) -> Any:
        """
        Make a request to the server and wait for the response.

        Args:
            method: The method name.
            params: The request parameters.
            timeout: Timeout in seconds.

        Returns:
            The response result.

        Raises:
            Exception: If the request fails or times out.
        """
        async with self._request_lock:
            self._next_id += 1
            request_id = self._next_id

        message = Message(id=request_id, method=method, params=params)

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_requests[request_id] = future

        try:
            if not await self._send_message(message):
                raise Exception("Failed to send request")

            return await asyncio.wait_for(future, timeout=timeout)

        except asyncio.TimeoutError:
            self._pending_requests.pop(request_id, None)
            raise Exception(f"Request {method} timed out")
        except Exception:
            self._pending_requests.pop(request_id, None)
            raise

    async def notify(self, method: str, params: Any = None) -> bool:
        """
        Send a notification to the server.

        Args:
            method: The method name.
            params: The notification parameters.

        Returns:
            True if the notification was sent successfully.
        """
        message = Message(method=method, params=params)
        return await self._send_message(message)

    def register_notification_handler(self, method: str, handler: NotificationHandler):
        """Register a handler for a notification method."""
        self._notification_handlers[method] = handler

    def unregister_notification_handler(self, method: str):
        """Unregister a notification handler."""
        self._notification_handlers.pop(method, None)

    def register_server_request_handler(
        self, method: str, handler: ServerRequestHandler
    ):
        """Register a handler for a server request method."""
        self._server_request_handlers[method] = handler

    def unregister_server_request_handler(self, method: str):
        """Unregister a server request handler."""
        self._server_request_handlers.pop(method, None)

    # LSP Protocol Methods

    async def initialize(
        self,
        workspace_dir: str,
        client_name: str = "clawcode-lsp-client",
        client_version: str = "0.1.0",
    ) -> InitializeResult:
        """
        Initialize the LSP connection.

        Args:
            workspace_dir: The workspace directory path.
            client_name: The client name.
            client_version: The client version.

        Returns:
            The initialization result.
        """
        workspace_uri = f"file://{Path(workspace_dir).absolute()}"

        params = InitializeParams(
            process_id=os.getpid(),
            client_info=ClientInfo(name=client_name, version=client_version),
            root_path=workspace_dir,
            root_uri=workspace_uri,
            capabilities=ClientCapabilities(
                workspace=WorkspaceClientCapabilities(
                    configuration=True,
                    did_change_watched_files={"dynamicRegistration": True, "relativePatternSupport": True},
                ),
                text_document=TextDocumentClientCapabilities(
                    synchronization=TextDocumentSyncClientCapabilities(
                        dynamic_registration=True,
                        did_save=True,
                    ),
                    publish_diagnostics=PublishDiagnosticsClientCapabilities(
                        version_support=True,
                    ),
                ),
            ),
            workspace_folders=[
                WorkspaceFolder(uri=workspace_uri, name=workspace_dir)
            ],
        )

        result = await self.call("initialize", params.to_dict())

        init_result = InitializeResult.from_dict(result)
        self._server_capabilities = init_result.capabilities
        self._server_info = init_result.server_info

        # Register default handlers
        self.register_notification_handler(
            "textDocument/publishDiagnostics",
            self._handle_publish_diagnostics
        )
        self.register_notification_handler(
            "window/showMessage",
            self._handle_show_message
        )
        self.register_server_request_handler(
            "workspace/configuration",
            self._handle_workspace_configuration
        )
        self.register_server_request_handler(
            "client/registerCapability",
            self._handle_register_capability
        )

        # Send initialized notification
        await self.notify("initialized", {})

        self.state = ServerState.READY
        return init_result

    async def shutdown(self):
        """Send shutdown request to the server."""
        try:
            await self.call("shutdown", None, timeout=5.0)
        except Exception as e:
            logger.debug(f"Shutdown error: {e}")

        try:
            await self.notify("exit")
        except Exception as e:
            logger.debug(f"Exit notification error: {e}")

    async def open_file(self, file_path: str) -> bool:
        """
        Open a file in the LSP server.

        Args:
            file_path: The file path.

        Returns:
            True if successful.
        """
        uri = f"file://{Path(file_path).absolute()}"

        # Check if already open
        with self._open_files_lock:
            if uri in self._open_files:
                return True

        try:
            content = Path(file_path).read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to read file {file_path}: {e}")
            return False

        language_id = detect_language_id(file_path)

        params = DidOpenTextDocumentParams(
            text_document=TextDocumentItem(
                uri=uri,
                language_id=language_id,
                version=1,
                text=content,
            )
        )

        if not await self.notify("textDocument/didOpen", params.to_dict()):
            return False

        with self._open_files_lock:
            self._open_files[uri] = OpenFileInfo(uri=uri, version=1)

        return True

    async def close_file(self, file_path: str) -> bool:
        """
        Close a file in the LSP server.

        Args:
            file_path: The file path.

        Returns:
            True if successful.
        """
        uri = f"file://{Path(file_path).absolute()}"

        with self._open_files_lock:
            if uri not in self._open_files:
                return True

        params = DidCloseTextDocumentParams(
            text_document=TextDocumentIdentifier(uri=uri)
        )

        if not await self.notify("textDocument/didClose", params.to_dict()):
            return False

        with self._open_files_lock:
            self._open_files.pop(uri, None)

        return True

    async def notify_change(self, file_path: str) -> bool:
        """
        Notify the server that a file has changed.

        Args:
            file_path: The file path.

        Returns:
            True if successful.
        """
        uri = f"file://{Path(file_path).absolute()}"

        with self._open_files_lock:
            file_info = self._open_files.get(uri)
            if not file_info:
                return False
            file_info.version += 1
            version = file_info.version

        try:
            content = Path(file_path).read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to read file {file_path}: {e}")
            return False

        params = DidChangeTextDocumentParams(
            text_document=VersionedTextDocumentIdentifier(uri=uri, version=version),
            content_changes=[
                TextDocumentContentChangeEvent(text=content)
            ]
        )

        return await self.notify("textDocument/didChange", params.to_dict())

    def is_file_open(self, file_path: str) -> bool:
        """Check if a file is open in the LSP server."""
        uri = f"file://{Path(file_path).absolute()}"
        with self._open_files_lock:
            return uri in self._open_files

    async def close_all_files(self):
        """Close all open files."""
        with self._open_files_lock:
            file_paths = list(self._open_files.keys())

        for uri in file_paths:
            # Convert URI back to file path
            file_path = uri[7:] if uri.startswith("file://") else uri  # Remove file:// prefix
            try:
                await self.close_file(file_path)
            except Exception as e:
                logger.debug(f"Error closing file {file_path}: {e}")

    def get_diagnostics(self, uri: Optional[str] = None) -> Union[List[Diagnostic], Dict[str, List[Diagnostic]]]:
        """
        Get diagnostics for a specific file or all files.

        Args:
            uri: Optional file URI. If None, returns all diagnostics.

        Returns:
            List of diagnostics for the file, or dict of all diagnostics.
        """
        with self._diagnostics_lock:
            if uri:
                return self._diagnostics.get(uri, [])
            return dict(self._diagnostics)

    def get_file_diagnostics(self, file_path: str) -> List[Diagnostic]:
        """
        Get diagnostics for a specific file path.

        Args:
            file_path: The file path.

        Returns:
            List of diagnostics.
        """
        uri = f"file://{Path(file_path).absolute()}"
        return self.get_diagnostics(uri)

    async def get_diagnostics_for_file(
        self, file_path: str, wait_time: float = 0.1
    ) -> List[Diagnostic]:
        """
        Open a file if needed and get its diagnostics.

        Args:
            file_path: The file path.
            wait_time: Time to wait for diagnostics after opening.

        Returns:
            List of diagnostics.
        """
        if not self.is_file_open(file_path):
            if not await self.open_file(file_path):
                return []

            # Wait for diagnostics
            await asyncio.sleep(wait_time)

        return self.get_file_diagnostics(file_path)

    async def document_symbols(self, file_path: str, *, timeout: float = 5.0) -> List[Dict[str, Any]]:
        """Request textDocument/documentSymbol for an open file.

        Returns the raw list of DocumentSymbol / SymbolInformation dicts from
        the server, or an empty list on failure.
        """
        uri = f"file://{Path(file_path).absolute()}"
        try:
            result = await self.call(
                "textDocument/documentSymbol",
                {"textDocument": {"uri": uri}},
                timeout=timeout,
            )
            if isinstance(result, list):
                return result
        except Exception as e:
            logger.debug("documentSymbol failed for %s: %s", file_path, e)
        return []

    # Default handlers

    def _handle_publish_diagnostics(self, params: Any):
        """Handle textDocument/publishDiagnostics notification."""
        try:
            diag_params = PublishDiagnosticsParams.from_dict(params)

            with self._diagnostics_lock:
                self._diagnostics[diag_params.uri] = diag_params.diagnostics

            if self.debug:
                logger.debug(
                    f"Received {len(diag_params.diagnostics)} diagnostics for {diag_params.uri}"
                )

        except Exception as e:
            logger.error(f"Error handling publishDiagnostics: {e}")

    def _handle_show_message(self, params: Any):
        """Handle window/showMessage notification."""
        if self.debug:
            message = params.get("message", "") if isinstance(params, dict) else str(params)
            msg_type = params.get("type", 0) if isinstance(params, dict) else 0
            logger.debug(f"Server message (type={msg_type}): {message}")

    def _handle_workspace_configuration(self, params: Any) -> List[Dict[str, Any]]:
        """Handle workspace/configuration request."""
        # Return empty configuration by default
        items = params.get("items", []) if isinstance(params, dict) else []
        return [{} for _ in items]

    def _handle_register_capability(self, params: Any) -> None:
        """Handle client/registerCapability request."""
        if self.debug:
            registrations = params.get("registrations", []) if isinstance(params, dict) else []
            for reg in registrations:
                logger.debug(f"Server registered capability: {reg.get('method', 'unknown')}")
        return None

    async def __aenter__(self):
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.stop()
        return False
