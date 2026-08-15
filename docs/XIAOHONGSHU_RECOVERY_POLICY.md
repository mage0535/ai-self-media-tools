# Xiaohongshu Recovery Policy

## Non-negotiable boundary

Xiaohongshu is `manual_handoff_only`. The system must never upload, schedule,
or create a platform draft. This is enforced in code before publisher routing,
in delivery health classification, and by `scripts/xhs_manual_publish_gate.py`.
Configuration cannot re-enable an automatic route.

## Required handoff

The operator receives the full title, body, topics, publishing guide, cover,
and at least three readable images as separate Hermes media messages. A task
may enter `handoff_pending` only after a delivery receipt confirms that the
text and every image were sent. Missing operator delivery remains `blocked`.

The account owner alone publishes in the Xiaohongshu app or creator center and
records the post-publication confirmation.

## Recovery strategy

- Keep one lane: practical AI efficiency systems, not generic tool reviews.
- Lead each carousel with a useful result or proof, then provide a checklist,
  example, and a save-worthy template.
- Prefer authentic product screenshots and licensed real-scene assets over
  decorative AI imagery.
- Use concise human Chinese: result first, no exaggerated promises, no external
  traffic diversion, and no more than six relevant topics.
- Publish conservatively after account recovery. Review saves, comments,
  profile-to-follow conversion, and cover click-through at 1, 24, and 72 hours
  before increasing cadence.

## Executable recovery contract

Every handoff package contains `growth_strategy` and is rejected unless it
identifies the recovery lane, a first-image payoff, a save value, a minimum
36-hour interval, and the 1/24/72-hour review schedule. This is checked by
`scripts/xhs_manual_publish_gate.py` before delivery. It does not publish or
schedule anything: the owner remains the only person who can publish.

Start with no more than four posts in the first seven days. Do not increase
cadence until three post-publication reviews are complete and no account-health
warning is present. The delivery package is a pre-publication checklist, not a
claim that those later metrics already exist.
