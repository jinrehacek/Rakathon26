# AGENTS.md

Read `TASK.md` before starting any task. It defines the hackathon goal and deliverable.

This is a 24-hour hackathon. A working end-to-end slice beats a polished partial one.

## Files and patient data

- `Other/` is not git-ignored. The current anonymised hackathon scans are tracked in Git.
- Keep research files in `Other/research/`. Keep the image pipeline proposal in `Other/IMAGE_PIPELINE.md`.
- Keep identifiable production records, patient-linked extracted text and model output, and tokens out of Git. Add a new local data or output folder to `.gitignore` before the first write.
- Send a scan or extracted text to an external model or service only when the user has said so in the current session. Local processing is fine.

## Schema

Before designing or changing extraction, matching or export, read `data_schema/STRUCTURE.md`. It is authoritative for extraction concepts, statuses, bases, evidence and relationships. If another document conflicts with it, follow `STRUCTURE.md` and correct the other document.

## Extraction rules

- Extract each document independently. Match report subjects and drawing subjects in a later step, preserving the original observations.
- Recorded values must be traceable to source evidence, directly or through supporting observations. Use the schema's bases: `explicit`, `normalized`, `inferred` and `calculated`.
- An unmentioned property uses status `not reported` with no value. An explicit negative is a recorded presence value of `absent`. Keep unreadable, not assessed and not applicable findings distinct.
- Show inferred and calculated suggestions apart from explicit findings, with their evidence and reasoning. A doctor confirms them before export.
- When text and drawing disagree, keep both values and raise an issue for the doctor. Neither source overwrites the other.
- A drawing mark alone never creates a lesion. Unmatched marks become review issues.
- The report text decides side (vpravo/vlevo, pravý/levý, P/L lalok). Mark position and handwritten P/L letters are supporting evidence, and any disagreement raises an issue. In axial views patient right is usually on the viewer's left. The coronal view is sometimes drawn mirrored.
- Ink colour has no fixed meaning. Every non-template stroke is a candidate mark, whatever its colour.

## Production design

Local redaction, a hospital-held patient mapping, external extraction and local reassociation are a proposed flow, not a selected architecture. Retaining a patient mapping makes the hospital workflow pseudonymised rather than anonymous. Establish the hospital's lawful basis and supplier arrangements before production use; a research purpose alone does not authorise an external service.

## Working agreement

- Inspect the files, data and command output before claiming anything about them. Say what you verified and label guesses.
- Carry authorized work through implementation and verification. Ask again only when new information changes the scope or needs a separate decision.
- Measure model accuracy on our scans, not on vendor benchmarks. A run on three sheets is a probe, so call it one.
- Before calling an image-pipeline change good, prepare 5 to 8 grading sheets and ask the user to grade them. Format: `Other/IMAGE-PIPELINE-RECONCILIATION.md`, section "Testing".
- Write plainly. Cut praise, filler, repeated explanations and process narration.
- Change only what the task needs. Commit only when asked.
