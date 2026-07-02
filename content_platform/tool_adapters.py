import json
import subprocess


class _BaseScriptProvider:
    def __init__(self, script, timeout=120):
        self.script = str(script or "")
        self.timeout = int(timeout or 120)

    def _run(self, target):
        proc = subprocess.run(
            ["python", self.script, str(target)],
            capture_output=True,
            text=True,
            timeout=self.timeout,
            check=False,
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
