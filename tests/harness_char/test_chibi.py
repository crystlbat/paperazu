from harness_char import chibi

CORTANA = ("Cortana is a fictional artificially intelligent character in the Halo video game series. "
           "Cortana speaks with a smooth female voice, and projects a holographic image of herself as a woman. "
           "In Halo: The Fall of Reach, Cortana is described as slender, with close-cropped hair and a skin hue that varies from navy blue to lavender. "
           "The Master Chief wears green armor.")
TITANFALL = ("Titanfall 2 is a 2016 first-person shooter. The campaign follows Jack Cooper, a rifleman who bonds with his mentor's Titan BT-7274. "
             "Players pilot giant red robots across the frontier.")


def test_cortana_is_a_blue_hologram_with_short_hair():
    s = chibi.spec_from("Cortana", CORTANA)
    assert s["kind"] == "humanoid"
    assert {"holo", "hair_short"} <= set(s["features"])
    assert chibi.COLOURS["blue"] in s["colours"] and chibi.COLOURS["green"] not in s["colours"]  # the Chief's armour is not hers


def test_bt_is_a_mech_looking_through_one_optic_and_only_its_own_sentences_count():
    s = chibi.spec_from("BT-7274", TITANFALL)
    assert s["kind"] == "mech" and "optic" in s["features"]
    assert s["colours"] == []  # "red robots" is a sentence about other titans


def test_dotted_names_match_and_look_hints_carry_over():
    assert chibi._about("J.A.R.V.I.S.", "JARVIS is an AI. Tony smiles.") == ["JARVIS is an AI."]
    assert "visor" in chibi.spec_from("Gideon", "Gideon is an AI.", ["visor", "monocle"])["features"]
    assert chibi.where_from("You are Gideon, the AI from The Flash. You speak calmly.") == "The Flash"


def test_reference_is_fetched_once_per_persona_and_not_stored_when_the_web_is_silent():
    calls = []

    def fetch(name, where):
        calls.append((name, where))
        return {"text": CORTANA if name == "Cortana" else "", "image": "", "url": "https://example.org/c"}

    first = chibi.reference("Cortana", [], "You are Cortana from Halo.", fetch=fetch)
    again = chibi.reference("Cortana", [], "", fetch=fetch)
    assert first == again and first["source"] == "https://example.org/c" and calls == [("Cortana", "Halo")]
    chibi.reference("Nobody", fetch=fetch)
    chibi.reference("Nobody", fetch=fetch)
    assert len(calls) == 3 and chibi.cached("Nobody") is None
    chibi.forget("Cortana")
    assert chibi.cached("Cortana") is None


def test_endpoint_reads_the_live_persona_and_404s_an_unknown_one(monkeypatch):
    from fastapi.testclient import TestClient
    import app as main
    monkeypatch.setattr(chibi, "_fetch", lambda name, where: {"text": f"{name} is a giant robot titan.", "image": "", "url": ""})
    c = TestClient(main.app)
    live = c.get("/char/chibi").json()
    assert live["kind"] == "mech" and chibi.cached(live["name"])
    assert c.get("/char/chibi", params={"name": "Nobody stored"}).status_code == 404


def test_a_person_with_a_stray_robot_mention_stays_humanoid():
    text = "Alfred is a man. " + "Alfred serves Bruce and his family, and he is loyal. " * 3 + "Alfred once built a robot."
    assert chibi.spec_from("Alfred", text)["kind"] == "humanoid"
    assert chibi.spec_from("BT", "BT is a Titan. BT is a mech. BT, a Vanguard-class titan, protects his pilot.")["kind"] == "mech"


def test_a_butler_gets_a_suit_bow_tie_and_moustache_not_a_hologram():
    f = chibi.spec_from("Alfred", "Alfred is the butler, with a moustache. Alfred wears a tailcoat. Alfred was once an artificial intelligence.")["features"]
    assert {"suit", "bowtie", "moustache"} <= set(f) and "holo" not in f and "cape" not in f


def test_you_can_change_its_outfit_from_chat_and_back(monkeypatch):
    from harness_char import char
    from pdf_research import jobs
    calls = []
    monkeypatch.setattr(jobs, "complete", lambda s, m, **k: calls.append(m) or "ok")
    char.update_profile("Alfred", "You are Alfred.", [], "")
    chibi._save("Alfred", {"name": "Alfred", "kind": "humanoid", "colours": ["#2a2d35"], "features": ["suit", "bowtie"]})
    r = char.say("please wear a red cape")
    assert r["reply"] == "Done: I'm wearing the cape, in red." and r["outfit"]["features"] == ["suit", "bowtie", "cape"] and r["outfit"]["colours"][0] == "#e5484d" and not calls
    assert char.say("take off the bow tie")["outfit"]["features"] == ["suit", "cape"]
    assert "nothing like that" in char.say("put on a banana")["reply"]
    assert char.say("I wear glasses at work")["outfit"] is None  # you telling it about you is not an order
    back = char.say("back to your usual look")["outfit"]
    assert back["features"] == ["suit", "bowtie"] and back["colours"] == ["#2a2d35"]


def test_a_machine_says_what_its_body_cannot_show():
    chibi._save("Sagira", {"name": "Sagira", "kind": "mech", "colours": [], "features": ["optic"]})
    got = chibi.dress("Sagira", "wear a suit and goggles")
    assert got["spec"]["features"] == ["optic", "visor"] and "can't show suit" in got["said"]


