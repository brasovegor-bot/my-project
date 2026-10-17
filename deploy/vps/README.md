# Codex CLI on a separate VPS

The VPS is a separate machine from the Codex chat workspace. This chat has no
authenticated SSH connection to it. The owner's private SSH key was created on
Windows and entered by the owner in n8n Credentials for the SSH connection.
Do not request that key, its passphrase, or device-login codes in chat.

## Verified by the owner

Ubuntu 24.04 LTS x86_64, 4 GB RAM / 2 vCPU. The owner updated packages,
rebooted into the updated kernel, installed git/curl/ca-certificates/python3-venv/
nodejs/npm, and created an unprivileged `codex` user:

```sh
adduser --disabled-password --gecos "" codex
su - codex
npm install -g --prefix "$HOME/.local" @openai/codex
~/.local/bin/codex --version
~/.local/bin/codex login --device-auth
~/.local/bin/codex login status
```

Observed versions: Node 18.19.1, npm 9.2.0, Git 2.43.0, codex-cli 0.163.0.
Login reported `Logged in using ChatGPT`. The owner confirmed that the following
manual check answered successfully (this agent has not executed it on the VPS):

```sh
~/.local/bin/codex exec --skip-git-repo-check --sandbox read-only "Reply exactly: CODEX_OK"
```

ChatGPT device-code login must be enabled in the same account's security settings.
Use a fresh code after enabling it. OAuth state stays in the VPS user's home;
never copy authentication files into GitHub, n8n workflow JSON or execution logs.

## SSH from n8n: live node test verified

`codex` was created with no password. The owner installed the root-authorized
public key in this user's previously unconfigured authorized_keys. The first
n8n test returned code 0, stdout `codex`, empty stderr for `whoami`.
Do not assume that root's login key automatically authorizes another user on
other installations. Preserve any existing authorized keys. Permissions must be 0700 for
`/home/codex/.ssh`, 0600 for `authorized_keys`, both owned by `codex:codex`.

Import `n8n/codex-smoke-test.json` into n8n, or create equivalent Manual Trigger
and SSH nodes. Bind a new **SSH Private Key** credential in n8n's credential form:

- Host: the new VPS IP, port 22, username `codex`.
- Private Key: the owner's dedicated Windows private key file (without `.pub`).
  Open/copy it locally into the trusted n8n Credentials form only; never chat.
- Passphrase: the tested passphrase for that same key.
- Prefer a separate n8n-only key installed for `codex` before durable operation.
  Reusing an owner's root-authorized key also gives that credential root access
  if it is used with root; simply setting username=codex is not key-level isolation.

The shipped workflow contains no credentials, IPs, wallet addresses or secrets.
It is inactive, manually triggered, with no incoming webhook or schedule.
It runs a fixed read-only model test under a 120-second timeout.
Inspect the SSH output: require exit code 0 and the model's final `CODEX_OK`.
A green n8n node alone does not prove the remote command succeeded; n8n SSH can
return a nonzero remote exit code as output. Timeout also means failure, not success.

Node parameter names were checked against upstream `n8n-io/n8n`'s
`packages/nodes-base/nodes/Ssh/Ssh.node.ts`.

On October 18, 2026 (Moscow), the owner's screenshot verified a manually configured
SSH node executing the 120-second read-only Codex test: code 0, stdout `CODEX_OK`.
The command ran as `codex` from `/home/codex`, codex-cli 0.163.0, using ChatGPT
authentication. stderr contained diagnostic logging and a warning about missing
system bubblewrap; the CLI reported using its bundled bubblewrap. That warning
did not prevent this test. It does not establish an isolation guarantee for other
tasks. No new installation is required just to repeat this already successful test.

The JSON template itself has not been imported or run in the owner's n8n.
The screenshot still shows `No input connected`; connection of Manual Trigger
to SSH and execution of the complete workflow remain unverified. Do not conflate
successful Execute step with a connected or published workflow.

This is not a durable job runner or an always-running agent. Later work must add
job status, retry policy, concurrent-job bounds, outbound-message approvals and
cost/usage bounds. CLI executions use the connected account's applicable limits.
The current chat history is not automatically transferred to this installation.

Keep the replacement VPS and the original inaccessible VPS distinct. The original
still incurs charges until the owner deletes it. Do not delete either server
without identifying its role and the owner's authorization.
