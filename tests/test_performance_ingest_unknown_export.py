from content_platform.performance_ingest import import_performance_records


class _Store:
    def __init__(self):
        self.jobs = {}
        self.rows = []

    def list_jobs(self, _limit):
        return list(self.jobs.values())

    def get_job(self, job_id):
        if job_id not in self.jobs:
            raise KeyError(job_id)
        return self.jobs[job_id]

    def create_job(self, title, platforms, metadata, topic_fingerprint):
        job_id = f"job-{len(self.jobs) + 1}"
        job = {"id": job_id, "title": title, "platforms": platforms, "topic_fingerprint": topic_fingerprint, "metadata": metadata}
        self.jobs[job_id] = job
        return job

    def record_performance(self, job_id, platform, **metrics):
        self.rows.append({"job_id": job_id, "platform": platform, **metrics})


def test_unknown_official_export_without_job_id_creates_auditable_snapshot_job():
    store = _Store()
    result = import_performance_records(store, [{
        "platform": "wechat",
        "title": "仓库盘点的 AI 异常处理",
        "article_id": "wx-001",
        "read_count": 1200,
        "share_count": 21,
        "observed_at": "2026-09-15T12:00:00+00:00",
    }], allow_unknown_job=True)

    assert result == {"imported": 1, "failed": 0, "errors": []}
    assert store.rows[0]["platform"] == "wechat"
    assert store.rows[0]["views"] == 1200
    assert store.rows[0]["extra_metrics"]["article_id"] == "wx-001"
    assert store.rows[0]["extra_metrics"]["observed_at"] == "2026-09-15T12:00:00+00:00"
    assert store.rows[0]["job_id"] in store.jobs
