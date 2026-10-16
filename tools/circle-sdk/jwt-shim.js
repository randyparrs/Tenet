// Circle's Web SDK only uses jsonwebtoken.decode (it reads the userToken payload without verifying it).
// This does the same in the browser, without jsonwebtoken's Node dependencies.
export function decode(token) {
  const part = String(token || "").split(".")[1];
  if (!part) return null;
  try {
    const b64 = part.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((part.length + 3) % 4);
    return JSON.parse(atob(b64));
  } catch {
    return null;
  }
}
export default { decode };
