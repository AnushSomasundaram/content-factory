"""Runtime settings, read once from environment variables.

Every setting has a default, so `uvicorn contentfactory.api:app` works with no
configuration at all (offline mode, no MeetStream import). See docs/CONFIGURATION.md.

| Variable              | Default                              | Meaning                                         |
|-----------------------|--------------------------------------|-------------------------------------------------|
| CF_DATA_DIR           | ./data                               | Database, recordings, renders, exports          |
| CF_LLM                | openai if OPENAI_API_KEY is set, else offline | Which generator to use                 |
| CF_MODEL              | gpt-6-astra                          | OpenAI model id                                 |
| CF_EFFORT             | medium                               | Reasoning effort: low / medium / high / xhigh / max |
| CF_JOB_WORKERS        | 2                                    | Jobs processed at the same time                 |
| MEETSTREAM_API_KEY    | (unset)                              | Enables MeetStream recording import             |
| MEETSTREAM_BASE_URL   | https://api.meetstream.ai/api/v1     | Override for testing                            |
| CF_API_TOKEN          | (unset)                              | If set, the API requires this bearer token (read in api.py) |
"""

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("CF_DATA_DIR", "data")).resolve())
    # "openai" uses the OpenAI API; "offline" uses deterministic heuristics (tests, demos without a key).
    llm_mode: str = field(
        default_factory=lambda: os.environ.get("CF_LLM", "openai" if os.environ.get("OPENAI_API_KEY") else "offline")
    )
    model: str = field(default_factory=lambda: os.environ.get("CF_MODEL", "gpt-6-astra"))
    effort: str = field(default_factory=lambda: os.environ.get("CF_EFFORT", "medium"))
    meetstream_api_key: str | None = field(default_factory=lambda: os.environ.get("MEETSTREAM_API_KEY"))
    meetstream_base_url: str = field(
        default_factory=lambda: os.environ.get("MEETSTREAM_BASE_URL", "https://api.meetstream.ai/api/v1")
    )
    job_workers: int = field(default_factory=lambda: int(os.environ.get("CF_JOB_WORKERS", "2")))

    # On-disk layout under data_dir:
    #   contentfactory.db             SQLite: webinars, jobs, assets, versions, reviews, exports
    #   webinars/<webinar_id>/        recording.*, transcript.json, raw MeetStream responses
    #   jobs/<job_id>/clips|captions  rendered media for one job
    #   jobs/<job_id>/exports/        ZIP packages

    @property
    def db_path(self) -> Path:
        return self.data_dir / "contentfactory.db"

    def webinar_dir(self, webinar_id: str) -> Path:
        return self.data_dir / "webinars" / webinar_id

    def job_dir(self, job_id: str) -> Path:
        return self.data_dir / "jobs" / job_id


def load_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    return s
