# Browse: give the character a web task, steer its plan, watch it use a real browser inside its world

## Intent
You give the character a task in words ("go to youtube and play a song you like"). It plans, you see and steer the plan,
then it uses a real browser while you watch, inside its own world: Dot's dots build a screen and the live page plays on it.
A checker confirms each step really happened, it learns from its mistakes, and it writes down recipes for what worked.
Immersion is the key: nothing opens outside the scene on purpose.

## Flow
1. `/browse <task>` in the character's chat box (`/browse` alone says how).
2. **Plan**: one model call writes its intent and a list of commands. It is told its recipe for the site the task names
   and its latest lessons.
3. **Steer**: the plan waits on screen. Edit any line, or type a note and press Plan again. Go starts it.
4. **Run**: real Chrome (its own throwaway profile, never yours) runs off screen; its live picture streams as MJPEG onto
   Dot's screen and its sound plays from the Mac. Before a click it shows the target box and waits a beat, so the little
   Dot travels there and taps. Stop lands between steps; Close browser ends the music.
5. **Checker** (plain code): before the run it rejects commands that cannot work (unknown, no address, over budget,
   clicking before a page is open) and repairs what a small model glues on. After each step it marks it done or failed with
   why: an error page (404) is a failed open, a click on an empty list waits for a page that draws itself late, play is
   only done when the video really plays.
6. **Opinion**: what it did and what it thinks, scored for grounding, saved as a note.

## Learning
- **Lessons**: every failed step goes to the feedbacker (`char._fail("browse")`) as a written row; each plan sees the
  latest. Two slips and the feedbacker drafts a fix for the browse prompt, which reaches the prompt only after you approve
  it in Wiring (the app's existing rule).
- **Recipes**: a browse that works end to end is written down as its site's recipe, the task's words left as
  `<what you want>`. `/recipes` (or the Recipes button) shows them: read, change, forget, or teach one. Yours are never
  overwritten by what it learns; it only counts that they worked.

## Commands (data in `harness_char/browse.py`)
`open`, `search`, `click <what, in words>`, `play`, `wait <seconds>`, `read <words>`, `scroll`, `opinion`.
At most 10 steps and 4 clicks.

## Approaches considered
- Text copy of the page (built first): no dependency, but pages that need JavaScript (YouTube) show nothing. Dropped.
- Visible Chrome window beside the app: breaks immersion.
- Hidden real Chrome streamed into Dot's screen (picked): Playwright with the installed Chrome, no Chromium download.

## Constraints
One model in memory: uses whichever chat model is loaded, no swap. Refuses while a harness cycle or training run holds
the model; idle learning stands aside while it plans or runs. Errors said plainly (model down, Chrome would not start,
page would not load).
