import json
from types import SimpleNamespace

from content_platform.pipeline import ARTICLE_AI_IMAGE_NOTE, Pipeline


def _draft(platform):
    return {"title": "t", "body": "正文。\n\n结尾。", "draft_meta": {"strategy": {"primary_platforms": [platform]}}}


def _provenance(tmp_path, origins):
    root = tmp_path / "artifacts" / "j1"
    root.mkdir(parents=True)
    (root / "asset_provenance.json").write_text(json.dumps({"assets": [{"origin": o} for o in origins]}), encoding="utf-8")


def test_article_with_generated_pictures_says_so_once(tmp_path):
    # MED90: the rulebook allows declared generated pictures only with a reader-facing note.
    _provenance(tmp_path, ["real_photo", "ai_generated"])
    owner, draft = SimpleNamespace(data_dir=str(tmp_path)), _draft("zhihu")
    Pipeline._add_generated_image_note(owner, "j1", draft)
    Pipeline._add_generated_image_note(owner, "j1", draft)
    assert draft["body"] == "正文。\n\n结尾。\n\n" + ARTICLE_AI_IMAGE_NOTE


def test_stock_only_article_and_video_lanes_get_no_note(tmp_path):
    _provenance(tmp_path, ["real_photo"])
    owner = SimpleNamespace(data_dir=str(tmp_path))
    for platform in ("zhihu", "douyin_pet"):
        draft = _draft(platform)
        Pipeline._add_generated_image_note(owner, "j1", draft)
        assert ARTICLE_AI_IMAGE_NOTE not in draft["body"]
