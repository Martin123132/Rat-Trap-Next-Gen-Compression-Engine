# Rat-Trap Store screenshots

Status: five clean captures required before submission

Do not reuse screenshots of the development desktop. Existing captures expose
personal paths, filenames, unrelated applications, and desktop content.

## Capture requirements

- PNG format;
- at least 1366 x 768 pixels;
- no more than 50 MB per image;
- one Rat-Trap window only, with no desktop or unrelated application visible;
- 100% Windows display scaling for the primary set;
- no real names, personal paths, credentials, recovery keys, or confidential
  file contents;
- use only the synthetic files under `store/demo-data`;
- keep critical controls and text in the top three-quarters of the image; and
- do not add competitor logos, benchmark numbers, promotional badges, or text
  overlays to the screenshots.

## Planned sequence

1. `01-create-archive.png` - the Create archive view with the profile selector
   and optional encryption control visible.
2. `02-secure-files.png` - empty Protect one file view with synthetic paths.
3. `03-backup-history.png` - two synthetic repository snapshots and a neutral
   file-history result.
4. `04-queryable-vault.png` - a search for `maintenance` in the synthetic
   Vault.
5. `05-data-tables.png` - the synthetic `inventory.csv` table with no SQL text
   containing personal data.

The matching captions are in
`store/submission/en-gb/screenshot-captions.json`.

The current Windows capture helper cannot capture the Tk window reliably on
this Windows 10 machine (`SetIsBorderRequired` is unsupported). Capture these
through a clean full-screen/window-only workflow before submission and inspect
every image manually.
