# Security reporting

For a suspected security defect, contact **ollett123123@outlook.com** privately
with the subject **Rat-Trap security report**. This is the same support route
documented in [SUPPORT.md](SUPPORT.md), handled by TWO HANDS NETWORK LTD.

Include the affected version, a concise description, the impact you observed
and a minimal reproduction using fictional data. Do not post a working
sensitive-data exploit or confidential diagnostics in a public issue.

Never send real passwords, recovery keys, confidential archives, private
signing keys or customer data. Ordinary email is not a secure file-transfer
service. Start with a description and arrange any necessary follow-up before
sending sensitive material.

## Scope and current status

The current public Windows preview is identified by
[the release notes](docs/releases/5.7.0-preview.6.md). Older versions remain
historical records, not a promise of active security maintenance. No response
deadline, bug bounty, independent audit or security certification is promised.

The app and installer are unsigned. Do not disable operating-system security
protections to run them. Keep original files and independent backups while
evaluating the preview.

Consult the [technical security boundaries](docs/TECHNICAL.md#exact-feature-boundaries)
and the format specifications for the precise protections. Live backup
repositories are unencrypted. Matching recovery keys independently grant
access to protected data. Temporary plaintext cleanup is best-effort.
Documented public fixture passwords and keys are deliberately not secrets.