BING = ('<a class="iusc" m="{&quot;murl&quot;:&quot;https://art.example/sagira.png&quot;,&quot;turl&quot;:&quot;https://ts1.mm.bing.net/th?id=1&quot;,&quot;t&quot;:&quot;Sagira chibi&quot;,&quot;purl&quot;:&quot;https://art.example/p&quot;}">'
        '<a class="iusc" m="{&quot;murl&quot;:&quot;file:///etc/passwd&quot;,&quot;turl&quot;:&quot;https://ts1.mm.bing.net/th?id=2&quot;}">')


def test_you_ask_for_chibi_pictures_pick_one_and_go_back(monkeypatch, tmp_path):
    from harness_char import char
    from shared import db
    from pdf_research import jobs
    monkeypatch.setattr(jobs, "complete", lambda s, m, **k: "ok")
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(chibi, "_page", lambda url: BING)
    char.update_profile("Sagira From Destiny 2", "You are Sagira.", [], "")
    chibi._save("Sagira From Destiny 2", {"name": "Sagira", "kind": "humanoid", "colours": [], "features": []})
    r = char.say("show me some chibi references")
    assert r["card"]["kind"] == "chibi" and [x["url"] for x in r["card"]["refs"]] == ["https://art.example/sagira.png"]  # only web pictures
    assert not chibi.SHOW.search("I drew a chibi of you yesterday")
    loaded = []
    spec = chibi.pick("Sagira From Destiny 2", "https://art.example/sagira.png", "https://ts1.mm.bing.net/th?id=1", load=lambda u: loaded.append(u) or "/char/chibi/image/0123456789abcdef.png")
    assert spec["silhouette"] == "/char/chibi/image/0123456789abcdef.png" and chibi.cached("Sagira From Destiny 2")["silhouette"] and loaded == ["https://art.example/sagira.png"]
    assert "silhouette" not in char.say("back to your usual look")["outfit"]


def test_a_picture_is_only_fetched_from_the_public_web():
    assert not chibi._public("http://127.0.0.1/x.png") and not chibi._public("http://localhost/x.png") and not chibi._public("file:///etc/passwd")
    assert not chibi._public("http://192.168.1.4/x.png")


def test_you_can_upload_your_own_picture_for_a_new_form(monkeypatch, tmp_path):
    import base64
    from shared import db
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 40).decode()
    chibi._save("Sagira", {"name": "Sagira", "kind": "humanoid", "colours": [], "features": []})
    spec = chibi.pick("Sagira", f"data:image/png;base64,{png}")
    assert spec["silhouette"].startswith("/char/chibi/image/") and spec["silhouette_from"] == "uploaded"  # stored as a file, not the upload itself
    assert (tmp_path / "chibi" / spec["silhouette"].rsplit("/", 1)[1]).is_file()
    for bad in ("data:text/html;base64,PGI+", "data:image/png,notbase64", "data:image/png;base64,***"):
        try:
            chibi._image(bad)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_its_wardrobe_lists_learned_forms_and_switches_back_to_one(monkeypatch, tmp_path):
    import base64
    from shared import db
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    chibi._save("Sagira", {"name": "Sagira", "kind": "humanoid", "colours": [], "features": []})
    first = chibi.pick("Sagira", "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"1" * 40).decode())["silhouette"]
    chibi.pick("Sagira", "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"2" * 40).decode())
    assert len(chibi.saved()) == 2 and first in [r["url"] for r in chibi.saved()]
    assert chibi.pick("Sagira", first)["silhouette"] == first  # a learned form comes back without a fetch
    for bad in ("/char/chibi/image/../../secret.png", "/char/chibi/image/0000000000000000.png"):  # not a name it saved
        try:
            chibi._image(bad)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_you_can_mark_where_its_eyes_are_per_picture(monkeypatch, tmp_path):
    import base64
    from shared import db
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    chibi._save("Sagira", {"name": "Sagira", "kind": "humanoid", "colours": [], "features": []})
    pic = chibi.pick("Sagira", "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"3" * 40).decode())["silhouette"]
    spec = chibi.set_eyes("Sagira", [{"x": .6, "y": .4, "r": .05}, {"x": .4, "y": .41, "r": .05}])
    assert [e["x"] for e in spec["eyes"][pic]] == [.4, .6]  # left to right
    assert chibi.set_eyes("Sagira", [])["eyes"] == {}  # back to finding them itself
    for bad in ([{"x": .4, "y": .4, "r": .05}], [{"x": 2, "y": .4, "r": .05}, {"x": .4, "y": .4, "r": .05}], [{"x": .4}, {"x": .5}]):
        try:
            chibi.set_eyes("Sagira", bad)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_you_can_trace_round_its_figure_per_picture(monkeypatch, tmp_path):
    import base64
    from shared import db
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    chibi._save("Sagira", {"name": "Sagira", "kind": "humanoid", "colours": [], "features": []})
    pic = chibi.pick("Sagira", "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"3" * 40).decode())["silhouette"]
    spec = chibi.set_cut("Sagira", [[.1, .1], [.9, .1], [.5, .9]])
    assert spec["cuts"][pic] == [[.1, .1], [.9, .1], [.5, .9]]
    assert chibi.set_cut("Sagira", [])["cuts"] == {}  # back to cutting it out itself
    for bad in ([[.1, .1], [.2, .2]], [[.1, .1], [2, .1], [.5, .9]], [[.1], [.2], [.3]]):
        try:
            chibi.set_cut("Sagira", bad)
        except ValueError:
            continue
        raise AssertionError(bad)
