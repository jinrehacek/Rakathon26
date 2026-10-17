# Read the handwritten marks on one drawing view

You get one view of an anonymised prostate diagram that a pathologist annotated by hand. List every handwritten mark in the supplied JSON structure. A mark is a drawing mark, not a diagnosed lesion. A human reviews your output.

## The two images

- Image 1 is the original colour crop of the scan.
- Image 2 is the cleaned crop: the printed coloured template with the recovered handwriting drawn in black. For coronal and sagittal views, image 2 also has thin magenta outlines with labels such as "base, image left" or "mid, anterior". Those outlines and labels are the sector map. They are not ink.

Both images share one pixel frame: the same point has the same coordinates in both. Trust image 2 for geometry. Use image 1 to catch ink the cleaning lost, such as faint pencil or yellow. If a mark is only visible in image 1, still report it, with coordinates in the same frame.

## What counts as a mark

Inspect the whole crop, including the margins outside the organ. The printed organ outline, internal contours, dashed lines, coloured zones, printed labels, titles and legends are background. Colour has no fixed meaning: every handwritten stroke of any colour is a candidate mark. Do not invent ink. Part of a neighbouring panel can show at a crop edge; skip outlines, shading and text drawn on that neighbouring panel, but still report side letters near the edge. If you are not sure a stroke is handwritten, report it as kind other.

Give each mark a local ID: m1, m2, and so on. Kinds:

- closed outline: a drawn loop around an area
- open arc: an outline that does not close
- small circle: a small closed loop or dot-like circle
- shading: a filled or hatched area
- side letter: a single letter P, L or R; put the letter in text
- text: any other handwriting, numbers or words
- arrow
- other

Keep marks separate. Do not group them into lesions and do not merge nearby outlines into one.

## Coordinates

All coordinates are integers from 0 to 1000 over the whole crop, origin top-left, x to the right, y down.

- polygon is a list of [x, y] points on image 2. For closed outline, small circle and shading, trace the centre of the visible stroke (shading: its outer edge) as a ring of about 8 to 40 points, following concavities. Do not trace the printed organ outline. For open arc and arrow, list the points along the stroke in order and keep the gap open. Use an empty list for text and side letters, or for a mark too small to trace.
- box_2d is [ymin, xmin, ymax, xmax] around the mark's own stroke. Note the order: polygon points are x first, box_2d is y first.

## Text

Transcribe Czech handwriting as seen, with diacritics and units, for example "cca 25mm" or "zánět". If the text is unreadable, give your best partial reading with "?" for the unreadable parts. Use null for marks without writing.

## Sectors

For each bubble (closed outline, open arc, small circle, shading) list the sectors it touches or encloses. List every one, not only the largest. A sector wholly inside a closed outline counts. Leave sectors empty for letters, text and arrows.

- SV, base, mid, apex and urethra views: use the printed zone labels on image 2 (AFS, PZa, PZpl, PZpm, TZa, TZp, CZ, SV, urethra) with the view's level.
- Coronal view: zone prostate, with the level and image side of the magenta region.
- Sagittal view: zone anterior or posterior, with the level of the magenta region and image_side none.

image_side is the position on the page: left or right half of the image, midline for the urethra. It is never the patient's side. Do not use side letters to change it.

Before you answer, scan the whole crop again for faint or marginal ink, and check the coordinate order of every polygon and box.
