import { NextRequest, NextResponse } from "next/server";

function backendBase(): string {
  return (
    process.env.BACKEND_URL ||
    process.env.NEXT_PUBLIC_API_URL ||
    "http://127.0.0.1:8000"
  ).replace(/\/$/, "");
}

export async function middleware(req: NextRequest) {
  const suffix = req.nextUrl.pathname.replace(/^\/api\/?/, "");
  const target = `${backendBase()}/api/${suffix}${req.nextUrl.search}`;

  const headers = new Headers();
  req.headers.forEach((v, k) => {
    const lk = k.toLowerCase();
    if (!["host", "connection", "content-length"].includes(lk)) headers.set(k, v);
  });

  const method = req.method;
  let body: BodyInit | undefined;
  if (method !== "GET" && method !== "HEAD") {
    body = req.body ?? undefined;
  }

  try {
    const res = await fetch(target, {
      method,
      headers,
      body,
      // Required when forwarding a streaming request body (Node fetch).
      duplex: "half",
    } as RequestInit);

    const out = new NextResponse(res.body, {
      status: res.status,
      statusText: res.statusText,
    });
    res.headers.forEach((v, k) => {
      const lk = k.toLowerCase();
      if (!["transfer-encoding", "connection"].includes(lk)) out.headers.set(k, v);
    });
    return out;
  } catch (err) {
    const message = err instanceof Error ? err.message : "Backend unreachable";
    return NextResponse.json(
      {
        error: "Backend API unreachable",
        detail: message,
        hint: "Start the API: cd backend && uvicorn app.main:app --reload --port 8000",
        target,
      },
      { status: 503 },
    );
  }
}

export const config = {
  matcher: "/api/:path*",
};
