// Validation only: text locations and image positions never generate sectors.
export function sectorCodes(sectors, context = "Cannot adapt analysis") {
  const fail = message => { throw new Error(`${context}: ${message}`); };
  const canonical = new Set(["urethra"]);
  for (const [level, zones] of Object.entries({
    base: ["sv", "as", "pza", "tza", "pzpl", "tzp", "cz", "pzpm"],
    mid: ["as", "pza", "tza", "pzpl", "tzp", "pzpm"],
    apex: ["as", "pza", "tza", "pzpl", "tzp", "pzpm"],
  })) {
    for (const zone of zones) for (const side of ["rs", "ls"]) canonical.add(`${zone}_${level}_${side}`);
  }
  if (!Array.isArray(sectors) || sectors.length !== 41) fail("Supply the complete 41-sector specification.");
  const codes = new Set();
  for (const sector of sectors) {
    if (sector === null || typeof sector !== "object" || Array.isArray(sector) || !canonical.has(sector.code) ||
        codes.has(sector.code) || sector.column !== `sur_prostate_regions___${sector.code}`) {
      fail("Sector specification has an unknown code, duplicate code or incorrect column.");
    }
    codes.add(sector.code);
  }
  return codes;
}
