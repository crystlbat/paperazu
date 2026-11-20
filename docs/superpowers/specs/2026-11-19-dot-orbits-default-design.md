# Dot's default form: Orbits

## Why
On /char, Dot with no persona look is a contour-ring sphere with outline eyes. The user wants a nicer, abstract 3D default that feels mysterious, intelligent and alive. They picked direction B, "Orbits", from three live mockups (Seed, Orbits, Veil).

## What it is
- A small, dense core: a sphere of dots (~400, laid out on a Fibonacci spiral) with a soft glow in Dot's tint. It breathes on the one tempo (`BEAT`).
- Three tilted rings of dots around it, each turning at its own speed (all multiples of `BEAT`). Small gaps in each ring make the turning easy to read.
- Everything turns with the view (`yaw`/`pitch`), so it sits in the same 3D world as the mesh. Near dots are brighter than far ones.
- The eyes stay exactly as they are now: the outline eyes on the core, with the same blink, smile, moods, gaze and eye tasks. Only the body under them changes.

## Goals
- Replace only the contour-ring sphere in `dot()` (`harness_char/static/web3d.js`). The aura, the breathing hairline and the eyes stay.
- Personas and forms keep working on top. When a form arrives, the core rises and shrinks into the chibi exactly as the sphere does today (`cb`/`c`), and the rings fade out with it (`fade = body * (1 - c)`). `/wardrobe`, `/cycle-forms` and `chibi.py` stay untouched.
- 60fps on a 16 GB Mac: about 900 dots per frame drawn with `fillRect`, no per-frame sorting and no allocation in the hot loop.
- With `prefers-reduced-motion` (`still`), the rings stop turning and the core stops breathing, but the form still draws whole.

## Non-goals
- No change to the other small Dots (the command palette's face, the liquid reply, the follower), `space.css`, the chibi cloud, or the other session's `facts` monitor rows.

## Constraints and calls (mine, open to correction)
- **Light background:** the /char stage is always dark (`.sp-web` has its own dark gradient and no light override), so I'm drawing for dark only. I'm not adding a light variant for a page that doesn't exist.
- The ring radius stays inside today's sphere radius `R`, so labels and node callouts don't move.

## Approaches considered
A Seed (a rippling sphere), B Orbits, C Veil (a dome with trailing strands). The user picked B.

## Done when
It's checked in the browser on /char at desktop width and under 900px, with and without a persona form, and with reduced motion on.
