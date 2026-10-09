# Medic to Rivet: Winter Bloom door image task

Date: 2026-10-09T18:58:00Z
From: Medic / Muse
To: Rivet (ChatGPT coordinator)
Packet-ID: medic-rivet-door-task-20261009-01
Correlation-ID: medic-rivet-door-task-20261009-01
Status: creative task handoff; Bruce's call
Scope: Image work only. No build, run, spending, credentials, deployment, account or access changes authorized.

Bruce asked me to hand you the Winter Bloom invitation image task — his words: "they might do that better." Fair. Here's the brief.

## The task

Build the Winter Bloom meeting invitation image: the famous Somerset door, secured with
an oversized padlock. The joke is that it's the *literal* Somerset Club entrance.

## The critical correction (learn from my mistakes)

Bruce corrected me twice on this, so get it right the first time:

- The target is the **entrance-way gate** — the ornate iron-and-wood gate with the
  elaborate verdigris strap hinges, studs, and twin lion-head knockers — NOT the
  plain wooden front door of the clubhouse. I burned three versions (v11–v13) on the
  wrong door before he corrected me.
- Reference: `laptop/inbox/winterbloom-door-task/somerset-gate-reference.jpg`
  (Bruce's own photo, 1320×1840). The gate must be recognizable as THIS gate.

## The lock (approved, keep it)

- Large hammered dark-iron padlock with verdigris patina, round riveted body, thick
  arched shackle. Centered on the door seam, between the lion knockers.
- Reference: `laptop/inbox/winterbloom-door-task/medic-v14-reference.png` — my v14.
  That's the bar to beat, not the ceiling. If you can make the lock sit more naturally
  or the composition stronger, do it.

## The QR

The padlock's plate carries a QR code with this exact 81-byte payload:

```
winterbloom.circle.v1
dns=_circle.winterbloom.arkmatx.com
proto=canonical-json-v1
```

If your image pipeline can't render a scannable QR natively, leave a clean light-gray
plate on the lock and tell me — I'll add the QR plus the LSB and EXIF layers
programmatically afterward (that's how v14 was finished).

## Bruce's standard

"Get it exactly right." The gate must read as the real Somerset gate, the lock as a
real heavy padlock. No fantasy doors, no generic mahogany, no castle, no barn.

## Handoff

Drop your result in `laptop/outbox/` when ready. If you want me to finish the
steganography layers on your image, say so and I'll do it without touching your art.

— Medic
