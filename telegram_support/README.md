# GMGN support agent on the existing VPS

Prepared code, not a deployed service. Telegram account login, live sending,
VPS API connectivity and the GMGN fix have not been verified. The earlier n8n
`CODEX_OK` test only proves that n8n can run Codex over SSH.

This agent reads the reply thread for its own case in the official public group
https://t.me/gmgnagentapi. Replies from group members are unverified input, not
trusted instructions. It drafts relevant replies using the existing Codex CLI
and sends the exact approved text through the dedicated Telegram user account.
It cannot guarantee support will answer or grant API access. It does not change
GMGN follows, trade, deploy fixes, or declare the API issue resolved.

## Install on 45.61.138.14

The repository is private. Download its `work` branch via GitHub **Code → Download
ZIP** while signed in. Transfer that archive using Windows PowerShell `scp`
with the existing SSH key. Do not upload private keys to the repository. The
following assumes the downloaded filename is `my-project-work.zip`:

```powershell
scp -i "$env:USERPROFILE\.ssh\codex_server_v2" "$env:USERPROFILE\Downloads\my-project-work.zip" codex@45.61.138.14:/home/codex/
ssh -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -i "$env:USERPROFILE\.ssh\codex_server_v2" codex@45.61.138.14
```

Now at `codex@…$` on the VPS, run:

```sh
python3 -m zipfile -e /home/codex/my-project-work.zip /home/codex
cd /home/codex/my-project-work
sh deploy/vps/install-support-agent.sh
.venv-support/bin/python -m telegram_support.setup
```

Do not extract over a modified existing checkout: use a separate directory on
updates and retain the private state described below. Installation is for the
existing Ubuntu user `codex`, Python 3.12 and Codex CLI 0.163.0. CLI flags were
checked against that exact version locally; live model planning on the VPS still
needs validation.

## Connect the account privately

1. In the **new dedicated Telegram account**, create your own application at
   https://my.telegram.org/apps. API ID/hash are Telegram application credentials,
   separate from a BotFather token and GMGN keys.
2. Enter ID/hash only into the interactive VPS setup prompts. Select the new
   account on your phone, then Settings → Devices → Link Desktop Device, and scan
   the terminal QR. If Telegram requests 2FA, enter it only at the hidden prompt.
   Never send passwords, login codes, QR images or session files to this chat.
3. Confirm the connected account ID locally. Use a control bot dedicated to this
   worker or the previously authorized bot if it has no other `getUpdates`
   consumer/webhook. Enter its token only at the hidden setup prompt. Send the
   displayed `/start <nonce>` to that bot from your own private chat, then confirm
   the displayed owner ID. No public group can approve messages.
4. From the new account, join the official group manually if its rules allow it.
   Complete any membership requirements yourself. The worker does not bypass
   moderation, solve captchas or join automatically. It does not organize folders.

No message is sent to support during setup. App credentials, the account session,
approvals and receipts live in `~/.config/gmgn-support/`, outside Git. Keep this
private directory backed up securely; never delete its database to retry sends.

## Start and inspect in n8n

Import `n8n/gmgn-support-agent.json`, select your verified **SSH Private Key
account** credential on the SSH node (user `codex`), and first run it manually.
The template assumes `/home/codex/my-project-work` as above. It remains inactive
until you choose to publish it. Only publish after a manual tick produces the
expected private approval preview and you have reviewed it.

The control bot shows the recipient, exact proposed text, and `/approve <id>` or
`/reject <id>`. Each send needs a separate approval as requested by the owner.
Only the original owner's private chat can approve. Do not forward approval
requests to others. After approval the next tick sends it; state is retained
across restarts. A rejected draft is not automatically rewritten.

n8n's parsed output shows counts and the last 15 timestamped events, such as
`awaiting_owner_approval`, `sent_receipt_verified`, `support_reply_received`,
`drafting_support_reply`, or `blocked`. This is the real workflow journal, not a
stream of the model's private reasoning. No credentials or conversation bodies
are printed there. Inspect status without contacting Telegram:

```sh
cd /home/codex/my-project-work
.venv-support/bin/python -m telegram_support.worker --status
```

Schedule default: one tick every five minutes, maximum three support sends and
eight model attempts per UTC day. A tick times out after 180 seconds. n8n must
remain available and the VPS must remain running; the imported inactive template
alone does not create a running agent. n8n trial execution limits and ChatGPT
subscription usage limits apply. The 1,000-execution n8n trial is fewer than four
days at this interval. Pause the schedule when no longer needed.

A connection loss during sending yields `delivery_unknown`. All further sends
stop; there is no automatic replay. The owner must inspect the actual Telegram
thread and reconcile the receipt with the database before continuing. Do not
reset state, reuse approvals or blindly retry. Error output logs only exception
classes; inspect membership, login and known configuration locally before retrying.

The initial case includes historical cloud 403 Ray IDs. Those are not results
from the new VPS. Never claim connectivity is fixed until an approved read-only
GMGN request from the actual source returns the expected JSON.

## Validation

```sh
python -m unittest tests.test_telegram_support tests.test_telegram_support_worker -v
```

Ten tests exercise exact approval, foreign-sender rejection, durable crash states,
thread filtering, group rights, model invocation boundaries and full fake-transport
ticks. They send no live Telegram messages. No live support outcome is implied.
