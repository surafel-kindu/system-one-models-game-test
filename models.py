"""Shared model backends (Laya, Jev-BERTa, Drex) used by every game in this project.

A backend answers one typed multiple-choice question: given `state` text, `instructions`, and
`criteria` (dict of option id -> description), it returns (chosen_id, {id: probability}).
Backends are heavy (local models) or rate-limited (hosted API), so `get_backend` caches one
instance per name and every game reuses it instead of loading its own copy.
"""
import json
import os
import socket
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit


def _load_env(path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")):
    """Minimal .env loader (KEY=VALUE lines); real environment variables win."""
    try:
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))
    except FileNotFoundError:
        pass


_load_env()


class Backend:
    name = "base"
    label = "Base"
    max_concurrency = 1  # simultaneous answer() calls the server will allow

    @classmethod
    def availability(cls):
        """(available, reason-if-not). Lets a backend opt out, e.g. when an API key is missing."""
        return True, ""

    def answer(self, state, instructions, criteria):
        raise NotImplementedError


class LayaBackend(Backend):
    name, label = "laya", "Laya"

    def __init__(self, model="convaiinnovations/laya"):
        import laya
        self.agent = laya.load(model)

    def answer(self, state, instructions, criteria):
        q = {"choice": {"type": "choice", "instructions": instructions, "criteria": criteria}}
        a = self.agent.system_one(state, q)["answers"]["choice"]
        return a["choice"], a.get("probabilities", {})


class JevBackend(Backend):
    name, label = "jev", "Jev-BERTa"

    def __init__(self, model="leobitz/jev-berta-base-zeroshot-classifier"):
        from jev_berta import JevBerta
        # batch_size chunks how many (state, candidate) rows go through one encoder forward pass
        # within a single predict() call — matters most for Chess, which can offer up to 14 choices.
        batch_size = int(os.environ.get("JEV_BATCH_SIZE", "4"))
        self.m = JevBerta.from_pretrained(model, batch_size=batch_size)
        self.m.model.float()  # checkpoint ships half-precision layers; CPU needs float32

    def answer(self, state, instructions, criteria):
        ids = list(criteria)
        r = self.m.predict(context=state, query=instructions, choices=[criteria[k] for k in ids])
        return ids[r["choice_index"]], {k: r["probabilities"][criteria[k]] for k in ids}


class GlinerBackend(Backend):
    """fastino/GLiNER2.5-Decide (DeBERTa-v3-large based). Its public API only returns the winning
    label's confidence, not a full distribution — but passing `multi_label=True, cls_threshold=0.0,
    class_act="softmax"` (documented `gliner2` classification kwargs) makes every label pass the
    zero threshold, so we get back the whole softmax distribution rather than just the argmax."""
    name, label = "gliner", "GLiNER2.5-Decide"

    def __init__(self, model="fastino/GLiNER2.5-Decide"):
        from gliner2 import AutoExtractor
        self.m = AutoExtractor.from_pretrained(model)

    def answer(self, state, instructions, criteria):
        text = f"{instructions}\n\n{state}"
        tasks = {"choice": {"labels": criteria, "multi_label": True, "cls_threshold": 0.0, "class_act": "softmax"}}
        r = self.m.classify_text(text, tasks, include_confidence=True)
        probs = {row["label"]: row["confidence"] for row in r["choice"]}
        pick = max(probs, key=probs.get)
        return pick, probs


def _call_systemone(url, state, instructions, criteria, model, api_key=None, service_name="API"):
    """Shared client for TypeSafe's /v1/systemone contract (used by both Drex and a local Kev
    server — same request/response shape). Retries on rate limiting / transient server errors."""
    body = json.dumps({"model": model, "state": state, "questions": {
        "choice": {"type": "choice", "instructions": instructions, "criteria": criteria}}}).encode()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    req = urllib.request.Request(url, body, headers)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                a = json.load(r)["answers"]["choice"]
            break
        except urllib.error.HTTPError as e:
            if e.code in (429, 529, 500, 502, 503, 504) and attempt < 4:
                ms = e.headers.get("retry-after-ms")
                time.sleep(int(ms) / 1000 if ms and ms.isdigit() else 2 * (attempt + 1))
                continue
            raise RuntimeError(f"{service_name} error {e.code}: {e.read()[:200]!r}") from None
    probs = a.get("probabilities", {})
    pick = a.get("choice")
    if pick not in criteria:
        pick = max(criteria, key=lambda k: probs.get(k, 0))
    return pick, probs


class DrexBackend(Backend):
    """Hosted Drex API (https://drex.nace.ai/docs). Needs DREX_API_KEY in .env or the environment."""
    name, label = "drex", "Drex"
    URL = "https://drex.nace.ai/v1/systemone"

    @classmethod
    def availability(cls):
        return (True, "") if os.environ.get("DREX_API_KEY") else (False, "set DREX_API_KEY in .env")

    def __init__(self):
        ok, why = self.availability()
        if not ok:
            raise RuntimeError("Drex unavailable: " + why)
        self.key = os.environ["DREX_API_KEY"]
        self.model = os.environ.get("DREX_MODEL", "drex-latest")
        self.max_concurrency = int(os.environ.get("DREX_CONCURRENCY", "2"))  # free tier allows 2

    def answer(self, state, instructions, criteria):
        return _call_systemone(self.URL, state, instructions, criteria, self.model,
                                api_key=self.key, service_name="Drex API")


class KevBackend(Backend):
    """A locally-run Kev server (https://github.com/jaredpalmer/kev), started separately with
    `python -m kev.serve --run jaredpalmer/kev-0.8b --port 8009` (see kev-repo/README.md — it
    needs its own venv, since kev pins an older torch than this project's). Kev speaks the same
    TypeSafe /v1/systemone contract as Drex, just unauthenticated and on localhost by default."""
    name, label = "kev", "Kev-0.8B"

    @classmethod
    def _url(cls):
        return os.environ.get("KEV_URL", "http://127.0.0.1:8009/v1/systemone")

    @classmethod
    def availability(cls):
        host_port = urlsplit(cls._url())
        try:
            with socket.create_connection((host_port.hostname, host_port.port or 80), timeout=0.4):
                return True, ""
        except OSError:
            return False, "kev server not reachable — see kev-repo/README.md to start it"

    def __init__(self):
        ok, why = self.availability()
        if not ok:
            raise RuntimeError(why)
        self.url = self._url()
        self.key = os.environ.get("KEV_API_KEY")  # only needed if the server was started with one
        self.model = os.environ.get("KEV_MODEL", "kev-latest")
        self.max_concurrency = int(os.environ.get("KEV_CONCURRENCY", "1"))

    def answer(self, state, instructions, criteria):
        return _call_systemone(self.url, state, instructions, criteria, self.model,
                                api_key=self.key, service_name="Kev server")


BACKENDS = {"laya": LayaBackend, "jev": JevBackend, "drex": DrexBackend, "kev": KevBackend, "gliner": GlinerBackend}
_cache = {}


def get_backend(name):
    if name not in _cache:
        _cache[name] = BACKENDS[name]()
    return _cache[name]
