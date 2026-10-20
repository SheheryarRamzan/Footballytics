"""ViewerSession: one per connected viewer. Sits between the hub stream and the socket.

Client -> server messages (JSON):
  {"fan_id": "..."}             attach a fan profile (enables the Personal Director)
  {"focus": match_id}           watch a match without a profile (no director)
  {"stage": match_id}           the fan picked a match manually
  {"languages": ["en", "ur"]}   languages for agent renditions (profile language is added automatically)

Server -> client adds (on top of hub messages):
  {"kind": "director", "data": Decision}   cut / pip / ticker / return / points / stage
"""

from __future__ import annotations

from ..hub import LiveHub
from .director import PersonalDirector
from .profiles import FanProfile, ProfileStore


class ViewerSession:
    def __init__(self, hub: LiveHub, store: ProfileStore, agents=None):
        self.hub = hub
        self.store = store
        self.agents = agents
        self.focus: str | None = None
        self.languages: list[str] = []
        self.fan: FanProfile | None = None
        self.director: PersonalDirector | None = None

    # ------------------------------------------------------------------ languages
    def _set_languages(self, langs: list[str]) -> None:
        if self.agents:
            self.agents.remove_viewer_languages(self.languages)
        self.languages = sorted(set(str(x)[:8] for x in langs))[:3]
        if self.agents:
            self.agents.add_viewer_languages(self.languages)

    def close(self) -> None:
        self._set_languages([])

    # ------------------------------------------------------------------ client messages
    def on_client(self, msg: dict) -> list[dict]:
        out: list[dict] = []
        if "fan_id" in msg:
            self.fan = self.store.get(msg["fan_id"])
            matches = {mid: {"home": m.meta["home"], "away": m.meta["away"]} for mid, m in self.hub.matches.items()}
            home = next((mid for mid, m in matches.items() if self.fan.favorite_club in (m["home"], m["away"])),
                        next(iter(matches), None))
            self.director = PersonalDirector(self.fan, self.hub.league, home, matches)
            self.focus = home
            self._set_languages([self.fan.language] + self.languages)
            out.append(self._director_msg({"action": "stage", "match_id": home, "relevance": 0, "line":
                                           "Your club's match is on the main stage.",
                                           "reasons": ["home match: your favourite club"]}))
        if "focus" in msg:
            self.focus = msg["focus"]
        if "stage" in msg and self.director:
            self.director.stage_switch(msg["stage"])
            self.focus = msg["stage"]
        if "languages" in msg:
            langs = list(msg["languages"]) + ([self.fan.language] if self.fan else [])
            self._set_languages(langs)
        return out

    def refresh_profile(self) -> None:
        """Pick up profile changes (mode/language/captain) made over REST."""
        if self.fan:
            self._set_languages([self.fan.language] + [lang for lang in self.languages if lang != self.fan.language])

    # ------------------------------------------------------------------ hub messages
    def on_hub(self, msg: dict) -> list[dict]:
        kind = msg["kind"]
        if kind == "matchday":
            # A new matchday started: re-plan the fan's show around the new fixtures.
            out = [msg]
            if self.fan:
                out += self.on_client({"fan_id": self.fan.fan_id})
            else:
                self.focus = next(iter(self.hub.matches), None)
            return out
        if kind in ("frame", "event"):
            return [msg] if msg["match_id"] == self.focus else []
        out = [self._trim(msg)] if kind == "broadcast" else [msg]
        if not self.director:
            return out
        if kind == "moment":
            for d in self.director.on_moment(msg["data"]):
                if d.action == "cut":
                    self.focus = d.match_id
                out.append(self._director_msg(d.to_dict()))
        elif kind == "fantasy":
            out += [self._director_msg(d.to_dict()) for d in self.director.on_fantasy(msg["match_id"], msg["data"])]
        elif kind == "tick":
            for d in self.director.on_tick():
                self.focus = d.match_id
                out.append(self._director_msg(d.to_dict()))
        return out

    def _trim(self, msg: dict) -> dict:
        """Send only the renditions this viewer can use."""
        item = msg["data"]
        keep = set(self.languages) | {"en"}
        rend = {k: v for k, v in item.get("renditions", {}).items() if k in keep}
        return {**msg, "data": {**item, "renditions": rend}}

    @staticmethod
    def _director_msg(data: dict) -> dict:
        return {"kind": "director", "match_id": data.get("match_id"), "data": data}
