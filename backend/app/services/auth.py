"""Authentication service — JWT + password hashing."""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
import bcrypt as _bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import User

bearer_scheme = HTTPBearer(auto_error=False)


# ── Password helpers ───────────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plain.encode(), hashed.encode())


# ── Token helpers ──────────────────────────────────────────────────────────────
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


# ── FastAPI dependencies ──────────────────────────────────────────────────────
async def get_current_user(
    cred: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """Extract user from JWT. Returns None if no token provided (public access)."""
    if cred is None:
        return None
    payload = decode_token(cred.credentials)
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


async def require_user(user: Optional[User] = Depends(get_current_user)) -> User:
    """Require an authenticated user."""
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


async def require_reporter(user: User = Depends(require_user)) -> User:
    """Require reporter or admin role."""
    if user.role not in ("reporter", "admin"):
        raise HTTPException(status_code=403, detail="Reporter role required")
    return user


async def require_admin(user: User = Depends(require_user)) -> User:
    """Require admin role."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return user
