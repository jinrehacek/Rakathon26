// Atlas lettering is not the REDCap code: notably, "AFS" exports as "as".
const ZONES = {
  sv: { atlas: "Seminal vesicles", name: "seminal vesicles" },
  as: { atlas: "AFS", name: "anterior fibromuscular stroma" },
  pza: { atlas: "PZa", name: "anterior peripheral zone" },
  pzpl: { atlas: "PZpl", name: "posterolateral peripheral zone" },
  pzpm: { atlas: "PZpm", name: "posteromedial peripheral zone" },
  tza: { atlas: "TZa", name: "anterior transition zone" },
  tzp: { atlas: "TZp", name: "posterior transition zone" },
  cz: { atlas: "CZ", name: "central zone" },
};
const LEVELS = { base: "Base", mid: "Mid", apex: "Apex" };

function identity(sector) {
  const match = /^(sv|as|pza|pzpl|pzpm|tza|tzp|cz)_(base|mid|apex)_(rs|ls)$/.exec(sector.code);
  if (!match || (["sv", "cz"].includes(match[1]) && match[2] !== "base")) {
    throw new Error(`No verified atlas label for sector: ${sector.code}`);
  }
  return { zone: ZONES[match[1]], level: LEVELS[match[2]], side: match[3] === "rs" ? "Right" : "Left" };
}

export function atlasLabel(sector) {
  return sector.code === "urethra" ? "Urethra" : identity(sector).zone.atlas;
}

export function sectorName(sector) {
  if (sector.code === "urethra") {
    return "Urethra (atlas); External urethral sphincter (mapped source title)";
  }
  const { zone, level, side } = identity(sector);
  return `${side} ${zone.name} - ${level} (${zone.atlas})`;
}

function inside([x, y], points) {
  let result = false;
  for (let index = 0, previous = points.length - 1; index < points.length; previous = index++) {
    const [ax, ay] = points[index], [bx, by] = points[previous];
    if ((ay > y) !== (by > y) && x < (bx - ax) * (y - ay) / (by - ay) + ax) result = !result;
  }
  return result;
}

// Thin or concave sectors keep their full accessible label instead of overlapping text.
export function sectorLabel(sector) {
  let area = 0, x = 0, y = 0;
  sector.points.forEach(([ax, ay], index) => {
    const [bx, by] = sector.points[(index + 1) % sector.points.length];
    const cross = ax * by - bx * ay;
    area += cross;
    x += (ax + bx) * cross;
    y += (ay + by) * cross;
  });
  if (!area) return null;
  x /= 3 * area;
  y /= 3 * area;
  const text = atlasLabel(sector);
  const halfWidth = text.length * 2.2;
  if (![[-halfWidth, -4], [halfWidth, -4], [-halfWidth, 4], [halfWidth, 4]]
    .every(([dx, dy]) => inside([x + dx, y + dy], sector.points))) return null;
  return { text, x, y };
}
