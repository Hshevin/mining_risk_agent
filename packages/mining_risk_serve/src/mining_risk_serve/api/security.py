"""Lightweight API protection for operational endpoints."""

import os
import secrets
from typing import Optional

from fastapi import Header, HTTPException, status


def _admin_token() -> str:
    return os.getenv("MRA_ADMIN_TOKEN", "").strip()


def _allow_unauthenticated_admin() -> bool:
    return os.getenv("MRA_ALLOW_UNAUTHENTICATED_ADMIN", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


async def require_admin_token(
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
) -> None:
    """Require an admin token for mutable/sensitive operational endpoints."""
    expected = _admin_token()
    if not expected:
        if _allow_unauthenticated_admin():
            return
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="管理接口未启用：请设置 MRA_ADMIN_TOKEN，或仅在本地演示时设置 MRA_ALLOW_UNAUTHENTICATED_ADMIN=true。",
        )

    if not x_admin_token or not secrets.compare_digest(x_admin_token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少或无效的管理令牌",
        )
