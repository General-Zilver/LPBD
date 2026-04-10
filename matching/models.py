# models.py -- Data structures for the matching pipeline.
# These are plain dataclasses with dict conversion for JSON serialization.

from dataclasses import dataclass, field, asdict
from datetime import datetime


@dataclass
class CrossReference:
    match_id: str
    relationship: str


@dataclass
class MatchResult:
    match_id: str
    page_url: str
    page_title: str
    source_type: str          # edu | gov | custom
    relevance_score: int      # 1-5
    benefit_name: str
    action: str               # apply | opt-in | opt-out | contact | review | be-aware
    summary: str
    reasoning: str
    action_details: str
    evidence_quote: str = ""
    evidence_type: str = ""
    cross_references: list[CrossReference] = field(default_factory=list)
    inferred_from: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    matched_at: str = field(default_factory=lambda: datetime.now().isoformat())
    pipeline_run_id: str = ""
    status: str = "new"       # new | seen | dismissed | saved

    def to_dict(self):
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data):
        refs = [CrossReference(**r) for r in data.pop("cross_references", [])]
        data.setdefault("benefit_name", "")
        data.setdefault("evidence_quote", "")
        data.setdefault("evidence_type", "")
        return cls(cross_references=refs, **data)


@dataclass
class PipelineProgress:
    current_stage: str        # filtering | matching | complete
    items_processed: int
    items_total: int
    started_at: str
    estimated_completion: str | None = None

    def to_dict(self):
        return asdict(self)


@dataclass
class PipelineState:
    run_id: str
    user: str
    model: str
    current_stage: str        # idle | filtering | matching | complete
    stages_completed: list[str] = field(default_factory=list)
    items_processed: int = 0
    items_total: int = 0
    last_processed_item: str | None = None
    answers_hash: str = ""
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**data)


@dataclass
class MatchResultsEnvelope:
    pipeline_status: str      # idle | filtering | matching | complete
    pipeline_progress: PipelineProgress | None = None
    results: list[MatchResult] = field(default_factory=list)
    result_count: int = 0
    last_updated: str | None = None

    def to_dict(self):
        d = {
            "pipeline_status": self.pipeline_status,
            "pipeline_progress": self.pipeline_progress.to_dict() if self.pipeline_progress else None,
            "results": sorted(
                [r.to_dict() for r in self.results],
                key=lambda x: x["relevance_score"],
                reverse=True,
            ),
            "result_count": self.result_count,
            "last_updated": self.last_updated,
        }
        return d

    @classmethod
    def from_dict(cls, data):
        progress = None
        if data.get("pipeline_progress"):
            progress = PipelineProgress(**data["pipeline_progress"])
        results = [MatchResult.from_dict(r) for r in data.get("results", [])]
        return cls(
            pipeline_status=data["pipeline_status"],
            pipeline_progress=progress,
            results=results,
            result_count=data.get("result_count", len(results)),
            last_updated=data.get("last_updated"),
        )
