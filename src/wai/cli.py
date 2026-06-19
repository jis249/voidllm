"""CLI entry point for WAI."""

from __future__ import annotations

import argparse
import logging
import sys


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="wai", description="WAI server")
    parser.add_argument(
        "--config",
        default="",
        help="Path to wai.yaml (default: WAI_CONFIG or ./wai.yaml)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="Bind host")
    parser.add_argument("--port", type=int, default=0, help="Bind port (overrides config)")
    parser.add_argument(
        "--log-level",
        default="",
        help="Log level (debug, info, warn, error)",
    )
    args = parser.parse_args(argv)

    from wai.config import load

    cfg, _ = load(args.config)
    port = args.port or cfg.server.proxy.port
    log_level = (args.log_level or cfg.logging.level or "info").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    import uvicorn

    from wai.app import create_app

    app = create_app(config=cfg, config_path=args.config)
    uvicorn.run(app, host=args.host, port=port, log_level=log_level.lower())


if __name__ == "__main__":
    main(sys.argv[1:])
