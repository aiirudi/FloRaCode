from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DirectoryTree, Input, Label, RadioButton, RadioSet, Static


class WorkspaceSetupScreen(ModalScreen[tuple[str, str] | None]):
    """Choose the directory and sandbox mode before opening a chat session."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]
    DEFAULT_CSS = """
    WorkspaceSetupScreen {
        align: center middle;
        background: $background 80%;
    }
    #workspace-dialog {
        width: 88;
        max-width: 96%;
        height: 30;
        max-height: 94%;
        padding: 1 2;
        border: round $accent;
        background: $surface;
    }
    #workspace-title {
        height: 1;
        text-style: bold;
        color: $accent;
    }
    #workspace-help {
        height: 2;
        color: $text-muted;
    }
    #workspace-path {
        width: 1fr;
    }
    #workspace-navigation {
        height: 3;
    }
    #workspace-navigation Button {
        margin-left: 1;
        min-width: 7;
    }
    #workspace-tree {
        height: 1fr;
        border: round $surface-lighten-2;
        background: $background;
    }
    #workspace-mode-label {
        height: 1;
        margin-top: 1;
        text-style: bold;
    }
    #workspace-modes {
        height: 3;
        layout: horizontal;
        border: none;
        padding: 0;
    }
    #workspace-modes RadioButton {
        width: 1fr;
    }
    #workspace-error {
        height: 1;
        color: $error;
    }
    #workspace-actions {
        height: 3;
        align-horizontal: right;
    }
    #workspace-actions Button {
        margin-left: 1;
    }
    """

    _MODES = {
        "mode-off": "off",
        "mode-read-only": "read_only",
        "mode-workspace-write": "workspace_write",
    }

    def __init__(self, initial_workspace: str | Path, initial_mode: str = "off") -> None:
        super().__init__()
        self.initial_workspace = str(Path(initial_workspace).resolve())
        self.initial_mode = initial_mode if initial_mode in self._MODES.values() else "off"

    def compose(self) -> ComposeResult:
        with Vertical(id="workspace-dialog"):
            yield Label("Set up your workspace", id="workspace-title")
            yield Static(
                "Choose a folder, then select what the assistant can change.",
                id="workspace-help",
            )
            with Horizontal(id="workspace-navigation"):
                yield Input(value=self.initial_workspace, id="workspace-path")
                yield Button("Up", id="workspace-up")
                yield Button("Go", id="workspace-go")
            yield DirectoryTree(self.initial_workspace, id="workspace-tree")
            yield Label("Sandbox mode", id="workspace-mode-label")
            yield RadioSet(
                RadioButton("Off", value=self.initial_mode == "off", id="mode-off"),
                RadioButton(
                    "Read only", value=self.initial_mode == "read_only", id="mode-read-only"
                ),
                RadioButton(
                    "Workspace write",
                    value=self.initial_mode == "workspace_write",
                    id="mode-workspace-write",
                ),
                id="workspace-modes",
            )
            yield Static("", id="workspace-error")
            with Horizontal(id="workspace-actions"):
                yield Button("Start with defaults", id="workspace-default")
                yield Button("Cancel", id="workspace-cancel")
                yield Button("Start chat", variant="primary", id="workspace-confirm")

    def on_mount(self) -> None:
        path_input = self.query_one("#workspace-path", Input)
        path_input.focus()
        path_input.cursor_position = 0

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        self.query_one("#workspace-path", Input).value = str(event.path.resolve())
        self._clear_error()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "workspace-up":
            tree = self.query_one("#workspace-tree", DirectoryTree)
            parent = Path(tree.path).parent
            tree.path = parent
            self.query_one("#workspace-path", Input).value = str(parent)
            self._clear_error()
        elif button_id == "workspace-go":
            directory = self._valid_directory()
            if directory is not None:
                self.query_one("#workspace-tree", DirectoryTree).path = directory
                self.query_one("#workspace-path", Input).value = str(directory)
        elif button_id == "workspace-confirm":
            directory = self._valid_directory()
            if directory is not None:
                modes = self.query_one("#workspace-modes", RadioSet)
                pressed = modes.pressed_button
                mode_id = pressed.id if pressed is not None else None
                mode = self._MODES.get(mode_id or "", "off")
                self.dismiss((str(directory), mode))
        elif button_id == "workspace-default":
            self.dismiss((self.initial_workspace, "off"))
        elif button_id == "workspace-cancel":
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _valid_directory(self) -> Path | None:
        raw_path = self.query_one("#workspace-path", Input).value.strip()
        try:
            directory = Path(raw_path)
            if not raw_path or not directory.is_absolute() or not directory.is_dir():
                raise ValueError("invalid workspace directory")
            resolved = directory.resolve()
        except (OSError, ValueError):
            self.query_one("#workspace-error", Static).update(
                "Enter an existing absolute directory path."
            )
            return None
        self._clear_error()
        return resolved

    def _clear_error(self) -> None:
        self.query_one("#workspace-error", Static).update("")
