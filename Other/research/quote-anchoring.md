# Quote anchoring: how tools map a model's quote back to source text

Question: how do existing tools map a model-written quote to exact positions in a source text?

Scope: Hermes agent (main example), OpenAI Codex, OpenHands, Roo Code, Cline, Google LangExtract, Anthropic Citations. Aider is left out at your request. Claude Code's Edit tool: I read only the Edit tool description in this session (`old_string` must be unique, or the edit fails; `replace_all` changes that). I did not read Claude Code source.

Every claim below comes from a file I opened. Repo links name the commit I cloned. Paths are relative to each repo.

## Hermes agent (NousResearch)

Repo: https://github.com/NousResearch/hermes-agent at 0ab43d4f. Files: `tools/fuzzy_match.py`, `tools/file_operations.py`, `tools/file_tools.py`.

**Model output.** `path`, `old_string`, `new_string`, `replace_all`. No offsets. The schema tells the model to include surrounding lines to make the match unique (`tools/file_tools.py` L1203-1235).

**Cascade.** Nine strategies run in order. The first one that finds any match wins, and later strategies do not run (`tools/fuzzy_match.py` L289-298, L394-398):

1. exact, all non-overlapping occurrences (L176-179)
2. strip each line (L182-184)
3. collapse runs of spaces and tabs, map offsets back (L187-196)
4. ignore leading indentation (L199-201)
5. turn literal `\n`, `\t`, `\r` in the pattern into control characters (L204-209)
6. strip first and last line only (L212-214)
7. fold smart quotes, dashes and odd spaces to ASCII on both sides (L24-34, L217-227)
8. block anchor: first and last line must match after strip, middle scored by `difflib` ratio, threshold 0.50 for a single candidate and 0.70 for several (L230-258)
9. context aware: every non-blank line at ratio 0.80 or more (L261-285)

Limit, from reading the code (not run): strategy 3 collapses only `[ \t]+` (L190), never `\n`. Strategies 2, 4, 6, 8 and 9 compare windows of the same line count as the pattern. A one-line quote `karcinom prostaty` against OCR `karcinom\nprostaty` matches none of the nine. Strategy 9 scores 0.64 on the first line (2*8/25), below its 0.80 floor. Hermes cannot cross an OCR line break.

Strategies 8 and 9 are tagged as similarity matches (L302). Under `replace_all`, a similarity strategy that finds more than one match is refused (L406-412).

**Ambiguity.** If the winning strategy returns two or more spans and `replace_all` is false, the edit fails. The error lists up to five matches with line numbers and snippets (L399-405, formatter L340-356). The chain does not fall through to a later strategy, so a repeated phrase is never resolved by fuzzy matching. A test asserts both line numbers appear in the error (`tests/tools/test_patch_multimatch_locations.py` L26-37).

**Failure to the model.** The tool returns an error string. There is no retry inside the tool. On a plain "could not find", it appends the three closest snippets, found by `difflib` ratio above 0.3 on the first line (`tools/fuzzy_match.py` L669-719). For whitespace-only misses it shows tabs as arrows and spaces as dots (L700-708).

**Already applied.** If the new text is already present and the old text is gone, the tool reports success with no write (`tools/fuzzy_match.py` L328-333, `tools/file_operations.py` L1561-1580).

**Guards on non-exact matches.** Escape-drift checks run only when the match is not exact (L416-419). Indentation is re-anchored to the file (L575-604). Unicode typography in the file is kept (L607-634). A similarity match returns a note asking the model to check the diff (L305-323, `tools/file_operations.py` L1642).

## OpenAI Codex (`apply_patch`)

Repo: https://github.com/openai/codex at ce0323f2. Files: `codex-rs/apply-patch/src/seek_sequence.rs`, `file_update.rs`.

**Model output.** A line-based patch with context lines and an optional `@@` anchor. No offsets.

**Cascade.** Exact, then trailing whitespace stripped, then fully trimmed, then Unicode punctuation folded (`seek_sequence.rs` L35-108).

**Ambiguity.** None. Each chunk takes the first hit at or after a cursor that moves forward through the file (`seek_sequence.rs` L36-40, `file_update.rs` L102-104). The patch order decides which occurrence is used.

**Failure.** "Failed to find expected lines in <path>:" followed by the old lines (`file_update.rs` L155-159). For `@@` anchors: "Failed to find context" (L80-82).

## OpenHands `str_replace_editor`

Repo: https://github.com/All-Hands-AI/openhands-aci at a8d8d23. File: `openhands_aci/editor/editor.py` L170-239.

**Model output.** `old_str`, `new_str`. No offsets.

**Cascade.** Exact regex. If that finds nothing, strip both strings and retry exact. No fuzzy step (L196-219).

**Ambiguity.** Refused. More than one occurrence raises "Multiple occurrences ... in lines [...]" (L224-228).

**Failure.** "did not appear verbatim" (L221-223).

## Roo Code

Repo: https://github.com/RooCodeInc/Roo-Code at b867ec91. File: `src/core/diff/strategies/multi-search-replace.ts`.

**Cascade.** Scores every window by Levenshtein similarity, `1 - distance / max length`, after `normalizeString` (its rules not checked) (L11-31, L37-72). The default threshold is 1.0, which means exact (L83-87). A configured start line narrows the search. A second pass strips line-number prefixes (L377-430).

**Ambiguity.** None. The highest score wins, and ties go to whichever window the middle-out scan visits first.

