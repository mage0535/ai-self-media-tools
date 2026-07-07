import json
import subprocess
import sys


class _BaseScriptProvider:
    def __init__(self, script, timeout=120):
        self.script = str(script or "")
        self.timeout = int(timeout or 120)

    def _run(self, target, extra_args=None, env=None):
        proc = subprocess.run(
            [sys.executable, self.script, str(target), *(extra_args or [])],
            capture_output=True,
            text=True,
            timeout=self.timeout,
            check=False,
            env=env,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "provider failed")[-500:]
            raise RuntimeError(detail)
        payload = (proc.stdout or "").strip()
        if not payload:
            return {}
        return json.loads(payload)


class ScriptOCRProvider(_BaseScriptProvider):
    def run(self, target):
        return self._run(target)


class ScriptTranscriberProvider(_BaseScriptProvider):
    def run(self, target):
        return self._run(target)


class ScriptAnalyzerProvider(_BaseScriptProvider):
    def run(self, target):
        return self._run(target)


class ScriptImageProvider(_BaseScriptProvider):
    def run(self, prompt, output, extra_args=None):
        self._run(prompt, ["--output", str(output), *(extra_args or [])])
        return {"path": str(output)}


class ScriptVideoProvider(_BaseScriptProvider):
    def run(self, script_body, title, env=None):
        return self._run(script_body, [str(title)], env=env)
