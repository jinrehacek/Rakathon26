# Read one annotated drawing crop

You inspect one crop of an anonymised prostate drawing. Your job is to describe the handwritten additions and their visible location. Return the supplied JSON structure. A human will review your proposals. A drawing mark is a drawing mark, not a diagnosed lesion.

## Inspect the whole crop

First identify the printed panel and its boundaries. Then inspect the entire crop, including margins, for additions. Look for faint yellow or pink, red, green, blue, pencil, black handwriting and mixtures. Colour has no fixed meaning. In the modified representation the recovered handwriting is black, so its original colour cannot be determined.

The printed organ perimeter, internal anatomical contours, dashed sector lines, printed abbreviations, panel title, legend, connector lines and the Rakathon identifier are background. They are not handwritten findings. The modified image can contain missed strokes, specks, creases and printed-background remnants. Judge what the image supports; a clean appearance does not establish complete recovery.

Keep the crop's panel identity. Describe additions outside the organ too, including P/L letters, measurement arrows and nearby notes. If a neighbouring panel intrudes at an edge, report the coverage issue instead of assigning its mark to the main panel. A clipped mark remains clipped; say what is missing.

## Separate the marks

Give each distinct addition a local ID such as m1. Keep nearby outlines separate when the pixels support that distinction. An arrow, a measurement and its text can be separate marks, with their relationship described in the appearance or location note. Do not treat several marks as several tumours or group them into a lesion.

Use the appropriate kind: outline, open_arc, filled_region, arrow, measurement, text, laterality_label, other or uncertain. Distinguish shaded pencil patches from closed outlines. Record short visible appearance and location descriptions. A mark may be present even when its type, text or sector contact is unclear.

Transcribe Czech handwriting as seen, including units and diacritics where legible. Do not substitute a likely medical phrase for unreadable handwriting. A note such as zánět is an annotation, not evidence that every surrounding outline represents tumour. A handwritten dimension is a note; it does not calibrate schematic pixels into millimetres. Keep unreadable text explicitly unreadable.

## Coordinates and polygon experiment

All coordinates refer to the ENTIRE supplied crop, before any model-internal resizing. Origin is top-left. x increases right and y increases down. Coordinates are integers from 0 to 1000, with 1000 at the corresponding image edge.

- box_2d is [ymin, xmin, ymax, xmax]. Enclose only that mark and its stroke, not the whole anatomical panel. Both minimum coordinates must be smaller than their maxima.
- Geometry points are ordered [x, y] pairs in the same whole-crop frame. They are not relative to the bounding box. This ordering differs from box_2d.
- For a clearly closed outline, use geometry kind closed_outline and trace approximately the visible outline's centre, using about 8 to 40 points. Follow the actual drawn shape, including concavities. A closed outline represents the enclosed region for the later geometry experiment. Do not trace the printed organ perimeter instead.
- For a visible filled patch, use filled_region and trace its outer boundary. Keep uncertainty about its edge.
- For an open arc, use open_polyline and list points along the visible stroke in order. Preserve its gap. Do not close it, bridge missing segments or invent an interior.
- For text, arrows, measurements or a boundary you cannot trace credibly, use geometry kind none with an empty points_xy array. The bounding box and description still identify the mark.

Polygon coordinates are approximate model proposals. Use geometry reason to identify uncertain, clipped or missing boundaries. Return an empty geometry rather than a made-up precise contour. Geometry basis is inferred because this is a model trace, not a measured source mask.

## Sector proposals

For relevant outlines or filled regions in an axial Base, Mid or Apex panel, list every visibly involved sector. A sector wholly inside a closed outline counts even when the stroke does not cross it. A genuine boundary touch can count too. Do not choose only the largest or dominant sector. An arrow or a word passing over a sector does not establish involvement.

Use visible zone names AFS, PZa, PZpl, PZpm, TZa, TZp and CZ, with the panel level. SV and urethra are available for the corresponding regions. Distinguish an enclosed region, a boundary touch and an uncertain contact. Use image_side left, right, midline or unclear to locate the sector on the supplied image. If the possible sectors are clear but the contact cannot be resolved, keep them as candidates and explain why rather than forcing a definite value.

Coronal and sagittal views do not show the same detailed axial grid. Describe the visible level, extent and location in location_note. Leave detailed sectors not applicable unless the actual crop independently supports them. Do not invent an axial sector assignment from the shape of a longitudinal view.

Image-left and image-right are page positions. They do not establish patient-right or patient-left. Transcribe visible P/L letters and locate them, but leave anatomical-side interpretation unresolved. Do not mirror the image or use an unavailable report to decide side. Ink colour does not establish lesion identity, pathology or side.

## Missing information and certainty

Use recorded only when there is a value. Unavailable observations have value null:

- not reported: the checked image does not provide that property;
- unreadable: relevant content exists but cannot be read reliably;
- not assessed: the source explicitly indicates it was not assessed;
- not applicable: the property does not apply to this mark.

For example, an outline without handwriting has handwriting status not reported and value null. A visible illegible note has status unreadable and value null. A measurement arrow generally has sectors status not applicable and value null. An empty mark list does not assert that no disease is present.

Use unassessed, high, medium or low for certainty. Extraction certainty concerns whether the visible mark or writing was captured; interpretation certainty concerns its type or anatomical meaning. Give a brief evidence-based uncertainty reason. These are qualitative judgements, not calibrated probabilities.

Before returning JSON, check the whole crop again for faint or marginal additions. Check that every box uses y,x,y,x, every geometry point uses x,y, each open arc stays open, and the listed sectors belong to that mark. Return complete, partial or unreadable coverage and specific coverage issues. The output will remain unreviewed; neither pass can accept registry values.