**Failure.** "No sufficiently similar match found (N% similar, needs M%)" with the search text and a tip to re-read the file (L456).

## Cline (SDK editor)

Repo: https://github.com/cline/cline at a42df8c8. File: `sdk/packages/core/src/extensions/tools/executors/editor.ts` L160-190. The VS Code copy in `apps/vscode/src/sdk/sdk-diff-edit-coordinator.ts` L412-430 does the same.

**Cascade.** Exact only, after line-ending normalisation.

**Ambiguity.** Refused. Zero hits: "text not found". Two or more: "multiple occurrences of text found".

## Google LangExtract

Repo: https://github.com/google/langextract at 3a68580. Files: `langextract/resolver.py`, `langextract/core/data.py`.

**Model output.** Extraction text. Offsets are computed by the library.

**Pipeline.** Source and extraction are tokenised, lowercased (`resolver.py` L1251-1264).

1. Exact token-sequence match. All occurrences are found (L1115-1133). Each extraction takes at most one, in output order, maximising matched tokens. Ties prefer the chain that ends earliest, so repeated mentions map to successive occurrences (L1152-1171).
2. Lesser match. `difflib` matching blocks, accepted when the extraction is longer than the match and `accept_match_lesser` is on (L1039-1058).
3. Fuzzy. Window scan over tokens with a token-count prefilter. Accepted when the `SequenceMatcher` ratio is at least `fuzzy_alignment_threshold`, default 0.75 (L58, L630-730). Only for extractions still unmatched.

**Statuses.** `MATCH_EXACT`, `MATCH_GREATER`, `MATCH_LESSER`, `MATCH_FUZZY` (`core/data.py` L43-48). `char_interval` is half-open: start inclusive, end exclusive (L50-60).

**Ambiguity.** Resolved by order, not by an error. This assumes extractions come in reading order.

**Failure.** An unmatched extraction has no interval and a `None` status. The caller decides what to do.

**Tokeniser.** `langextract/core/tokenizer.py` L148-157: letters are `[^\W\d_]+` (Unicode-aware, so Czech háček letters stay in one token), digits `\d+`, each symbol a token. Whitespace is never a token, so line breaks are ignored. Lowercasing: `resolver.py` L1285 onward. Diacritic or OCR-typo differences still fail exact token matching and fall to the fuzzy step.

## Anthropic Citations API

Source: https://platform.claude.com/docs/en/build-with-claude/citations (fetched).

- The model does not output offsets. The API returns citation objects.
- Plain text is split into sentences by the API. Citations carry `start_char_index` and `end_char_index`, 0-indexed with an exclusive end.
- Custom content documents skip the split. Citations carry block indices instead.
- The docs say `cited_text` is extracted from the document, so "citations are guaranteed to contain valid pointers to the provided documents".

Relevance to us: the split is on the API side. We can only cite chunks we send, so our own chunking has to be right.

## Designs that avoid the problem

- Numbered chunks. Anthropic Citations uses chunk indices, so the model names a span instead of copying it. This is a sourced design.
- Surrounding context. Hermes tells the model to include surrounding lines so the match is unique (`tools/file_tools.py` L1218). This is a sourced design.
- Occurrence index. Not seen in any tool above. It is our idea.

## Recommended design for our case

- Keep the raw OCR text immutable. Compute all offsets in code.
- Ask the model for a line range and an exact quote. Search inside that range first, then the whole text.
- Tier 1, exact on raw text. One hit: accept, `match_quality` `exact`.
- Tier 2, whitespace and line-break normalised. Build the folded string with an index array (one raw code-point index per folded character). A folded match `[ns, ne)` maps to `[idx[ns], idx[ne-1]+1)`. Hermes's `_map_normalized_positions` is best-effort and handles only spaces and tabs (L123-125), so do not copy it. Also join a hyphen at a line end. `match_quality` `normalized`.
- Tier 3, diacritics and smart punctuation folded for comparison only, same index array. `match_quality` `normalized`.
- Tier 4, token-level fuzzy match, `difflib` ratio at least 0.85 to start. Tune on our scans; LangExtract uses 0.75. Count every window above threshold, as Hermes's `_window_spans` does (L54-59); more than one is ambiguous. Taking only the best window is weaker. `match_quality` `fuzzy`, score stored.
- Numbered prompt lines: if the model copies a line-number prefix into its quote, strip it before matching. Roo does this in a second pass (`multi-search-replace.ts` L409-430).
- Ambiguity: if a tier returns two or more hits, stop there. Do not take the first. Break ties with the line range or the surrounding context. If still tied, store `ambiguous` with all candidate spans and raise a doctor issue. This covers "GS 6".
- Retry: at most one. Send back the error with numbered candidate lines and the instruction to copy from them. If still unresolved, store `not_found` and raise an issue.
- Store per evidence item: `match_quality`, tier, score, candidate count, and `text[start:end]` so the UI and doctor see what was highlighted. Use `match_quality`, not `status`: STRUCTURE.md already uses "Status" (Recorded, Not reported, Unreadable, Not assessed, Not applicable) and "Basis" (Explicit, Normalized, Inferred, Calculated). Its Evidence section already has "Original quotation" and "Text offsets" (`data_schema/STRUCTURE.md` L120-133). Store the offsets in the Text offsets field of that anchor.
- Measure on our scans: tier distribution and ambiguity rate. Three sheets is a probe, not a measurement.
