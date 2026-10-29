"""What leaves the laptop for the hub's FleetView (thinkingtoo/tt-tiroir#173).

The push sends a projection of the roster, never the roster: a fixed list of
fields, only for the projects named in `push.include`, and every string checked
for a credential shape before it goes. These tests feed a roster that carries
everything the page has -- prompts, paths, branches, Paste first lines -- and
look at what would be sent.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import push

PROMPT = "please read /home/tiroir/secret-client/contract.pdf and draft the reply"
P1, P2 = "0123456789abcdef", "fedcba9876543210"
TOKEN = "gh" + "p_" + "aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3zA5"


def tile(**over):
    t = {
        "key": "claude:0b148296-4dca-48d5-9db1-e04a1d98d014", "name": "Rune", "provider": "claude",
        "status": "waiting", "suggestion": None, "unread": True, "handover": "I merged it into dev",
        "stop": 1793314847423, "pinned": False, "assigned": False, "tags": ["boss"],
        "line": "push.py for the hub", "lineSource": "did",
        "jump": {"via": "pane"}, "flag": "waiting", "flagNote": "asks you",
        "movement": None, "moving": False, "waiting": False, "activity": "waiting", "ci": None,
        "stuck": {"kind": "needs", "source": "question", "reason": "Question",
                  "context": {"questions": [{"question": "Which default?", "header": "Default", "multi": False,
                                             "options": [{"label": "Include", "description": "send none"}]}]}},
        "counted": "needs", "guessedCommands": ["git push"],
        "pastes": [{"id": P1, "title": "Mail to Sven", "first": "Hi Sven, the contract", "secret": False,
                    "copied": False},
                   {"id": P2, "title": "Token", "first": "", "secret": True, "copied": False}],
        "blocked": True, "need": "pick the default",
        "find": PROMPT + "\n/home/tiroir/Projects/agentview\nfeat/fleet-push",
    }
    t.update(over)
    return t


def roster(*tiles, project="repo:github.com/thinkingtoo/agentview", name="agentview", flags=None):
    tiles = tiles or (tile(),)
    return {
        "columns": [{"project": project, "raw": "/home/tiroir/Projects/agentview", "kind": "repo",
                     "name": name, "context": {"line": "FleetView", "full": "FleetView"},
                     "sessions": list(tiles), "pills": []}],
        "flags": flags if flags is not None else [
            {"key": t["key"], "id": t["key"].partition(":")[2], "name": t["name"], "flag": t["flag"],
             "blocked": t["blocked"]} for t in tiles],
        "pastes": 2, "kept": [],
    }


INCLUDE = ["repo:github.com/thinkingtoo/agentview"]


class Projection(unittest.TestCase):
    def test_a_session_is_sent_with_the_listed_fields_only(self):
        body = push.projection(roster(), INCLUDE)
        self.assertEqual(body["columns"], [{"project": INCLUDE[0], "name": "agentview", "sessions": [{
            "name": "Rune", "flag": "waiting", "blocked": True, "since": 1793314847423,
            "line": "push.py for the hub", "need": "pick the default",
            "question": {"questions": [{"question": "Which default?", "header": "Default", "multi": False,
                                        "options": [{"label": "Include", "description": "send none"}]}]},
            "pastes": [{"id": P1, "title": "Mail to Sven", "secret": False},
                       {"id": P2, "title": "Token", "secret": True}],
        }]}])

    def test_a_project_not_included_never_leaves(self):
        self.assertEqual(push.projection(roster(), [])["columns"], [])
        self.assertEqual(push.projection(roster(), ["repo:github.com/thinkingtoo/other"])["columns"], [])

    def test_the_display_name_does_not_include_a_project(self):
        # Two columns can share a name; only the key says which project it is.
        self.assertEqual(push.projection(roster(), ["agentview"])["columns"], [])

    def test_a_line_read_from_the_prompt_or_the_branch_is_not_sent(self):
        for source, text in (("prompt", PROMPT), ("place", "feat/fleet-push"), ("place", "agentview")):
            body = push.projection(roster(tile(line=text, lineSource=source)), INCLUDE)
            self.assertEqual(body["columns"][0]["sessions"][0]["line"], "", source)

    def test_the_own_line_and_the_title_are_sent(self):
        for source in ("own", "did", "title"):
            body = push.projection(roster(tile(line="the hub push", lineSource=source)), INCLUDE)
            self.assertEqual(body["columns"][0]["sessions"][0]["line"], "the hub push", source)

    def test_a_credential_shape_in_any_field_is_hidden(self):
        hidden = push.HIDDEN
        question = {"questions": [{"question": "use " + TOKEN + "?", "header": TOKEN, "multi": False,
                                   "options": [{"label": TOKEN, "description": "token=" + TOKEN}]}]}
        t = tile(name="Rune " + TOKEN, line="sent " + TOKEN, need="paste " + TOKEN,
                 stuck={"kind": "needs", "source": "question", "reason": "Question", "context": question},
                 pastes=[{"id": P1, "title": "key " + TOKEN, "first": "", "secret": False, "copied": False}])
        body = push.projection(roster(t, name="agentview " + TOKEN), INCLUDE)
        column = body["columns"][0]
        self.assertEqual(column["name"], hidden)
        sent = column["sessions"][0]
        self.assertEqual([sent["name"], sent["line"], sent["need"], sent["pastes"][0]["title"]], [hidden] * 4)
        q = sent["question"]["questions"][0]
        self.assertEqual([q["question"], q["header"], q["options"][0]["label"], q["options"][0]["description"]],
                         [hidden] * 4)
        self.assertNotIn(TOKEN, json.dumps(body))

    def test_nothing_outside_the_list_reaches_the_body(self):
        text = json.dumps(push.projection(roster(), INCLUDE))
        for leak in (PROMPT, "/home/tiroir", "feat/fleet-push", "0b148296", "Hi Sven", "I merged it",
                     "git push", "FleetView", "asks you", "boss"):
            self.assertNotIn(leak, text)

    def test_a_paste_with_an_id_not_made_by_paste_py_is_left_out(self):
        t = tile(pastes=[{"id": "../../etc", "title": "odd", "secret": False},
                         {"id": P1, "title": "Mail to Sven", "first": "Hi", "secret": False}])
        sent = push.projection(roster(t), INCLUDE)["columns"][0]["sessions"][0]
        self.assertEqual(sent["pastes"], [{"id": P1, "title": "Mail to Sven", "secret": False}])

    def test_a_flag_outside_the_set_is_sent_as_none(self):
        r = roster()
        r["flags"][0]["flag"] = "thinking"
        self.assertIsNone(push.projection(r, INCLUDE)["columns"][0]["sessions"][0]["flag"])


    def test_a_token_broken_by_an_invisible_character_is_still_hidden(self):
        # Stripping the character would put the token back together after the check.
        for mark in ("\u200b", "\u00ad", "\u2060", "\ufeff", "\x00", "\n"):
            broken = TOKEN[:10] + mark + TOKEN[10:]
            body = push.projection(roster(tile(line="sent " + broken)), INCLUDE)
            self.assertEqual(body["columns"][0]["sessions"][0]["line"], push.HIDDEN, repr(mark))
            self.assertNotIn(TOKEN, json.dumps(body, ensure_ascii=False))

    def test_a_codex_title_is_its_first_prompt_and_is_not_sent(self):
        t = tile(provider="codex", key="codex:abc", line=PROMPT[:80], lineSource="title")
        self.assertEqual(push.projection(roster(t), INCLUDE)["columns"][0]["sessions"][0]["line"], "")

    def test_an_ask_read_from_the_transcript_is_not_sent(self):
        # Only a line the session wrote itself blocks; the rest is lifted from what it said.
        t = tile(blocked=False, need="Shall I read /home/tiroir/secret-client/contract.pdf?")
        self.assertEqual(push.projection(roster(t), INCLUDE)["columns"][0]["sessions"][0]["need"], "")

    def test_a_lone_surrogate_does_not_stop_the_push(self):
        body = push.projection(roster(tile(line="cut \ud83d")), INCLUDE)
        json.dumps(body, ensure_ascii=False).encode("utf-8")

    def test_a_tile_that_cannot_be_read_is_left_out_and_the_rest_goes(self):
        # A question without its context cannot be read; a missing stop no longer drops a tile (since is None).
        odd = tile(name="Odd", key="claude:odd", stuck={"source": "question", "context": None}, pastes=None)
        sent = push.projection(roster(odd, tile()), INCLUDE)["columns"][0]["sessions"]
        self.assertEqual([s["name"] for s in sent], ["Rune"])

    def test_a_stamp_the_hub_refuses_is_sent_as_none(self):
        # The hub answers 400 for the whole push on a since outside 0 <= ms < 10**14 (#173).
        for stop in (-1, 10 ** 14, float("inf"), float("nan"), True, "1793314847423"):
            with self.subTest(stop=stop):
                sent = push.projection(roster(tile(stop=stop)), INCLUDE)["columns"][0]["sessions"]
                self.assertEqual([(s["name"], s["since"]) for s in sent], [("Rune", None)])

    def test_the_edges_of_the_range_are_kept(self):
        for stop, since in ((0, 0), (10 ** 14 - 1, 10 ** 14 - 1), (1793314847423.9, 1793314847423)):
            with self.subTest(stop=stop):
                self.assertEqual(push.projection(roster(tile(stop=stop)), INCLUDE)["columns"][0]["sessions"][0]["since"],
                                 since)

    def test_a_tile_without_stop_is_sent_with_since_none(self):
        t = tile()
        del t["stop"]
        sent = push.projection(roster(t), INCLUDE)["columns"][0]["sessions"]
        self.assertEqual([(s["name"], s["since"]) for s in sent], [("Rune", None)])

    def test_a_column_that_cannot_be_read_is_left_out(self):
        r = roster()
        r["columns"] += [{"project": ["x"], "name": "odd", "sessions": []},
                         {"project": INCLUDE[0], "name": "odd", "sessions": {"a": 1}}]
        names = [c["name"] for c in push.projection(r, INCLUDE)["columns"]]
        self.assertEqual(names, ["agentview", "odd"])


class Token(unittest.TestCase):
    def test_the_newline_mint_prints_is_taken_off(self):
        self.assertEqual(push.clean_token("tok-123\n"), "tok-123")

    def test_a_token_a_header_cannot_carry_is_refused(self):
        for bad in ("tok\nen", "tok en", "tök", "", None):
            self.assertIsNone(push.clean_token(bad), repr(bad))


class Hub:
    """The hub as `once` sees it: what was posted, and what it answers."""

    def __init__(self, status=204):
        self.status, self.got = status, []

    def __call__(self, url, token, body):
        self.got.append((url, token, json.loads(body)))
        return self.status


class Once(unittest.TestCase):
    def setUp(self):
        self.state = Path(tempfile.mkdtemp()) / "push.json"
        self.tokens = []

    def token(self):
        self.tokens.append(1)
        return "device-token"

    def once(self, hub, now, include=INCLUDE, data=None):
        return push.once(include=include, read=lambda: data or roster(), post=hub, token=self.token,
                         url="https://hub.example/fleet-push", state=self.state, now=now)

    def test_a_change_is_posted_with_the_token(self):
        hub = Hub()
        self.assertEqual(self.once(hub, 1_000_000), "sent")
        (url, token, body), = hub.got
        self.assertEqual((url, token, body["v"], body["at"]), ("https://hub.example/fleet-push", "device-token", 1, 1_000_000))
        self.assertNotIn("device", body)
        self.assertEqual(body["columns"][0]["project"], INCLUDE[0])

    def test_nothing_changed_is_not_posted_until_the_heartbeat(self):
        hub = Hub()
        self.once(hub, 1_000_000)
        self.assertEqual(self.once(hub, 1_000_000 + 20_000), "unchanged")
        self.assertEqual(len(hub.got), 1)
        self.assertEqual(self.once(hub, 1_000_000 + push.HEARTBEAT_MS), "sent")
        self.assertEqual(len(hub.got), 2)

    def test_a_refused_push_is_tried_again_next_round(self):
        self.once(Hub(429), 1_000_000)
        hub = Hub()
        self.assertEqual(self.once(hub, 1_020_000), "sent")

    def test_with_nothing_included_nothing_is_read_or_sent(self):
        hub = Hub()
        self.assertEqual(self.once(hub, 1_000_000, include=[]), "nothing included")
        self.assertEqual((hub.got, self.tokens), ([], []))

    def test_emptying_the_list_clears_the_hub_once(self):
        self.once(Hub(), 1_000_000)
        hub = Hub()
        self.assertEqual(self.once(hub, 1_020_000, include=[]), "sent")
        self.assertEqual(hub.got[0][2]["columns"], [])
        self.assertEqual(self.once(hub, 1_040_000, include=[]), "nothing included")
        self.assertEqual(len(hub.got), 1)

    def test_a_body_too_big_for_the_hub_is_cut_to_fit(self):
        big = {"questions": [{"question": "q" * 300, "header": "h" * 60, "multi": False,
                              "options": [{"label": "l" * 60, "description": "d" * 200}] * 6}] * 4}
        tiles = [tile(key=f"claude:{i}", name=f"S{i}", stuck={"source": "question", "context": big},
                      line="x" * 200) for i in range(40)]
        data = {"columns": [roster(*tiles, project=f"repo:x/{c}")["columns"][0] for c in range(8)],
                "flags": roster(*tiles)["flags"]}
        hub = Hub()
        self.assertEqual(self.once(hub, 1_000_000, include=[f"repo:x/{c}" for c in range(8)], data=data), "sent")
        self.assertLessEqual(len(json.dumps(hub.got[0][2], ensure_ascii=False).encode()), push.MAX_BODY)
        self.assertTrue(hub.got[0][2]["columns"])

    def test_without_a_token_nothing_is_sent(self):
        hub = Hub()
        got = push.once(include=INCLUDE, read=roster, post=hub, token=lambda: None,
                        url="https://hub.example/fleet-push", state=self.state, now=1_000_000)
        self.assertEqual((got, hub.got), ("no token", []))


if __name__ == "__main__":
    unittest.main()
