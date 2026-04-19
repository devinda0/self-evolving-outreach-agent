import html2canvas from "html2canvas";

function getTargetScale(width: number, height: number, preferredScale: number): number {
  const maxSide = Math.max(width, height, 1);
  const maxScale = Math.max(1, Math.floor(6012 / maxSide) || 1);
  return Math.min(preferredScale, maxScale);
}

export async function captureIframeContentAsPngDataUrl(
  iframe: HTMLIFrameElement,
  scale = 2,
): Promise<string | null> {
  const doc = iframe.contentDocument;
  const root = doc?.body?.firstElementChild as HTMLElement | null;
  if (!doc || !root) return null;

  const rect = root.getBoundingClientRect();
  const width = Math.max(Math.ceil(root.scrollWidth || rect.width), 1);
  const height = Math.max(Math.ceil(root.scrollHeight || rect.height), 1);
  const targetScale = getTargetScale(width, height, scale);

  // Give the iframe a paint tick so the latest layout/styles are committed.
  await new Promise((resolve) => requestAnimationFrame(() => resolve(undefined)));

  const canvas = await html2canvas(root, {
    backgroundColor: null,
    scale: targetScale,
    useCORS: true,
    logging: false,
    width,
    height,
    windowWidth: width,
    windowHeight: height,
  });

  return canvas.toDataURL("image/png");
}
