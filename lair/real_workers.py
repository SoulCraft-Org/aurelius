"""Real workers (step 29, #71): an open model with one tool, search over the Library, in place of a stand-in.

A RealWorker has do_item's contract: one item in, one reply out, in the spec's reply shape. It sends the model the
key only, never item.answer or any truth. Stdlib only. The model server is any OpenAI-compatible chat API.
"""

import http.client
import json
import re
import time
import urllib.parse
import urllib.request

from lair import load_spec
from lair.workers import worker_types

# One Qwen3.5 family, Apache-2.0 on every card (Hugging Face, read 2026-11-23). BF16 weights are about 4.6, 9.3 and 19.3 GB, so
# together they do not fit one 24 GB L4: each is served in turn. Native context is 262144 on every card; we serve 16384.
REAL_WORKERS = {
    "small": {"model": "Qwen/Qwen3.5-2B", "revision": "15852e8c16360a2fea060d615a32b45270f8a8fc", "licence": "Apache-2.0", "params_b": 2.3},
    "medium": {"model": "Qwen/Qwen3.5-4B", "revision": "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a", "licence": "Apache-2.0", "params_b": 4.7},
    "large": {"model": "Qwen/Qwen3.5-9B", "revision": "c202236235762e1c871ad0ccb60c8ee5ba337b9a", "licence": "Apache-2.0", "params_b": 9.7},
}
ROUNDS, TOP_K, MAX_TOKENS, TIMEOUT_S = 4, 5, 512, 120
SEARCH = {"type": "function", "function": {"name": "search", "description": "Search the library; returns the top 5 documents as id and text.",
          "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}}
SYSTEM = ("Find the value of one record in a library. Use the search tool, at most 4 times, and trust the latest correct entry. "
          'Then answer with only JSON: {"value": "<the value>", "doc": "<id of the document you took it from>"}.')
BAD = (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, http.client.HTTPException)  # a timeout is an OSError


class RealWorker:
    def __init__(self, kind, url, model, library, spec=None, timeout=TIMEOUT_S, deadline=None):  # deadline: a time.monotonic() value no call may pass
        if urllib.parse.urlparse(url).scheme not in ("http", "https"):
            raise ValueError("url must be http or https")
        self.wtype = worker_types(spec or load_spec())[kind]
        self.url, self.model, self.library, self.timeout, self.deadline = url, model, library, timeout, deadline

    def __call__(self, item):
        return self.do_item(item)

    def do_item(self, item):
        """One worker call; any failure or malformed answer is status failed, with the spend still counted."""
        start, used, read = time.monotonic(), {"tokens": 0}, {}
        try:
            fact = self._ask(item.key, used, read)
            status, facts = "completed", [fact]
        except BAD:  # the type only is ever kept: no body, no answer text
            status, facts = "failed", []
        spent = {"credits": self.wtype["credits_per_call"], "seconds": round(time.monotonic() - start, 3), "tokens": used["tokens"]}
        return {"status": status, "facts": facts, "alarms": [], "spent": spent}

    def _ask(self, key, used, read):  # read: doc id -> text of every document a search returned
        msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": f"Record {key}: what is its value?"}]
        for turn in range(ROUNDS + 1):  # the last turn offers no tool, so it must answer
            msg = self._post(msgs, [SEARCH] if turn < ROUNDS else None, used)
            calls = msg.get("tool_calls") or []
            if not calls:
                return self._fact(key, msg["content"], read)
            if turn == ROUNDS:
                raise ValueError("no answer after the tool rounds")
            msgs.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
            for c in calls:
                hits = self.library.search(self._query(c), TOP_K) if c["function"]["name"] == "search" else []
                read.update(hits)
                msgs.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps([{"id": d, "text": t} for d, t in hits])})
        raise ValueError("unreachable")

    @staticmethod
    def _query(call):
        q = json.loads(call["function"]["arguments"])["query"]
        if not isinstance(q, str):
            raise TypeError("query must be a string")
        return q

    def _post(self, msgs, tools, used):
        req = {"model": self.model, "temperature": 0, "max_tokens": MAX_TOKENS, "messages": msgs, **({"tools": tools} if tools else {})}
        body = json.dumps(req).encode()
        head = {"Content-Type": "application/json"}
        try:
            wait = self.timeout if self.deadline is None else min(self.timeout, self.deadline - time.monotonic())
            if wait <= 0:
                raise TimeoutError("past the deadline")
            with urllib.request.urlopen(urllib.request.Request(self.url, body, head), timeout=wait) as r:
                data = json.load(r)
            n = data["usage"]["total_tokens"]
            used["tokens"] += n if isinstance(n, int) and not isinstance(n, bool) and n > 0 else len(body) // 3 + MAX_TOKENS
            return data["choices"][0]["message"]
        except BAD:
            used["tokens"] += len(body) // 3 + MAX_TOKENS  # unknown is never zero
            raise

    @staticmethod
    def _fact(key, content, read):
        found = re.search(r"\{.*\}", content or "", re.S)
        ans = json.loads(found.group())
        value, doc = ans["value"], ans.get("doc")
        if not isinstance(value, str) or not value.strip():
            raise ValueError("value must be a non-empty string")
        value = value.strip()
        hit = [d for d, t in read.items() if value.lower() in t.lower()]  # seen: the value is in a document it read
        source = doc if doc in hit else hit[0] if hit else doc if doc in read else "model"
        return {"claim": key, "value": value, "tag": "seen" if hit else "inferred", "source": source}
