from __future__ import annotations

from core.exchange.auth_check import signed_account_check
from core.utils.config import load_config


if __name__ == "__main__":
    result = signed_account_check(load_config())
    print(result)
