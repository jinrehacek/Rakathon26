# PI-RADS v2.1 sector map resolution search

Checked 2026-10-16. I found no higher-resolution copy of the same 2019 PI-RADS v2.1 map than the existing [map](../reference/pirads_v2.1_sector_map.png), which is 1342 × 1737 pixels.

The official ACR resource page links the 2019 PI-RADS v2.1 PDF. Its Appendix II sector map is an embedded 1342 × 1737 JPEG at 220 ppi. The PDF's Figure 16, on printed page 68 (PDF page 75), is another copy of the same diagram, embedded as a 1264 × 1635 JPEG at 192 × 210 ppi. Neither is vector artwork. The ACR download is byte-for-byte identical to the PDF supplied with this project, so it cannot improve the existing extraction. [ACR PI-RADS resource page](https://www.acr.org/Clinical-Resources/Clinical-Tools-and-Reference/Reporting-and-Data-Systems/PI-RADS) · [ACR 2019 PDF](https://edge.sitecorecloud.io/americancoldf5f-acrorgf92a-productioncb02-3650/media/ACR/Files/RADS/PI-RADS/PIRADS-2019.pdf)

I inspected these additional copies:

- The [APIMR PDF mirror](https://apimr.pt/wp-content/uploads/2021/05/PIRADS-V2-1.pdf) has the same SHA-256 as the ACR PDF and the supplied PDF: `594e618213e76205a5a91ca3df488274b0f6f42325b173581577da556cf2b4f2`.
- The [Dartmouth PDF mirror](https://geiselmed.dartmouth.edu/radiology/wp-content/uploads/sites/47/2024/04/PIRADS-V2.1_2019.pdf) embeds the Appendix II map at 1342 × 1737 and Figure 16 at 1264 × 1635. It offers no pixel-count gain.
- The [RadClarity standalone map](https://radclarity1.squarespace.com/pirads) image URL ends in `.png`, but the downloaded file is WebP. Its decoded dimensions are 806 × 953. Visual inspection showed the same general diagram at lower resolution.
- [RadCalc's map page](https://radcalc.online/pirads-map/) uses `template_final-PZPM-sized.jpg` as its canvas background. That image is 500 × 696 pixels, so the page's download cannot improve resolution.
- The [PMC article on PI-RADS v2.1](https://pmc.ncbi.nlm.nih.gov/articles/PMC8252188/) labels Figure 1 as a 41-zone sector map. I could not retrieve its standalone figure from the PMC URL during this check, so I did not compare its pixels or treat it as a verified copy of the ACR illustration.

I compared the downloaded ACR page-75 image and the two standalone maps visually with the current project asset. The ACR Appendix II image remains the largest verified copy of this same diagram. No new map file was added, and the existing map was left untouched.
