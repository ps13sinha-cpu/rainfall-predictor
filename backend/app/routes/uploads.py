"""Upload routes — file upload for community reports."""
import os
import uuid
from pathlib import Path
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import CommunityReport
from app.services.auth import require_reporter

router = APIRouter(prefix="/api/uploads", tags=["uploads"])

UPLOAD_DIR = Path(__file__).parent.parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_TYPES = {
    "image/jpeg", "image/png", "image/webp", "image/gif",
    "video/mp4", "video/webm",
}
MAX_SIZE = 25 * 1024 * 1024  # 25 MB


@router.post("/")
async def upload_file(
    file: UploadFile = File(...),
    user=None,  # require_reporter
    db: AsyncSession = Depends(get_db),
):
    """Upload a photo or video for a community report."""
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail=f"File type {file.content_type} not allowed")

    contents = await file.read()
    if len(contents) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="File too large (max 25 MB)")

    # Generate unique filename
    ext = file.filename.split(".")[-1] if file.filename else "bin"
    filename = f"{uuid.uuid4().hex[:12]}.{ext}"
    date_dir = datetime.utcnow().strftime("%Y-%m")
    save_dir = UPLOAD_DIR / date_dir
    save_dir.mkdir(exist_ok=True)

    filepath = save_dir / filename
    with open(filepath, "wb") as f:
        f.write(contents)

    # Relative URL for serving
    url = f"/uploads/{date_dir}/{filename}"
    media_type = "image" if file.content_type.startswith("image/") else "video"

    return {
        "url": url,
        "filename": filename,
        "media_type": media_type,
        "size": len(contents),
        "content_type": file.content_type,
    }
