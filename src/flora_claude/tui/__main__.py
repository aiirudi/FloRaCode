from __future__ import annotations

import argparse

from flora_claude.core.config import get_config
from flora_claude.tui.app import FloRaTuiApp

def main() -> None:
    parser = argparse.ArgumentParser(prog="flora-tui", description="FloRaClaude TUI")
    parser.add_argument("--replay",
                        metavar="RUN_ID",
                        help="Replay events from a past run on connect",)
    args = parser.parse_args()

    config = get_config()
    app = FloRaTuiApp(config.host, config.port, replay_run_id=args.replay)
    app.run()

if __name__ == "__main__":
    main()