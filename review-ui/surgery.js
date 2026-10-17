// Raw codes from Other/redcap/surgery_fields.csv. No web-form defaults.
const choices = labels => labels.map((label, i) => [String(i + 1), label]);
export const SURGERY_FIELDS = [
  { name: "surgery_date", label: "Surgery date", type: "date", required: true },
  { name: "surgery_type", label: "Surgery type", choices: choices(["Open surgery", "RALP"]), required: true },
  { name: "total_number_lesion_surg", label: "Total operated lesions", choices: choices(["1", "2", "3", "4", "5", "6", "Other"]), required: true },
  { name: "total_number_lesion_surg_oth", label: "Other lesion count", type: "number", min: 0, max: 100, when: ["total_number_lesion_surg", "7"] },
  { name: "lymphadenectomy", label: "Lymphadenectomy", choices: choices(["Performed", "Not performed"]), required: true },
  { name: "node_no_surgery", label: "Resected lymph nodes", type: "number", min: 0, max: 20, when: ["lymphadenectomy", "1"] },
  { name: "node_positive_no_surgery", label: "Positive lymph nodes", type: "number", min: 0, max: 20, when: ["lymphadenectomy", "1"] },
  { name: "pt_surg", label: "pT", choices: choices(["pT0", "pT1a", "pT1b", "pT1c", "pT2a", "pT2b", "pT2c", "pT3a", "pT3b", "pT4", "pTX"]) },
  { name: "pn_surg", label: "pN", choices: choices(["pN0", "pN1", "pNX"]) },
  { name: "pm_surg", label: "pM", choices: choices(["pM0", "pM1a", "pM1b", "pM1c", "pMX"]) },
  { name: "classify_r_surg", label: "Resection margin R", choices: choices(["R0", "R1", "R2", "RX"]), required: true },
  { name: "classify_l_surg", label: "Lymphatic invasion L", choices: choices(["L0", "L1", "LX"]), required: true },
  { name: "vascular_inv", label: "Vascular invasion V", choices: choices(["V0", "V1", "V2", "VX"]), required: true },
  { name: "isup", label: "Specimen grade group", choices: choices(["1", "2", "3", "4", "5"]) },
  { name: "histol_post_surg", label: "Definitive histology", choices: choices(["Carcinoma / epithelial", "Neuroendocrine", "Sarcoma", "Haematolymphoid", "Metastasis", "Other malignant"]), required: true },
  { name: "surgery_text", label: "Histological finding", type: "textarea" },
];

export function validateSurgery(surgery, { today = new Date().toISOString().slice(0, 10) } = {}) {
  if (!surgery || typeof surgery.values !== "object" || surgery.values === null) return ["Review the surgery record."];
  const errors = [], values = surgery.values;
  if (surgery.reviewed !== true) errors.push("Confirm review of the surgery record.");
  for (const name of Object.keys(values)) if (!SURGERY_FIELDS.some(f => f.name === name)) errors.push(`Unsupported surgery field ${name}.`);
  for (const field of SURGERY_FIELDS) {
    const value = values[field.name] ?? "";
    const applies = !field.when || values[field.when[0]] === field.when[1];
    if (!applies) {
      if (value !== "") errors.push(`${field.label}: clear the value because its prerequisite is not selected.`);
      continue;
    }
    if (typeof value !== "string") { errors.push(`${field.label}: a raw string value is required.`); continue; }
    if (!value) {
      if (field.required || field.when) errors.push(`${field.label} is required.`);
      continue;
    }
    if (field.choices && !field.choices.some(([code]) => code === value)) errors.push(`${field.label}: unknown choice code.`);
    if (field.type === "number" && (!/^\d+$/.test(value) || +value < field.min || +value > field.max)) errors.push(`${field.label}: enter an integer from ${field.min} to ${field.max}.`);
    if (field.type === "date" && (!/^\d{4}-\d{2}-\d{2}$/.test(value) || Number.isNaN(Date.parse(value)) || new Date(value).toISOString().slice(0, 10) !== value || value < "1900-01-01" || value > today)) errors.push(`${field.label}: enter a valid date from 1900 to today.`);
    if (/^[\s]*[=+\-@]/u.test(value) || /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/u.test(value)) errors.push(`${field.label}: unsafe spreadsheet content.`);
  }
  if (values.lymphadenectomy === "1" && +values.node_positive_no_surgery > +values.node_no_surgery) errors.push("Positive nodes exceed resected nodes.");
  return errors;
}
