export function pendingRegionCodes(lesion) {
  return Object.keys(lesion.pendingRegionEdits || {});
}

export function stageRegion(lesion, code, assigned) {
  if (lesion.excluded) throw new Error("Restore this lesion before editing regions.");
  const previous = lesion.regions.includes(code);
  if (previous === assigned) return;
  const edits = lesion.pendingRegionEdits ??= {};
  const from = edits[code]?.from ?? previous;
  if (from === assigned) delete edits[code];
  else edits[code] = { from, to: assigned };
  lesion.regions = assigned ? [...lesion.regions, code] : lesion.regions.filter(item => item !== code);
}

export function documentRegions(lesion, evidence) {
  const codes = pendingRegionCodes(lesion);
  if (!codes.length) throw new Error("No region edits need documentation.");
  lesion.regionEvidence ??= {};
  for (const code of codes) lesion.regionEvidence[code] = structuredClone(evidence);
  lesion.pendingRegionEdits = {};
}
