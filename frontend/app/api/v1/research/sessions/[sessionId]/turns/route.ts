import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const maxDuration = 300;

const BACKEND = (process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000").replace(/\/+$/, "");
const PROXY_TIMEOUT_MS = 240_000;

type RouteContext = {
  params: Promise<{ sessionId: string }>;
};

function jsonError(detail: string, status: number): NextResponse {
  return NextResponse.json({ detail }, { status });
}

function forwardHeaders(request: NextRequest): Headers {
  const headers = new Headers();
  headers.set("content-type", request.headers.get("content-type") ?? "application/json");

  const authorization = request.headers.get("authorization");
  if (authorization) {
    headers.set("authorization", authorization);
  }

  const cookie = request.headers.get("cookie");
  if (cookie) {
    headers.set("cookie", cookie);
  }

  return headers;
}

export async function POST(request: NextRequest, context: RouteContext): Promise<NextResponse> {
  const { sessionId } = await context.params;
  const body = await request.text();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), PROXY_TIMEOUT_MS);

  try {
    const backendResponse = await fetch(
      `${BACKEND}/api/v1/research/sessions/${encodeURIComponent(sessionId)}/turns`,
      {
        method: "POST",
        headers: forwardHeaders(request),
        body,
        signal: controller.signal,
        cache: "no-store",
      }
    );

    const responseBody = await backendResponse.text();
    const contentType = backendResponse.headers.get("content-type") ?? "application/json";

    return new NextResponse(responseBody, {
      status: backendResponse.status,
      headers: {
        "content-type": contentType,
        "x-ai-journalist-proxy": "research-sessions-turn",
      },
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      return jsonError(
        "Follow-up research is taking longer than expected. Please try a narrower request.",
        504
      );
    }
    return jsonError("Could not connect to the research service. Please try again.", 502);
  } finally {
    clearTimeout(timeout);
  }
}
