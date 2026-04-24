import asyncio
from collections import defaultdict
from typing import Any
 
latest_by_user: dict[str, dict[str, Any]] = {}
subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)
email_worker_task: asyncio.Task | None = None