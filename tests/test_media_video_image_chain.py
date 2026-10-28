from unittest.mock import patch

from content_platform.media import MediaBridge
from content_platform.tool_adapters import ScriptImageProvider


def test_video_image_cfg_uses_its_own_provider_chain(tmp_path):
    bridge = MediaBridge({"image": {"provider": "auto"}, "video": {"image_provider_chain": "sense_nova,go_gemini,cloudflare"}}, tmp_path)
    assert bridge._video_image_cfg() == {"provider": "auto", "provider_chain": "sense_nova,go_gemini,cloudflare"}
    assert "provider_chain" not in MediaBridge({"image": {"provider": "auto"}}, tmp_path)._video_image_cfg()


def test_script_image_provider_passes_env_only_when_given():
    provider = ScriptImageProvider("image_gen.py", 30)
    with patch.object(provider, "_run", return_value={}) as run:
        provider.run("p", "out.png", ["--provider", "auto"])
        provider.run("p", "out.png", ["--provider", "auto"], env={"IMAGE_PROVIDER_CHAIN": "sense_nova"})
    assert run.call_args_list[0].kwargs == {"env": None}
    assert run.call_args_list[1].kwargs == {"env": {"IMAGE_PROVIDER_CHAIN": "sense_nova"}}


def test_generate_image_hands_the_role_chain_to_the_image_script(tmp_path):
    bridge = MediaBridge({}, tmp_path)
    job = {"id": "j1", "title": "AI Agent 之 用户记忆和知识库", "body": "正文", "platforms": ["kuaishou"]}
    seen = {}

    class Stop(Exception):
        pass

    class Provider:
        def run(self, prompt, output, extra_args=None, env=None):
            seen["env"] = env
            raise Stop

    with patch.object(bridge.registry, "choose_provider", return_value=Provider()):
        try:
            bridge._generate_image(job, tmp_path / "out", {"provider": "auto", "provider_chain": "sense_nova,go_gemini"})
        except Stop:
            pass
    assert seen["env"]["IMAGE_PROVIDER_CHAIN"] == "sense_nova,go_gemini"
