# H-03 Script Materials Approval

Status: approved draft
Task: H-03 - 审核话术底料（问候/转化/拒绝等）业务合规
Prepared on: 2026-05-20

## Approved Materials

The approved script materials live in:

- `config/h03_approved_script_materials.json`

This file contains 50 approved seed items. It is intended as the business
approval source for P3-02 (`scripts_seed.sql`) and later script matching work.
The user may edit the wording in later review rounds without changing the
structure.

## Category Coverage

| Category | Count | Purpose |
|---|---:|---|
| `greeting` | 10 | Inbound and reply openers |
| `conversion` | 10 | VIP, price, benefit, objection, purchase, post-payment |
| `refusal` | 10 | Safety, boundary, medical/legal/political, internal-rule refusal |
| `probe` | 10 | Profile completion and preference discovery |
| `retention` | 10 | Gentle outbound return-chat prompts |

Total approved materials: 50.

## Review Rules

- All items use `review_status: "approved"`.
- The content is seed material, not immutable final copy.
- Future wording edits should preserve the `key`, `category`, and
  `review_status` unless the item is intentionally withdrawn.
- Conversion scripts must not be used in S5 crisis recovery, suspected minor,
  or marketing opt-out contexts.
- Refusal scripts must stay short, safe, and non-argumentative.
- Probe scripts must ask for only one lightweight detail at a time.
- Retention scripts must be gentle and avoid pressure or guilt.

## Acceptance

- [x] At least 50 script materials are approved.
- [x] Greeting, conversion, and refusal categories are included.
- [x] Probe and retention support downstream P2/P3 tasks.
- [x] Materials are stored in a config file that the user can edit later.
