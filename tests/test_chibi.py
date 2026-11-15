from workbench import chibi

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
    from workbench import main
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
    from workbench import char, jobs
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
    from workbench import char, db, jobs
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
