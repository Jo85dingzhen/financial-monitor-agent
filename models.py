# Core Data Structures for Financial Monitor Agent V2
# Implements atomic claims architecture per audit feedback

from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field
from enum import Enum
from datetime import datetime


class MetricType(str, Enum):
    """Types of metrics that can appear in financial claims"""
    PERCENTAGE = "percentage"
    CURRENCY = "currency"
    COUNT = "count"
    RATIO = "ratio"
    RATE = "rate"
    INDEX = "index"
    RANK = "rank"
    DURATION = "duration"
    OTHER = "other"


class ClaimType(str, Enum):
    """Classification of claim verifiability"""
    FACTUAL = "factual"          # Can be verified against sources
    ANALYTICAL = "analytical"     # Interpretation/analysis (softer verification)
    OPINION = "opinion"          # Opinion/outlook (no verification needed)
    UNKNOWN = "unknown"


class VerificationStatus(str, Enum):
    """Verification result status"""
    VERIFIED = "verified"         # Claim matches source evidence
    PARTIAL_MATCH = "partial"     # Claim partially matches (e.g., different precision)
    CONFLICT = "conflict"         # Claim contradicts source evidence
    NOT_FOUND = "not_found"       # No supporting evidence found
    PENDING = "pending"           # Not yet verified


# ==========================================
# Source & Article Models
# ==========================================

class SourceInfo(BaseModel):
    """Information about a news source"""
    url: str
    domain: str
    tier: str  # tier1, tier2, unknown
    outlet_name: str
    whitelisted: bool


class RawArticle(BaseModel):
    """Raw article from gathering phase"""
    article_id: str
    url: str
    title: str
    snippet: str
    full_text: str = ""
    source: SourceInfo
    eligible_for_event: bool = False
    publish_date: str = ""


# ==========================================
# Atomic Claim Models (Layer 1 Implementation)
# ==========================================

class SupportingEvidence(BaseModel):
    """Evidence span supporting a claim"""
    source_id: str                     # Reference to article/chunk
    source_url: str
    source_outlet: str
    span_text: str                     # Exact text from source
    confidence: float = 0.0            # Alignment confidence score


class AtomicClaim(BaseModel):
    """
    Atomic claim with structured fields for verification.
    This is the core unit of verification in the upgraded system.
    """
    claim_id: str
    claim_text: str                    # Natural language claim
    claim_type: ClaimType = ClaimType.FACTUAL
    
    # Entity extraction
    entities: List[str] = Field(default_factory=list, 
        description="Named entities: companies, persons, orgs")
    
    # Metric extraction (for numerical claims)
    metric_type: Optional[MetricType] = None
    metric_value: Optional[float] = None
    metric_unit: Optional[str] = None
    metric_original_text: Optional[str] = None  # "47.2%", "140万亿"
    
    # Temporal context
    time_reference: Optional[str] = None        # "2024年Q3", "本周"
    
    # Geographic context
    geography: Optional[str] = None             # "中国", "美国"
    
    # Source attribution (in-sentence citation)
    source_ids: List[str] = Field(default_factory=list)
    source_urls: List[str] = Field(default_factory=list)
    
    # Evidence for verification
    supporting_evidence: List[SupportingEvidence] = Field(default_factory=list)
    
    # Verification results
    verification_status: VerificationStatus = VerificationStatus.PENDING
    verification_details: Dict[str, Any] = Field(default_factory=dict)


# ==========================================
# Event & Report Models
# ==========================================

class Event(BaseModel):
    """Clustered event from analyst phase"""
    event_id: str
    main_title: str
    summary: str
    score: float
    articles: List[RawArticle]
    primary_category: str
    secondary_category: str = ""
    detail: dict = {}


class ClaimBasedReport(BaseModel):
    """
    News report with atomic claims architecture.
    Replaces the old NewsReport model.
    """
    event_id: str = ""
    title: str
    
    # Structured content sections
    summary_text: str = ""
    background_text: str = ""
    analysis_text: str = ""
    outlook_text: str = ""
    
    # Atomic claims extracted from the report
    claims: List[AtomicClaim] = Field(default_factory=list)
    
    # Source mapping for citations
    source_mapping: Dict[str, str] = Field(default_factory=dict)
    
    # Generation metadata
    generated_at: Optional[datetime] = None
    model_used: str = ""


# ==========================================
# Verification Result Models
# ==========================================

class AlignmentResult(BaseModel):
    """Result from deterministic aligner"""
    claim_id: str
    alignment_type: str  # "numeric", "temporal", "entity"
    source_value: Any
    claim_value: Any
    is_aligned: bool
    alignment_score: float
    discrepancy_details: Optional[str] = None


class VerificationResult(BaseModel):
    """Comprehensive verification result for a report"""
    event_id: str
    report: ClaimBasedReport
    
    # Alignment results
    alignment_results: List[AlignmentResult] = Field(default_factory=list)
    
    # Overall status
    status: str  # PASS, PARTIAL, FAIL, FLAGGED
    issues: List[str] = Field(default_factory=list)
    
    # Statistics
    total_claims: int = 0
    verified_claims: int = 0
    failed_claims: int = 0
    not_found_claims: int = 0