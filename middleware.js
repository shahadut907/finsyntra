// Vercel Routing Middleware: authenticate this proxy to the FinSyntra API.
//
// The API recovers a visitor's address from X-Forwarded-For. Only requests that
// carry the shared secret below may use the extra hop that Vercel adds, so a
// client that calls the Render origin directly (and forges X-Forwarded-For)
// cannot pass itself off as another address. The secret lives in the Vercel
// project environment (EDGE_PROXY_SECRET) and on the Render service; never in
// this repository. Any client-supplied X-Finsyntra-Edge header is overwritten.
//
// Written against the middleware wire protocol directly so the static project
// needs no build step or dependency.

export const config = {
  matcher: ['/api/:path*', '/auth/:path*', '/health'],
};

const API_ORIGIN = 'https://finsyntra-demo-api.onrender.com';
const EDGE_HEADER = 'x-finsyntra-edge';

export default function middleware(request) {
  const secret = (process.env.EDGE_PROXY_SECRET || '').trim();
  const headers = new Headers();

  if (!secret) {
    // Not configured: continue to the vercel.json rewrites unchanged.
    headers.set('x-middleware-next', '1');
    return new Response(null, { headers });
  }

  const url = new URL(request.url);
  const names = new Set();
  request.headers.forEach((value, name) => {
    if (name.toLowerCase() === EDGE_HEADER) return;
    names.add(name.toLowerCase());
    headers.set(`x-middleware-request-${name.toLowerCase()}`, value);
  });
  names.add(EDGE_HEADER);
  headers.set(`x-middleware-request-${EDGE_HEADER}`, secret);
  headers.set('x-middleware-override-headers', Array.from(names).join(','));
  headers.set('x-middleware-rewrite', `${API_ORIGIN}${url.pathname}${url.search}`);
  return new Response(null, { headers });
}
