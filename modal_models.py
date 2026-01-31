from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class SlideInput(BaseModel):
    index: int
    titulo: str = ""
    background_image: str = Field(..., alias="backgroundImage")
    audio_narration: Optional[str] = Field(None, alias="audioNarration")
    avatar_video: Optional[str] = Field(None, alias="avatarVideo")
    duration: Optional[float] = None

    class Config:
        populate_by_name = True


class RenderRequest(BaseModel):
    project_name: str = Field(..., alias="projectName")
    slides: list[SlideInput]
    resolution: str = "1080p"
    fps: int = 30
    quality: str = "high"

    class Config:
        populate_by_name = True

