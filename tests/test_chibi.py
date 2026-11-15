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
