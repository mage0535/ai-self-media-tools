DEFAULT_PROFILE = {
    "niche": "AI and practical automation",
    "audience": "builders",
    "tone": "clear, factual, and restrained",
    "language": "zh",
    "keywords": ["AI", "agent", "automation"],
    "banned_topics": [],
    "source_weights": {"hn": 2, "techcrunch": 2, "github": 2, "36kr": 1},
}


def resolve_profile(profiles, name="default", overrides=None):
    profiles = profiles or {}
    if name != "default" and name not in profiles:
        raise ValueError(f"unknown profile: {name}")
    resolved = dict(DEFAULT_PROFILE)
    resolved.update(profiles.get("default", {}))
    resolved.update(profiles.get(name, {}))
    resolved.update(overrides or {})
    resolved["name"] = name
    return resolved

