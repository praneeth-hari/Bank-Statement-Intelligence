import type { BBox, PageInfo } from "../types";

/** Position a PDF-point box over a page image that is shown at any size, as percentages. */
export function boxStyle(b: BBox, page: PageInfo, padPt = 1.5): Record<string, string> {
  const x0 = Math.max(0, b.x0 - padPt), y0 = Math.max(0, b.y0 - padPt);
  const x1 = Math.min(page.width, b.x1 + padPt), y1 = Math.min(page.height, b.y1 + padPt);
  return {
    left: `${(x0 / page.width) * 100}%`,
    top: `${(y0 / page.height) * 100}%`,
    width: `${((x1 - x0) / page.width) * 100}%`,
    height: `${((y1 - y0) / page.height) * 100}%`,
  };
}

/** CSS to show just the region around a box, enlarged, using the page image as a background. */
export function cropStyle(b: BBox, page: PageInfo, maxWidthPx: number, targetHeightPx = 48,
                          padPt = 3): { width: number; height: number; backgroundSize: string; backgroundPosition: string } {
  const w = b.x1 - b.x0 + padPt * 2, h = b.y1 - b.y0 + padPt * 2;
  const zoom = Math.min(5, targetHeightPx / h, maxWidthPx / w);  // pixels per PDF point
  return {
    width: Math.round(w * zoom),
    height: Math.round(h * zoom),
    backgroundSize: `${page.width * zoom}px ${page.height * zoom}px`,
    backgroundPosition: `${-(b.x0 - padPt) * zoom}px ${-(b.y0 - padPt) * zoom}px`,
  };
}
