from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from textual.app import App
from textual.widgets import DirectoryTree, Input, Static

from flora_claude.tui import __main__ as tui_main
from flora_claude.tui import app as tui_app
from flora_claude.tui.workspace_setup import WorkspaceSetupScreen


class _ScreenHarness(App[None]):
    def __init__(self, workspace: Path, mode: str = "off") -> None:
        super().__init__()
        self.workspace = workspace
        self.mode = mode
        self.selection: tuple[str, str] | None | object = _UNSELECTED

    def on_mount(self) -> None:
        self.push_screen(WorkspaceSetupScreen(self.workspace, self.mode), self._selected)

    def _selected(self, selection: tuple[str, str] | None) -> None:
        self.selection = selection


_UNSELECTED = object()


async def test_directory_tree_click_and_mode_selection(tmp_path: Path) -> None:
    child = tmp_path / "chosen"
    child.mkdir()
    app = _ScreenHarness(tmp_path)

    async with app.run_test(size=(100, 40)) as pilot:
        tree = app.screen.query_one("#workspace-tree", DirectoryTree)
        await pilot.pause()
        # The directory tree opens its root on mount; choose the child by mouse.
        await pilot.click(tree, offset=(8, 2))
        await pilot.pause()
        assert app.screen.query_one("#workspace-path", Input).value == str(child.resolve())

        await pilot.click("#mode-workspace-write")
        await pilot.click("#workspace-confirm")
        await pilot.pause()

    assert app.selection == (str(child.resolve()), "workspace_write")


async def test_parent_go_navigation_and_read_only_mode(tmp_path: Path) -> None:
    child = tmp_path / "child"
    child.mkdir()
    app = _ScreenHarness(child)

    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.click("#workspace-up")
        path_input = app.screen.query_one("#workspace-path", Input)
        assert path_input.value == str(tmp_path.resolve())
        assert Path(app.screen.query_one("#workspace-tree", DirectoryTree).path) == tmp_path.resolve()

        path_input.value = str(child)
        await pilot.click("#workspace-go")
        assert Path(app.screen.query_one("#workspace-tree", DirectoryTree).path) == child.resolve()
        await pilot.click("#mode-read-only")
        await pilot.click("#workspace-confirm")
        await pilot.pause()

    assert app.selection == (str(child.resolve()), "read_only")


async def test_invalid_paths_keep_selector_open(tmp_path: Path) -> None:
    app = _ScreenHarness(tmp_path)

    async with app.run_test(size=(100, 40)) as pilot:
        path_input = app.screen.query_one("#workspace-path", Input)
        for invalid in ("relative/path", str(tmp_path / "missing")):
            path_input.value = invalid
            await pilot.pause()
            await pilot.click("#workspace-confirm")
            await pilot.pause()
            assert isinstance(app.screen, WorkspaceSetupScreen)
            assert app.selection is _UNSELECTED
            assert "absolute" in str(app.screen.query_one("#workspace-error", Static).content)

        path_input.value = str(tmp_path)
        await pilot.pause()
        await pilot.click("#workspace-confirm")
        await pilot.pause()

    assert app.selection == (str(tmp_path.resolve()), "off")


async def test_defaults_and_cancel(tmp_path: Path) -> None:
    alternate = tmp_path / "alternate"
    alternate.mkdir()
    app = _ScreenHarness(tmp_path, "workspace_write")

    async with app.run_test(size=(100, 40)) as pilot:
        app.screen.query_one("#workspace-path", Input).value = str(alternate)
        await pilot.click("#workspace-default")
        await pilot.pause()
    assert app.selection == (str(tmp_path.resolve()), "off")

    cancelled = _ScreenHarness(tmp_path)
    async with cancelled.run_test(size=(100, 40)) as pilot:
        await pilot.click("#workspace-cancel")
        await pilot.pause()
    assert cancelled.selection is None


@pytest.mark.parametrize(
    ("mode_button", "expected_mode"),
    [
        ("mode-off", "off"),
        ("mode-read-only", "read_only"),
        ("mode-workspace-write", "workspace_write"),
    ],
)
async def test_app_waits_for_selection_before_connecting_and_sends_selected_values(
    monkeypatch, tmp_path: Path, mode_button: str, expected_mode: str,
) -> None:
    selected = tmp_path / "selected"
    selected.mkdir()
    calls: list[tuple[str, dict[str, object]]] = []
    clients: list[object] = []

    class FakeClient:
        def __init__(self, _host: str, _port: int) -> None:
            clients.append(self)

        async def connect(self) -> None:
            pass

        def on_event(self, _callback: object) -> None:
            pass

        async def run_event_loop(self) -> None:
            await asyncio.Event().wait()

        async def send_command(self, method: str, params: dict[str, object]) -> dict[str, str]:
            calls.append((method, params))
            if method == "session.create":
                return {"session_id": "test-session"}
            return {}

    monkeypatch.setattr(tui_app, "SocketClient", FakeClient)
    app = tui_app.FloRaTuiApp("127.0.0.1", 9000, workspace_root=str(tmp_path))
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        assert clients == []
        assert calls == []
        assert app._session_id is None

        app.screen.query_one("#workspace-path", Input).value = "relative/path"
        await pilot.click("#workspace-confirm")
        await pilot.pause()
        assert isinstance(app.screen, WorkspaceSetupScreen)
        assert clients == []
        assert calls == []

        app.screen.query_one("#workspace-path", Input).value = str(selected)
        await pilot.click(f"#{mode_button}")
        await pilot.click("#workspace-confirm")
        await pilot.pause(0.1)
        assert app._session_id == "test-session"

    creates = [params for method, params in calls if method == "session.create"]
    assert creates == [{
        "mode": "chat", "workspace_root": str(selected.resolve()), "sandbox_mode": expected_mode,
    }]


async def test_app_cancel_exits_without_creating_client(monkeypatch, tmp_path: Path) -> None:
    clients: list[object] = []
    monkeypatch.setattr(tui_app, "SocketClient", lambda *_args: clients.append(object()))
    app = tui_app.FloRaTuiApp("127.0.0.1", 9000, workspace_root=str(tmp_path))

    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.click("#workspace-cancel")
        await pilot.pause()

    assert clients == []
    assert app._session_id is None


def test_tui_entrypoint_defaults_to_startup_directory_and_off(
    monkeypatch, tmp_path: Path,
) -> None:
    """A configured sandbox default must not silently enable Docker in the TUI."""
    captured: dict[str, object] = {}

    class FakeApp:
        def __init__(self, host: str, port: int, **kwargs: object) -> None:
            captured.update(host=host, port=port, **kwargs)

        def run(self) -> None:
            captured["ran"] = True

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["flora-tui"])
    monkeypatch.setattr(tui_main, "get_config", lambda: SimpleNamespace(
        host="127.0.0.1", port=9000,
        logging=SimpleNamespace(level="INFO"),
        sandbox=SimpleNamespace(default_mode="workspace_write"),
    ))
    monkeypatch.setattr(tui_main, "_setup_logging", lambda _level: None)
    monkeypatch.setattr(tui_main, "FloRaTuiApp", FakeApp)

    tui_main.main()

    assert captured["workspace_root"] == str(tmp_path.resolve())
    assert captured["sandbox_mode"] == "off"
    assert captured["ran"] is True
