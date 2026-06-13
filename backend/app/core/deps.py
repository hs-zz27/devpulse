from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from jose import JWTError  # type: ignore
from app.core.database import get_db
from app.core import security
from app.models.user import User

from fastapi import Request

async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    jwtToken = request.cookies.get("access_token")
    if not jwtToken:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    null_user_id = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="The sub field does not have any user_id",
        headers={"WWW-Authenticate": "Bearer"},
    )
    invalid_user_id = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid user id",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = security.decode_token(jwtToken)
        user_id = payload.get("sub")
        if user_id is None:
            raise null_user_id
    except JWTError:
            raise credentials_exception
    
    import uuid
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        raise invalid_user_id

    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()
    
    if user is None:
        raise invalid_user_id
    return user
    

    

