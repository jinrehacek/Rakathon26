import { atlasLabel, sectorName, sectorLabel } from "../map-labels.js";

export function runMapLabelTests(sectors) {
  let passed = 0;
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const test = (name, run) => {
    try { run(); passed += 1; }
    catch (error) { throw new Error(`${name}: ${error.message}`); }
  };
  // Transcribed from the public atlas, independently of export abbreviations.
  const expected = {
    sv: ["Seminal vesicles", "seminal vesicles"],
    as: ["AFS", "anterior fibromuscular stroma"],
    pza: ["PZa", "anterior peripheral zone"],
    pzpl: ["PZpl", "posterolateral peripheral zone"],
    pzpm: ["PZpm", "posteromedial peripheral zone"],
    tza: ["TZa", "anterior transition zone"],
    tzp: ["TZp", "posterior transition zone"],
    cz: ["CZ", "central zone"],
  };
  test("All 40 bilateral sectors use atlas lettering, side and level", () => {
    assert(sectors.length === 41, "Use the complete canonical map");
    const codes = new Set();
    for (const [zone, [printed, name]] of Object.entries(expected)) {
      for (const level of ["sv", "cz"].includes(zone) ? ["base"] : ["base", "mid", "apex"]) {
        for (const [side, word] of [["rs", "Right"], ["ls", "Left"]]) {
          const code = `${zone}_${level}_${side}`;
          const sector = sectors.find(item => item.code === code);
          assert(sector, `Missing verified sector: ${code}`);
          assert(atlasLabel(sector) === printed, `Wrong atlas lettering for ${code}`);
          assert(sectorName(sector) === `${word} ${name} - ${level[0].toUpperCase() + level.slice(1)} (${printed})`,
            `Wrong expanded name, side or level for ${code}`);
          codes.add(code);
        }
      }
    }
    assert(codes.size === 40, "Every bilateral code must be checked exactly once");
  });
  test("AFS is a display label, never a renamed export code", () => {
    const before = JSON.stringify(sectors);
    for (const sector of sectors) {
      const label = sectorLabel(sector);
      assert(!label || label.text === atlasLabel(sector), "Rendered labels must use the same verified atlas lettering");
      assert(sector.column === `sur_prostate_regions___${sector.code}`, "Preserve canonical export columns");
    }
    assert(JSON.stringify(sectors) === before, "Label rendering must not mutate names, geometry or codes");
    assert(!sectors.some(sector => sector.code.startsWith("afs_")), "REDCap uses as_, not afs_");
    assert(sectorName(sectors.find(sector => sector.code === "tzp_base_rs")) ===
      "Right posterior transition zone - Base (TZp)", "Do not display upstream transition spelling errors");
    assert(sectorName(sectors.find(sector => sector.code === "cz_base_rs")) ===
      "Right central zone - Base (CZ)", "Do not display upstream central spelling errors");
  });
  test("Urethra naming disagreement remains explicit", () => {
    const sector = sectors.find(item => item.code === "urethra");
    assert(sector?.key === 41 && atlasLabel(sector) === "Urethra", "The atlas's bottom circle is labelled Urethra");
    assert(sectorName(sector) === "Urethra (atlas); External urethral sphincter (mapped source title)",
      "Do not silently equate or overwrite the two source names");
    assert(sector.column === "sur_prostate_regions___urethra", "The checkbox mapping must not change");
  });
  test("Unknown or anatomically unsupported codes fail rather than inventing names", () => {
    for (const code of ["afs_base_rs", "cz_mid_rs", "sv_apex_ls", "pza_base", "pza_base_left", "new_base_rs"]) {
      let rejected = false;
      try { atlasLabel({ code }); } catch (error) { rejected = error instanceof Error; }
      assert(rejected, `Do not guess a label for ${code}`);
    }
  });
  return { passed };
}
