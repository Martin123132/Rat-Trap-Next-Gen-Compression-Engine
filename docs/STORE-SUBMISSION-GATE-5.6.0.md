# Rat-Trap 5.6.0 Microsoft Store submission gate

Status: submission pack prepared; company verification and public URLs pending

This gate prepares every truthful submission field that does not depend on
Partner Center assigning Rat-Trap's permanent package identity. It does not
change the frozen 5.6.0 executable or development MSIX.

## Prepared now

- product owner and intended publisher: TWO HANDS NETWORK LTD;
- English (United Kingdom) listing copy;
- commercial feature list with no competitor claims or benchmark numbers;
- privacy policy and support guidance;
- `runFullTrust` justification and certification walkthrough;
- proposed Utilities + tools / Backup + manage classification;
- proposed free, private-beta first submission;
- explicit product declarations;
- five clean screenshot specifications and captions; and
- synthetic, non-confidential screenshot data.

Authoritative draft files:

- `store/submission/submission-profile.json`;
- `store/submission/en-gb/listing.json`;
- `store/submission/en-gb/screenshot-captions.json`;
- `store/submission/certification-notes.txt`;
- `store/submission/certification-test-walkthrough.md`;
- `store/submission/en-gb/additional-license-terms.txt`;
- `PRIVACY.md`; and
- `SUPPORT.md`.

## External items still pending

Do not submit until all of these are resolved:

1. Microsoft verifies the company developer account.
2. Partner Center confirms the reserved customer-facing product name.
3. The exact three Product identity values are copied verbatim into
   `packaging/publisher-profile.json`.
4. `PRIVACY.md` is published at a stable public HTTPS URL approved by the
   company.
5. The support email is confirmed or replaced by a company-domain support
   route; a support HTTPS page is strongly recommended.
6. Five clean screenshots are captured and manually checked.
7. The IARC questionnaire is answered in Partner Center.
8. Initial visibility is confirmed before it is saved.

No company website, privacy URL, support URL, age rating, market list, package
identity, or Store identifier may be invented to make the draft look complete.

## Recommended first-submission settings

- product: non-game MSIX app;
- architecture: x64;
- device family: Windows Desktop;
- language: English (United Kingdom);
- category: Utilities + tools;
- subcategory: Backup + manage;
- base price: Free;
- initial audience: Private beta;
- accounts/login: No;
- purchases or advertising: No;
- drivers or NT services: No;
- generative AI: No;
- personal-information access: Yes, because the desktop utility can process
  user-selected files that contain personal information;
- privacy policy: Required;
- accessibility declaration: leave unchecked until specifically tested; and
- restricted capability: `runFullTrust`, using the prepared explanation.

Private-beta visibility is a proposal, not an automatic Partner Center action.
The company representative must read and confirm the visibility choice before
saving the first submission.

## Screenshot gate

Microsoft requires at least one screenshot and recommends four or more desktop
screenshots. Rat-Trap's prepared set is:

1. Create archive;
2. Secure files;
3. Repository backup history;
4. Queryable Vault search; and
5. structured Data Tables.

Each file must be a clean PNG of at least 1366 x 768 pixels and must use only
the synthetic content under `store/demo-data`. Existing development screenshots
are rejected because they show personal desktop information.

The Windows capture helper on the current Windows 10 machine returned
`SetIsBorderRequired failed: No such interface supported (0x80004002)` twice.
No screenshot was silently substituted. Capture remains pending through a
clean window-only or full-screen workflow.

## Certification gate

The current package already passes MakeAppx pack/unpack, manifest, inventory,
payload, packaged self-test, real-folder test, and automated test gates.

The local Windows App Certification Kit is installed, but the current
development MSIX uses Microsoft's unsigned-development identity and cannot
provide the final Windows 10 install/activation test. Run WACK against a
test-signed package after Partner Center supplies the exact Publisher value,
or test the unsigned-development route on a suitable Windows 11 machine.
Partner Center upload validation and certification remain authoritative.

Before public release, also test:

- clean install and uninstall;
- upgrade from an earlier Store package;
- repair;
- `.gmw` and `.rtsf` Open with activation;
- 100%, 150%, and 200% display scaling;
- operations with the network disconnected;
- closing the application during a long operation;
- preservation of user-created archives after uninstall; and
- Windows 10 build 19045 and a current supported Windows 11 release.

## Product work identified during the audit

The next code-bearing stage should be a Windows reliability gate:

1. prevent accidental window closure while a compression, backup, encryption,
   verification, export, or restore operation is active;
2. catch startup, Tk callback, worker, and completion-callback failures;
3. add a privacy-conscious local diagnostic reference without logging
   passwords, recovery-key contents, or file contents;
4. strengthen safe file-activation manifest tests; and
5. expose Privacy and Support from an About view.

That stage changes the executable and therefore needs a new build, test run,
release manifest, and artifact audit. It should not be disguised as a
documentation-only change to the frozen 5.6.0 candidate.
