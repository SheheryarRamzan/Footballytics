"""Structured outputs exchanged between agents (validated with Pydantic)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Claim(BaseModel):
    subject_id: str = Field(description="Player id like 'RIV-09' or club id like 'RIV'")
    metric: str = Field(description="Metric name, e.g. xg, goals, pass_accuracy, top_speed_kmh, season_goals")
    value: float = Field(description="The value you state in the text (ratios as 0-1)")


class Insight(BaseModel):
    headline: str = Field(description="At most 12 words")
    why_it_matters: str = Field(description="2-3 sentences: cause, consequence and context")
    tactical_angle: str | None = Field(default=None, description="One sentence on control/chaos, pressing or rhythm, or null")
    claims: list[Claim] = Field(default_factory=list, description="Every player/team statistic used in the text")
    confidence: float = Field(default=0.8, ge=0, le=1)


class Rendition(BaseModel):
    language: str = Field(description="BCP-47 code, e.g. en, es, ar, ur, fr, pt, hi")
    fan: str = Field(description="1-2 short lively sentences, no jargon")
    analyst: str = Field(description="1-2 precise sentences that keep the key numbers")
    kids: str = Field(description="One simple sentence for ages 7-11")
    audio: str = Field(description="Audio description for blind/low-vision fans: where on the pitch, who, what, result")
    label: str = Field(description="On-screen graphic label, at most 28 characters")


class Renditions(BaseModel):
    renditions: list[Rendition]


class Recap(BaseModel):
    headline: str
    summary: str = Field(description="4-6 sentences telling the story of the match, not just listing events")
    turning_point: str = Field(description="The moment that decided the match and why")
    tactical_story: str = Field(description="How control, pressing and rhythm evolved")
    player_of_the_match: str = Field(description="Player id")
    player_of_the_match_reason: str
    claims: list[Claim] = Field(default_factory=list)
