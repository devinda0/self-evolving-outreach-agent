function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("Failed to load flyer preview image."));
    image.src = url;
  });
}

export async function captureIframeContentAsPngDataUrl(
  iframe: HTMLIFrameElement,
  scale = 2,
): Promise<string | null> {
  const doc = iframe.contentDocument;
  const root = doc?.body?.firstElementChild as HTMLElement | null;
  if (!doc || !root) return null;

  const bounds = root.getBoundingClientRect();
  const width = Math.max(Math.ceil(root.scrollWidth || bounds.width), 1);
  const height = Math.max(Math.ceil(root.scrollHeight || bounds.height), 1);
  const maxSide = Math.max(width, height);
  const maxScale = Math.max(1, Math.floor(6012 / maxSide) || 1);
  const targetScale = Math.min(scale, maxScale);

  const clonedRoot = root.cloneNode(true) as HTMLElement;
  clonedRoot.setAttribute("xmlns", "http://www.w3.org/1999/xhtml");

  const serialized = new XMLSerializer().serializeToString(clonedRoot);
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
      <foreignObject width="100%" height="100%">${serialized}</foreignObject>
    </svg>
  `.trim();

  const blob = new Blob([svg], { type: "image/svg+xml;charset=utf-8" });
  const objectUrl = URL.createObjectURL(blob);

  try {
    const image = await loadImage(objectUrl);
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(width * targetScale));
    canvas.height = Math.max(1, Math.round(height * targetScale));

    const context = canvas.getContext("2d");
    if (!context) throw new Error("Canvas rendering is unavailable.");

    context.scale(targetScale, targetScale);
    context.drawImage(image, 0, 0, width, height);

    return canvas.toDataURL("image/png");
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}
