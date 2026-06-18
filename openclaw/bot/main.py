from __future__ import annotations

import logging

from openclaw.bot import build_application
from openclaw.core.config import get_settings

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)


def main() -> None:
    settings = get_settings()
    app = build_application(settings)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
