"""
models/report.py
----------------
Pydantic models for the Report entity.

These serve three purposes:
  1. Request validation  — FastAPI validates incoming JSON against these schemas
  2. Response serialization — FastAPI serializes outgoing data via these models
  3. Documentation — FastAPI auto-generates OpenAPI/Swagger from these types

Phase 6 additions:
  - FrequencyResult, GapResult, GapSummary: embedded analytics sub-documents
  - TopJob: job metadata for top-20 representative postings (no descriptions)
  - ReportMeta, ReportInsights, ReportExamples: structured 3-key response shape
  - AnalyzeComplete: full response after pipeline completes

Design notes:
  - MongoDB stores _id as ObjectId but we expose `slug` as the public identifier.
  - SkillResult.category is str (not enum) so gap engine's "Unknown" doesn't fail.
  - All Optional fields use None default (not Field(...)) for forward-compat.
"""

from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


# ── Enums ─────────────────────────────────────────────────────────────────────

class ExperienceLevel(str, Enum):
    entry  = "entry"
    mid    = "mid"
    senior = "senior"


class ReportStatus(str, Enum):
    pending    = "pending"
    processing = "processing"
    done       = "done"
    failed     = "failed"


class SkillPriority(str, Enum):
    high   = "High"
    medium = "Medium"
    low    = "Low"


# ── Phase 6: analytics sub-documents ──────────────────────────────────────────

class FrequencyResult(BaseModel):
    """One skill's market frequency across all analyzed job postings."""
    skill:         str
    job_count:     int        = Field(..., ge=0)
    frequency_pct: float      = Field(..., ge=0, le=100)
    category:      str        # "Technical" | "Tool" | "Soft Skill" | "Certification" | "Unknown"


class GapResult(BaseModel):
    """Frequency result enriched with gap detection, priority, and confidence."""
    skill:         str
    job_count:     int        = Field(..., ge=0)
    frequency_pct: float      = Field(..., ge=0, le=100)
    category:      str
    is_gap:        Optional[bool] = None   # None = market-only mode (no baseline)
    priority:      str        # "High" | "Medium" | "Low"
    confidence:    str        # "Low" | "Moderate" | "High"


class GapSummaryEntry(BaseModel):
    skill:         str
    frequency_pct: float


class GapSummary(BaseModel):
    mode:                  str    # "baseline" | "market-only"
    total_skills:          int
    high_priority_gaps:    int
    medium_priority_gaps:  int
    top_gaps:              list[GapSummaryEntry] = Field(default_factory=list)


class TopJob(BaseModel):
    """Representative job posting — metadata only, no description stored."""
    external_id:       str
    title:             str
    company:           Optional[str]   = None
    redirect_url:      str
    skill_match_score: float           = Field(..., ge=0, le=100)


# ── Phase 6: structured 3-key response ────────────────────────────────────────

class ReportMeta(BaseModel):
    target_role:        str
    location:           str
    total_jobs:         int
    confidence:         str
    generated_at:       str             # ISO-8601 UTC string
    timings_ms:         dict[str, int]  = Field(default_factory=dict)
    low_data_warning:   bool            = False
    gap_mode:           str             = "market-only"   # "baseline-driven" | "market-only"
    baseline_supported: bool            = False


class ReportInsights(BaseModel):
    frequency_results: list[FrequencyResult] = Field(default_factory=list)
    gap_results:       list[GapResult]       = Field(default_factory=list)
    gap_summary:       Optional[GapSummary]  = None


class ReportExamples(BaseModel):
    top_jobs: list[TopJob] = Field(default_factory=list)


# ── Legacy embedded sub-document (kept for backwards-compat) ──────────────────

class SkillResult(BaseModel):
    """Legacy: one skill's analysis result embedded in the old report schema."""
    skill:         str
    category:      str    # relaxed from SkillCategory enum (gap engine yields "Unknown")
    job_count:     int
    frequency_pct: float  = Field(..., ge=0, le=100)
    is_gap:        Optional[bool] = None
    priority:      str    = "Low"


# ── Request model ─────────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    """Body of POST /api/analyze"""
    target_role:    str                    = Field(..., min_length=2, max_length=120, examples=["Data Engineer"])
    current_role:   Optional[str]          = Field(None, min_length=2, max_length=120, examples=["Data Analyst"])
    location:       str                    = Field("remote", max_length=100, examples=["Remote"])
    experience_lvl: ExperienceLevel        = ExperienceLevel.mid
    known_skills:   list[str]              = Field(default_factory=list)


# ── Response models ───────────────────────────────────────────────────────────

class AnalyzeResponse(BaseModel):
    """Returned from POST /api/analyze (Phase 6: includes full report on completion)."""
    slug:            str
    status:          ReportStatus
    low_data_warning: bool = False
    meta:            Optional[ReportMeta]     = None
    insights:        Optional[ReportInsights] = None
    examples:        Optional[ReportExamples] = None
    error_msg:       Optional[str]            = None


class ReportResponse(BaseModel):
    """Full report returned from GET /api/report/:slug"""
    slug:             str
    target_role:      str
    current_role:     Optional[str]           = None
    location:         str
    experience_lvl:   ExperienceLevel
    status:           ReportStatus
    postings_analyzed: int                    = 0
    low_data_warning: bool                    = False
    confidence_level: Optional[str]           = None
    meta:             Optional[ReportMeta]    = None
    insights:         Optional[ReportInsights] = None
    examples:         Optional[ReportExamples] = None
    # Legacy field kept for smooth migration
    skill_results:    list[SkillResult]       = Field(default_factory=list)
    error_msg:        Optional[str]           = None
    created_at:       datetime
    expires_at:       Optional[datetime]      = None
