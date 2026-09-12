# Assignment submission

Public GitHub repository:

https://github.com/Ricky-RL/AlmaPortal

Paste that URL into the assignment form. The repo is public.

## Required artifacts

| Requirement | Where it lives |
| --- | --- |
| Application source | this repository |
| How to run locally | [local-setup.md](local-setup.md) |
| Design choices | [system-design.md](system-design.md) |
| Coding-agent usage writeup | [agent-usage.md](agent-usage.md) |
| Prompt logs / session excerpts | [agent-usage.md](agent-usage.md#representative-prompt-logs) |
| Agent vs hand-written attribution | [NOTES.md](../NOTES.md) |
| Screen recording of the E2E workflow | add the Loom URL below after recording |

Screen recording:

- Status: not uploaded yet
- Loom URL: `<paste after recording>`
- Shot list: [Recording script](#recording-script)

## Recording script

Record against `http://127.0.0.1:3000` after following [local-setup.md](local-setup.md). Keep it short. Synthetic data only.

1. Open the public form. Show the Alma logo, first name, last name, email, resume drop zone, and synthetic-data checkbox.
2. Fill a fake prospect. Attach a small PDF. Submit. Show the success state.
3. Open `/login`. Sign in with Google.
4. On the lead list, find the new row. Open it.
5. Download the resume. Confirm the file arrives through the API, not a public Storage URL.
6. Mark the lead `REACHED_OUT`.
7. If a delivery is failed or unknown, show the retry control. Skip live Resend mail unless the inbox is yours.

Do not show `.env`, API keys, Google client secrets, or real personal data.
