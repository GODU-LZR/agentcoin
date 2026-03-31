from __future__ import annotations

import argparse
import logging

from agentcoin.config import load_config
from agentcoin.node import AgentCoinNode


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the AgentCoin reference node.")
    parser.add_argument("--config", help="Path to node config JSON file.")
    parser.add_argument("--log-level", default="INFO", help="Python logging level.")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    config = load_config(args.config)
    node = AgentCoinNode(config)
    node.serve_forever()


if __name__ == "__main__":
    main()

