# Product and evidence lanes

Rat-Trap uses two coordinated publishing lanes. They serve different readers,
but neither may contradict the other.

## Lane A: commercial product page

Purpose: explain quickly why someone should choose Rat-Trap.

Use:

- the clearest product promise;
- Rat-Trap strengths that matter to the intended user;
- selected, scoped benchmark wins;
- screenshots and simple workflows;
- direct calls to download, try, or license.

The lead proposition for the 5.3 product is:

> Compressed backup history, authenticated encrypted portable archives and
> queryable local vaults in one Windows application.

Supporting propositions are:

- recurring snapshots reuse matching content across time;
- any verified snapshot can become one portable `.gmw`;
- a portable archive can use tamper-detecting encryption with a separate
  recovery key;
- Queryable Vaults search supported files and structured data without first
  unpacking the collection.

Commercial copy does not need to advertise every competitor win. It does need
to remain literally supportable by the evidence lane. A number beside a claim
must name or link its corpus, profile, date, and methodology.

## Lane B: technical and buyer evidence

Purpose: let engineers, commercial buyers, reviewers, and partners audit the
technology.

Publish:

- complete test matrices, including losses and failures;
- raw result files and checksums;
- commands, source revision, environment, and dependencies;
- corpus provenance and manifests;
- timing boundaries and archive-semantics differences;
- round-trip and corruption tests;
- format registry, compatibility policy, security boundary, and known limits.

The evidence lane is not written as an attack on the product. Its job is to
make serious claims inspectable and reduce technical due-diligence risk.

## Shared rules

1. Never fabricate or silently round a result into a stronger claim.
2. Never compare a folder archive with a raw codec without labelling the
   semantic difference.
3. Never present a historical unvalidated result as a current rerun.
4. Never hide a failed or losing row from the backend matrix.
5. Never broaden the shipped portable-archive encryption into claims of an
   encrypted live repository, secure deletion, signing, cloud backup, or
   independent security certification.
6. Never use an arbitrary personal folder as a representative benchmark.
7. Keep project history and credits intact without treating a benchmark as
   proof of a physics theory.

## Publishing flow

```text
raw run
  -> machine-readable record + hashes
  -> technical validation
  -> complete evidence page
  -> scoped commercial claim
```

If a commercial sentence cannot be traced backward through that chain, it is
positioning without quantitative evidence and must not contain a benchmark
number.
